#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
DRAC RAID specific methods
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils
import sushy
import tenacity

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import raid as redfish_raid
from ironic.drivers.modules.redfish import utils as redfish_utils

sushy_oem_idrac = importutils.try_import('sushy_oem_idrac')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


def _wait_till_realtime_ready(task):
    """Waits till real time operations are ready to be executed.

    Useful for RAID operations where almost all controllers support
    real time configuration, but controllers might not be ready for
    it by the time IPA starts executing steps. It can take minute or
    bit more to be ready for real time configuration.

    :param task: TaskManager object containing the node.
    :raises RedfishError: If can't find OEM extension or it fails to
        execute
    """
    # If running without IPA, check that system is ON, if not, turn it on
    disable_ramdisk = task.node.driver_internal_info.get(
        'cleaning_disable_ramdisk')
    power_state = task.driver.power.get_power_state(task)
    if disable_ramdisk and power_state == states.POWER_OFF:
        task.driver.power.set_power_state(task, states.POWER_ON)

    try:
        _retry_till_realtime_ready(task)
    except tenacity.RetryError:
        LOG.debug('Retries exceeded while waiting for real-time ready '
                  'for node %(node)s. Will proceed with out real-time '
                  'ready state', {'node': task.node.uuid})


@tenacity.retry(
    stop=(tenacity.stop_after_attempt(30)),
    wait=tenacity.wait_fixed(10),
    retry=tenacity.retry_if_result(lambda result: not result))
def _retry_till_realtime_ready(task):
    """Retries till real time operations are ready to be executed.

    :param task: TaskManager object containing the node.
    :raises RedfishError: If can't find OEM extension or it fails to
        execute
    :raises RetryError: If retries exceeded and still not ready for real-time
    """
    return _is_realtime_ready(task)


def _is_realtime_ready(task):
    """Gets is real time ready status

    Uses sushy-oem-idrac extension.

    :param task: TaskManager object containing the node.
    :returns: True, if real time operations are ready, otherwise False.
    :raises RedfishError: If can't find OEM extension or it fails to
        execute
    """
    return drac_utils.execute_oem_manager_method(
        task, 'get real-time ready status',
        lambda m: m.lifecycle_service.is_realtime_ready())


class DracRedfishRAID(redfish_raid.RedfishRAID):
    """iDRAC Redfish interface for RAID related actions.

    Includes iDRAC specific adjustments for RAID related actions.
    """

    @base.clean_step(priority=0, abortable=False, argsinfo={
        'create_root_volume': {
            'description': (
                'This specifies whether to create the root volume. '
                'Defaults to `True`.'
            ),
            'required': False
        },
        'create_nonroot_volumes': {
            'description': (
                'This specifies whether to create the non-root volumes. '
                'Defaults to `True`.'
            ),
            'required': False
        },
        'delete_existing': {
            'description': (
                'Setting this to `True` indicates to delete existing RAID '
                'configuration prior to creating the new configuration. '
                'Default value is `False`.'
            ),
            'required': False,
        }
    }, requires_ramdisk=False)
    def create_configuration(self, task, create_root_volume=True,
                             create_nonroot_volumes=True,
                             delete_existing=False):
        """Create RAID configuration on the node.

        This method creates the RAID configuration as read from
        node.target_raid_config.  This method
        by default will create all logical disks.

        :param task: TaskManager object containing the node.
        :param create_root_volume: Setting this to False indicates
            not to create root volume that is specified in the node's
            target_raid_config. Default value is True.
        :param create_nonroot_volumes: Setting this to False indicates
            not to create non-root volumes (all except the root volume) in
            the node's target_raid_config.  Default value is True.
        :param delete_existing: Setting this to True indicates to delete RAID
            configuration prior to creating the new configuration. Default is
            False.
        :returns: states.CLEANWAIT if RAID configuration is in progress
            asynchronously or None if it is complete.
        :raises: RedfishError if there is an error creating the configuration
        """
        _wait_till_realtime_ready(task)
        return super(DracRedfishRAID, self).create_configuration(
            task, create_root_volume, create_nonroot_volumes,
            delete_existing)

    @base.clean_step(priority=0, requires_ramdisk=False)
    @base.deploy_step(priority=0)
    def delete_configuration(self, task):
        """Delete RAID configuration on the node.

        :param task: TaskManager object containing the node.
        :returns: states.CLEANWAIT (cleaning) or states.DEPLOYWAIT (deployment)
            if deletion is in progress asynchronously or None if it is
            complete.
        """
        _wait_till_realtime_ready(task)
        return super(DracRedfishRAID, self).delete_configuration(task)

    def _validate_vendor(self, task):
        pass  # for now assume idrac-redfish is used with iDRAC BMC, thus pass

    def pre_create_configuration(self, task, logical_disks_to_create):
        """Perform required actions before creating config.

        Converts any physical disks of selected controllers to RAID mode
        if in non-RAID mode.

        :param task: a TaskManager instance containing the node to act on.
        :param logical_disks_to_create: list of logical disks to create.
        :returns: updated list of logical disks to create
        """
        system = redfish_utils.get_system(task.node)
        controller_to_disks = {}
        for logical_disk in logical_disks_to_create:
            storage, controller = DracRedfishRAID._get_storage_controller(
                system, logical_disk.get('controller'))
            controller_to_disks[controller] = []
            for drive in storage.drives:
                if drive.identity in logical_disk.get('physical_disks'):
                    controller_to_disks[controller].append(drive)

        converted = DracRedfishRAID._change_physical_disk_state(
            system,
            sushy_oem_idrac.PHYSICAL_DISK_STATE_MODE_RAID,
            controller_to_disks)

        if converted:
            # Recalculate sizes as disks size changes after conversion
            return DracRedfishRAID._get_revalidated_logical_disks(
                task.node, system, logical_disks_to_create)
        else:
            return logical_disks_to_create

    def post_delete_configuration(self, task, raid_configs, return_state=None):
        """Perform post delete_configuration action to commit the config.

        Clears foreign configuration for all RAID controllers.
        If no foreign configuration to clear, then checks if any controllers
        can be converted to RAID mode.

        :param task: a TaskManager instance containing the node to act on.
        :param raid_configs: a list of dictionaries containing the RAID
                             configuration operation details.
        :param return_state: state to return based on operation being invoked
        """

        system = redfish_utils.get_system(task.node)
        async_proc = DracRedfishRAID._clear_foreign_config(system, task)
        if async_proc:
            # Async processing with system rebooting in progress
            task.node.set_driver_internal_info(
                'raid_config_substep', 'clear_foreign_config')
            task.node.save()
            return deploy_utils.get_async_step_return_state(task.node)
        else:
            conv_state = DracRedfishRAID._convert_controller_to_raid_mode(
                task)
            if conv_state:
                return conv_state

        return return_state

    @staticmethod
    def _get_storage_controller(system, identity):
        """Finds storage and controller by identity

        :param system: Redfish system
        :param identity: identity of controller to find
        :returns: Storage and its controller
        """
        for storage in system.storage.get_members():
            if storage.identity == identity:
                controller = redfish_utils.get_first_controller(storage)
                if controller:
                    return storage, controller

        raise exception.IronicException(
            (_("Couldn't find storage by '%(identity)s'"),
             {'identity': identity}))

    @staticmethod
    def _change_physical_disk_state(system, mode, controller_to_disks=None):
        """Changes physical disk state and waits for it to complete

        :param system: Redfish system
        :param mode: sushy_oem_idrac.PHYSICAL_DISK_STATE_MODE_RAID or
            sushy_oem_idrac.PHYSICAL_DISK_STATE_MODE_NONRAID
        :controller_to_disks: dictionary of controllers and their
            drives. Optional. If not provided, then converting all
            eligible drives on system.
        :returns: True if any drive got converted, otherwise False
        """
        oem_sys = system.get_oem_extension('Dell')
        try:
            task_mons = oem_sys.change_physical_disk_state(
                mode, controller_to_disks)
        except AttributeError as ae:
            # For backported version where libraries could be too old
            LOG.warning('Failed to find method to convert drives to RAID '
                        'mode. Possibly because `sushy-oem-idrac` is too old. '
                        'Without newer `sushy-oem-idrac` RAID configuration '
                        'will fail if selected physical disks are in non-RAID '
                        'mode. To avoid that update `sushy-oem-idrac`. '
                        'Error: %(err)s', {'err': ae})
            return False

        for task_mon in task_mons:
            # All jobs should be real-time, because all RAID controllers
            # that offer physical disk mode conversion support real-time
            # task execution. Note that BOSS does not offer disk mode
            # conversion nor support real-time task execution.
            if task_mon.check_is_processing:
                task_mon.wait(CONF.drac.raid_job_timeout)

        return bool(task_mons)

    @staticmethod
    def _get_revalidated_logical_disks(
            node, system, logical_disks_to_create):
        """Revalidates calculated volume size after RAID mode conversion

        :param node: an Ironic node
        :param system: Redfish system
        :param logical_disks_to_create:
        :returns: Revalidated logical disk list. If no changes in size,
            same as input `logical_disks_to_create`
        """
        new_physical_disks, disk_to_controller =\
            redfish_raid.get_physical_disks(node)
        free_space_bytes = {}
        for disk in new_physical_disks:
            free_space_bytes[disk] = disk.capacity_bytes

        new_processed_volumes = []
        for logical_disk in logical_disks_to_create:
            selected_disks = [disk for disk in new_physical_disks
                              if disk.identity
                              in logical_disk['physical_disks']]

            spans_count = redfish_raid._calculate_spans(
                logical_disk['raid_level'], len(selected_disks))
            new_max_vol_size_bytes = redfish_raid._max_volume_size_bytes(
                logical_disk['raid_level'], selected_disks, free_space_bytes,
                spans_count=spans_count)
            if logical_disk['size_bytes'] > new_max_vol_size_bytes:
                logical_disk['size_bytes'] = new_max_vol_size_bytes
                LOG.info("Logical size does not match so calculating volume "
                         "properties for current logical_disk")
                redfish_raid._calculate_volume_props(
                    logical_disk, new_physical_disks, free_space_bytes,
                    disk_to_controller)
                new_processed_volumes.append(logical_disk)

        if new_processed_volumes:
            return new_processed_volumes

        return logical_disks_to_create

    @staticmethod
    def _clear_foreign_config(system, task):
        """Clears foreign config for given system

        :param system: Redfish system
        :param task: a TaskManager instance containing the node to act on
        :returns: True if system needs rebooting and async processing for
            tasks necessary, otherwise False
        """
        oem_sys = system.get_oem_extension('Dell')
        try:
            task_mons = oem_sys.clear_foreign_config()
        except AttributeError as ae:
            # For backported version where libraries could be too old
            LOG.warning('Failed to find method to clear foreign config. '
                        'Possibly because `sushy-oem-idrac` is too old. '
                        'Without newer `sushy-oem-idrac` no foreign '
                        'configuration will be cleared if there is any. '
                        'To avoid that update `sushy-oem-idrac`. '
                        'Error: %(err)s', {'err': ae})
            return False

        # Check if any of tasks requires reboot
        for task_mon in task_mons:
            oem_task = task_mon.get_task().get_oem_extension('Dell')
            if oem_task.job_type == sushy_oem_idrac.JOB_TYPE_RAID_CONF:
                # System rebooting, prepare ramdisk to boot back in IPA
                deploy_utils.set_async_step_flags(
                    task.node,
                    reboot=True,
                    skip_current_step=True,
                    polling=True)
                deploy_utils.prepare_agent_boot(task)
                # Reboot already done by non real time task
                task.upgrade_lock()
                task.node.set_driver_internal_info(
                    'raid_task_monitor_uris',
                    [tm.task_monitor_uri for tm in task_mons])
                task.node.save()
                return True

        # No task requiring reboot found, proceed with waiting for sync tasks
        for task_mon in task_mons:
            if task_mon.check_is_processing:
                task_mon.wait(CONF.drac.raid_job_timeout)
        return False

    @staticmethod
    def _convert_controller_to_raid_mode(task):
        """Convert eligible controllers to RAID mode if not already.

        :param task: a TaskManager instance containing the node to act on
        :returns: Return state if there are controllers to convert and
            and rebooting, otherwise None.
        """

        system = redfish_utils.get_system(task.node)
        task_mons = []
        warning_msg_templ = (
            'Possibly because `%(pkg)s` is too old. Without newer `%(pkg)s` '
            'PERC 9 and PERC 10 controllers that are not in RAID mode will '
            'not be used or have limited RAID support. To avoid that update '
            '`%(pkg)s`')
        for storage in system.storage.get_members():
            storage_controllers = None
            try:
                storage_controllers = storage.controllers
            except sushy.exceptions.MissingAttributeError:
                # Check if there storage_controllers to separate old iDRAC and
                # storage without controller
                if storage.storage_controllers:
                    LOG.warning('%(storage)s does not have controllers for '
                                'node %(node)s' + warning_msg_templ,
                                {'storage': storage.identity,
                                 'node': task.node.uuid,
                                 'pkg': 'iDRAC'})
                continue
            except AttributeError:
                LOG.warning('%(storage)s does not have controllers attribute. '
                            + warning_msg_templ, {'storage': storage.identity,
                                                  'pkg': 'sushy'})
                return None
            if storage_controllers:
                controller = storage.controllers.get_members()[0]
                try:
                    oem_controller = controller.get_oem_extension('Dell')
                except sushy.exceptions.ExtensionError as ee:
                    LOG.warning('Failed to find extension to convert '
                                'controller to RAID mode. '
                                + warning_msg_templ + '. Error: %(err)s',
                                {'err': ee, 'pkg': 'sushy-oem-idrac'})
                    return None
                task_mon = oem_controller.convert_to_raid()
                if task_mon:
                    task_mons.append(task_mon)

        if task_mons:
            deploy_utils.set_async_step_flags(
                task.node,
                reboot=True,
                skip_current_step=True,
                polling=True)

            task.upgrade_lock()
            task.node.set_driver_internal_info(
                'raid_task_monitor_uris',
                [tm.task_monitor_uri for tm in task_mons])
            task.node.save()
            return deploy_utils.reboot_to_finish_step(task)

    @METRICS.timer('DracRedfishRAID._query_raid_tasks_status')
    @periodics.node_periodic(
        purpose='checking async RAID tasks',
        spacing=CONF.drac.query_raid_config_job_status_interval,
        filters={'reserved': False, 'maintenance': False},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: (
            n.driver_internal_info.get('raid_task_monitor_uris')
        ),
    )
    def _query_raid_tasks_status(self, task, manager, context):
        """Periodic task to check the progress of running RAID tasks"""
        self._check_raid_tasks_status(
            task, task.node.driver_internal_info.get('raid_task_monitor_uris'))

    def _check_raid_tasks_status(self, task, task_mon_uris):
        """Checks RAID tasks for completion

        If at least one of the jobs failed, then all step failed.
        If some tasks are still running, they are checked in next period.
        """
        node = task.node
        completed_task_mon_uris = []
        failed_msgs = []
        for task_mon_uri in task_mon_uris:
            task_mon = redfish_utils.get_task_monitor(node, task_mon_uri)
            if not task_mon.is_processing:
                raid_task = task_mon.get_task()
                completed_task_mon_uris.append(task_mon_uri)
                if not (raid_task.task_state == sushy.TASK_STATE_COMPLETED
                        and raid_task.task_status in
                        [sushy.HEALTH_OK, sushy.HEALTH_WARNING]):
                    messages = [m.message for m in raid_task.messages
                                if m.message is not None]
                    failed_msgs.append(
                        (_("Task %(task_mon_uri)s. "
                            "Message: '%(message)s'.")
                            % {'task_mon_uri': task_mon_uri,
                               'message': ', '.join(messages)}))

        task.upgrade_lock()
        if failed_msgs:
            error_msg = (_("Failed RAID configuration tasks: %(messages)s")
                         % {'messages': ', '.join(failed_msgs)})
            log_msg = ("RAID configuration task failed for node "
                       "%(node)s. %(error)s" % {'node': node.uuid,
                                                'error': error_msg})
            node.del_driver_internal_info('raid_task_monitor_uris')
            self._set_failed(task, log_msg, error_msg)
        else:
            running_task_mon_uris = [x for x in task_mon_uris
                                     if x not in completed_task_mon_uris]
            if running_task_mon_uris:
                node.set_driver_internal_info('raid_task_monitor_uris',
                                              running_task_mon_uris)
                # will check remaining jobs in the next period
            else:
                # all tasks completed and none of them failed
                node.del_driver_internal_info('raid_task_monitor_uris')
                substep = node.driver_internal_info.get(
                    'raid_config_substep')
                if substep == 'clear_foreign_config':
                    node.del_driver_internal_info('raid_config_substep')
                    node.save()
                    res = DracRedfishRAID._convert_controller_to_raid_mode(
                        task)
                    if res:  # New tasks submitted
                        return
                self._set_success(task)
        node.save()

    def _set_failed(self, task, log_msg, error_msg):
        if task.node.clean_step:
            manager_utils.cleaning_error_handler(task, log_msg, error_msg)
        else:
            manager_utils.deploying_error_handler(task, log_msg, error_msg)

    def _set_success(self, task):
        if task.node.clean_step:
            manager_utils.notify_conductor_resume_clean(task)
        else:
            manager_utils.notify_conductor_resume_deploy(task)
