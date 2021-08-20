# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2017-2021 Dell Inc. or its subsidiaries.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
DRAC management interface
"""

import json
import time

from futurist import periodics
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import molds
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import management as redfish_management
from ironic.drivers.modules.redfish import utils as redfish_utils


drac_exceptions = importutils.try_import('dracclient.exceptions')
sushy = importutils.try_import('sushy')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

# This dictionary is used to map boot device names between two (2) name
# spaces. The name spaces are:
#
#     1) ironic boot devices
#     2) iDRAC boot sources
#
# Mapping can be performed in both directions.
#
# The keys are ironic boot device types. Each value is a list of strings
# that appear in the identifiers of iDRAC boot sources.
#
# The iDRAC represents boot sources with class DCIM_BootSourceSetting
# [1]. Each instance of that class contains a unique identifier, which
# is called an instance identifier, InstanceID,
#
# An InstanceID contains the Fully Qualified Device Descriptor (FQDD) of
# the physical device that hosts the boot source [2].
#
# [1] "Dell EMC BIOS and Boot Management Profile", Version 4.0.0, July
#     10, 2017, Section 7.2 "Boot Management", pp. 44-47 --
#     http://en.community.dell.com/techcenter/extras/m/white_papers/20444495/download
# [2] "Lifecycle Controller Version 3.15.15.15 User's Guide", Dell EMC,
#     2017, Table 13, "Easy-to-use Names of System Components", pp. 71-74 --
#     http://topics-cdn.dell.com/pdf/idrac9-lifecycle-controller-v3.15.15.15_users-guide2_en-us.pdf
_BOOT_DEVICES_MAP = {
    boot_devices.DISK: ['AHCI', 'Disk', 'RAID'],
    boot_devices.PXE: ['NIC'],
    boot_devices.CDROM: ['Optical'],
}

_DRAC_BOOT_MODES = ['Bios', 'Uefi']

# BootMode constant
_NON_PERSISTENT_BOOT_MODE = 'OneTime'

# Clear job id's constant
_CLEAR_JOB_IDS = 'JID_CLEARALL'

# Clean steps constant
_CLEAR_JOBS_CLEAN_STEPS = ['clear_job_queue', 'known_good_state']


def _get_boot_device(node, drac_boot_devices=None):
    client = drac_common.get_drac_client(node)

    try:
        boot_modes = client.list_boot_modes()
        next_boot_modes = [mode.id for mode in boot_modes if mode.is_next]
        if _NON_PERSISTENT_BOOT_MODE in next_boot_modes:
            next_boot_mode = _NON_PERSISTENT_BOOT_MODE
        else:
            next_boot_mode = next_boot_modes[0]

        if drac_boot_devices is None:
            drac_boot_devices = client.list_boot_devices()

        # It is possible for there to be no boot device.
        boot_device = None

        if next_boot_mode in drac_boot_devices:
            drac_boot_device = drac_boot_devices[next_boot_mode][0]

            for key, value in _BOOT_DEVICES_MAP.items():
                for id_component in value:
                    if id_component in drac_boot_device.id:
                        boot_device = key
                        break

                if boot_device:
                    break

        return {'boot_device': boot_device,
                'persistent': next_boot_mode != _NON_PERSISTENT_BOOT_MODE}
    except (drac_exceptions.BaseClientException, IndexError) as exc:
        LOG.error('DRAC driver failed to get next boot mode for '
                  'node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


def _get_next_persistent_boot_mode(node):
    client = drac_common.get_drac_client(node)

    try:
        boot_modes = client.list_boot_modes()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get next persistent boot mode for '
                  'node %(node_uuid)s. Reason: %(error)s',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)

    next_persistent_boot_mode = None
    for mode in boot_modes:
        if mode.is_next and mode.id != _NON_PERSISTENT_BOOT_MODE:
            next_persistent_boot_mode = mode.id
            break

    if not next_persistent_boot_mode:
        message = _('List of boot modes, %(list_boot_modes)s, does not '
                    'contain a persistent mode') % {
                        'list_boot_modes': boot_modes}
        LOG.error('DRAC driver failed to get next persistent boot mode for '
                  'node %(node_uuid)s. Reason: %(message)s',
                  {'node_uuid': node.uuid, 'message': message})
        raise exception.DracOperationError(error=message)

    return next_persistent_boot_mode


def _is_boot_order_flexibly_programmable(persistent, bios_settings):
    return persistent and 'SetBootOrderFqdd1' in bios_settings


def _flexibly_program_boot_order(device, drac_boot_mode):
    if device == boot_devices.DISK:
        if drac_boot_mode == 'Bios':
            bios_settings = {'SetBootOrderFqdd1': 'HardDisk.List.1-1'}
        else:
            # 'Uefi'
            bios_settings = {
                'SetBootOrderFqdd1': '*.*.*',  # Disks, which are all else
                'SetBootOrderFqdd2': 'NIC.*.*',
                'SetBootOrderFqdd3': 'Optical.*.*',
                'SetBootOrderFqdd4': 'Floppy.*.*',
            }
    elif device == boot_devices.PXE:
        bios_settings = {'SetBootOrderFqdd1': 'NIC.*.*'}
    else:
        # boot_devices.CDROM
        bios_settings = {'SetBootOrderFqdd1': 'Optical.*.*'}

    return bios_settings


def set_boot_device(node, device, persistent=False):
    """Set the boot device for a node.

    Set the boot device to use on next boot of the node.

    :param node: an ironic node object.
    :param device: the boot device, one of
                   :mod:`ironic.common.boot_devices`.
    :param persistent: Boolean value. True if the boot device will
                       persist to all future boots, False if not.
                       Default: False.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    # If pending BIOS job or pending non-BIOS job found in job queue,
    # we need to clear that jobs before executing clear_job_queue or
    # known_good_state clean step of management interface.
    # Otherwise, pending BIOS config job can cause creating new config jobs
    # to fail and pending non-BIOS job can execute on reboot the node.
    validate_job_queue = True
    if node.driver_internal_info.get("clean_steps"):
        if node.driver_internal_info.get("clean_steps")[0].get(
                'step') in _CLEAR_JOBS_CLEAN_STEPS:
            unfinished_jobs = drac_job.list_unfinished_jobs(node)
            if unfinished_jobs:
                validate_job_queue = False
                client.delete_jobs(job_ids=[job.id for job in unfinished_jobs])

    if validate_job_queue:
        drac_job.validate_job_queue(node)

    try:
        drac_boot_devices = client.list_boot_devices()

        current_boot_device = _get_boot_device(node, drac_boot_devices)
        # If we are already booting from the right device, do nothing.
        if current_boot_device == {'boot_device': device,
                                   'persistent': persistent}:
            LOG.debug('DRAC already set to boot from %s', device)
            return

        persistent_boot_mode = _get_next_persistent_boot_mode(node)

        drac_boot_device = None
        for drac_device in drac_boot_devices[persistent_boot_mode]:
            for id_component in _BOOT_DEVICES_MAP[device]:
                if id_component in drac_device.id:
                    drac_boot_device = drac_device.id
                    break

            if drac_boot_device:
                break

        if drac_boot_device:
            if persistent:
                boot_list = persistent_boot_mode
            else:
                boot_list = _NON_PERSISTENT_BOOT_MODE

            client.change_boot_device_order(boot_list, drac_boot_device)
        else:
            # No DRAC boot device of the type requested by the argument
            # 'device' is present. This is normal for UEFI boot mode,
            # following deployment's writing of the operating system to
            # disk. It can also occur when a server has not been
            # powered on after a new boot device has been installed.
            #
            # If the boot order is flexibly programmable, use that to
            # attempt to detect and boot from a device of the requested
            # type during the next boot. That avoids the need for an
            # extra reboot. Otherwise, this function cannot satisfy the
            # request, because it was called with an invalid device.
            bios_settings = client.list_bios_settings(by_name=True)
            if _is_boot_order_flexibly_programmable(persistent, bios_settings):
                drac_boot_mode = bios_settings['BootMode'].current_value
                if drac_boot_mode not in _DRAC_BOOT_MODES:
                    message = _("DRAC reported unknown boot mode "
                                "'%(drac_boot_mode)s'") % {
                                    'drac_boot_mode': drac_boot_mode}
                    LOG.error('DRAC driver failed to change boot device order '
                              'for node %(node_uuid)s. Reason: %(message)s.',
                              {'node_uuid': node.uuid, 'message': message})
                    raise exception.DracOperationError(error=message)

                flexibly_program_settings = _flexibly_program_boot_order(
                    device, drac_boot_mode)
                client.set_bios_settings(flexibly_program_settings)
            else:
                raise exception.InvalidParameterValue(
                    _("set_boot_device called with invalid device "
                      "'%(device)s' for node %(node_id)s.") %
                    {'device': device, 'node_id': node.uuid})

        job_id = client.commit_pending_bios_changes()
        job_entry = client.get_job(job_id)

        timeout = CONF.drac.boot_device_job_status_timeout
        end_time = time.time() + timeout

        LOG.debug('Waiting for BIOS configuration job %(job_id)s '
                  'to be scheduled for node %(node)s',
                  {'job_id': job_id,
                   'node': node.uuid})

        while job_entry.status != "Scheduled":
            if time.time() >= end_time:
                raise exception.DracOperationError(
                    error=_(
                        'Timed out waiting BIOS configuration for job '
                        '%(job)s to reach Scheduled state.  Job is still '
                        'in %(status)s state.') %
                    {'job': job_id, 'status': job_entry.status})
            time.sleep(3)
            job_entry = client.get_job(job_id)

    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to change boot device order for '
                  'node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid, 'error': exc})
        raise exception.DracOperationError(error=exc)


class DracRedfishManagement(redfish_management.RedfishManagement):
    """iDRAC Redfish interface for management-related actions."""

    EXPORT_CONFIGURATION_ARGSINFO = {
        "export_configuration_location": {
            "description": "URL of location to save the configuration to.",
            "required": True,
        }
    }

    IMPORT_CONFIGURATION_ARGSINFO = {
        "import_configuration_location": {
            "description": "URL of location to fetch desired configuration "
                           "from.",
            "required": True,
        }
    }

    IMPORT_EXPORT_CONFIGURATION_ARGSINFO = {**EXPORT_CONFIGURATION_ARGSINFO,
                                            **IMPORT_CONFIGURATION_ARGSINFO}

    @base.deploy_step(priority=0, argsinfo=EXPORT_CONFIGURATION_ARGSINFO)
    @base.clean_step(priority=0, argsinfo=EXPORT_CONFIGURATION_ARGSINFO)
    def export_configuration(self, task, export_configuration_location):
        """Export the configuration of the server.

        Exports the configuration of the server against which the step is run
        and stores it in specific format in indicated location.

        Uses Dell's Server Configuration Profile (SCP) from `sushy-oem-idrac`
        library to get ALL configuration for cloning.

        :param task: A task from TaskManager.
        :param export_configuration_location: URL of location to save the
            configuration to.

        :raises: MissingParameterValue if missing configuration name of a file
            to save the configuration to
        :raises: DracOperatationError when no managagers for Redfish system
            found or configuration export from SCP failed
        :raises: RedfishError when loading OEM extension failed
        """
        if not export_configuration_location:
            raise exception.MissingParameterValue(
                _('export_configuration_location missing'))

        system = redfish_utils.get_system(task.node)
        configuration = None

        if not system.managers:
            raise exception.DracOperationError(
                error=(_("No managers found for %(node)s") %
                       {'node': task.node.uuid}))

        configuration = drac_utils.execute_oem_manager_method(
            task, 'export system configuration',
            lambda m: m.export_system_configuration())

        if configuration and configuration.status_code == 200:
            configuration = {"oem": {"interface": "idrac-redfish",
                                     "data": configuration.json()}}
            molds.save_configuration(task,
                                     export_configuration_location,
                                     configuration)
        else:
            raise exception.DracOperationError(
                error=(_("No configuration exported for node %(node)s") %
                       {'node': task.node.uuid}))

    @base.deploy_step(priority=0, argsinfo=IMPORT_CONFIGURATION_ARGSINFO)
    @base.clean_step(priority=0, argsinfo=IMPORT_CONFIGURATION_ARGSINFO)
    def import_configuration(self, task, import_configuration_location):
        """Import and apply the configuration to the server.

        Gets pre-created configuration from storage by given location and
        imports that into given server. Uses Dell's Server Configuration
        Profile (SCP).

        :param task: A task from TaskManager.
        :param import_configuration_location: URL of location to fetch desired
            configuration from.

        :raises: MissingParameterValue if missing configuration name of a file
            to fetch the configuration from
        """
        if not import_configuration_location:
            raise exception.MissingParameterValue(
                _('import_configuration_location missing'))

        configuration = molds.get_configuration(task,
                                                import_configuration_location)
        if not configuration:
            raise exception.DracOperationError(
                error=(_("No configuration found for node %(node)s by name "
                         "%(configuration_name)s") %
                       {'node': task.node.uuid,
                        'configuration_name': import_configuration_location}))

        interface = configuration["oem"]["interface"]
        if interface != "idrac-redfish":
            raise exception.DracOperationError(
                error=(_("Invalid configuration for node %(node)s "
                         "in %(configuration_name)s. Supports only "
                         "idrac-redfish, but found %(interface)s") %
                       {'node': task.node.uuid,
                        'configuration_name': import_configuration_location,
                        'interface': interface}))

        task_monitor = drac_utils.execute_oem_manager_method(
            task, 'import system configuration',
            lambda m: m.import_system_configuration(
                json.dumps(configuration["oem"]["data"])),)

        info = task.node.driver_internal_info
        info['import_task_monitor_url'] = task_monitor.task_monitor_uri
        task.node.driver_internal_info = info

        deploy_utils.set_async_step_flags(
            task.node,
            reboot=True,
            skip_current_step=True,
            polling=True)
        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        manager_utils.node_power_action(task, states.REBOOT)

        return deploy_utils.get_async_step_return_state(task.node)

    @base.clean_step(priority=0,
                     argsinfo=IMPORT_EXPORT_CONFIGURATION_ARGSINFO)
    @base.deploy_step(priority=0,
                      argsinfo=IMPORT_EXPORT_CONFIGURATION_ARGSINFO)
    def import_export_configuration(self, task, import_configuration_location,
                                    export_configuration_location):
        """Import and export configuration in one go.

        Gets pre-created configuration from storage by given name and
        imports that into given server. After that exports the configuration of
        the server against which the step is run and stores it in specific
        format in indicated storage as configured by Ironic.

        :param import_configuration_location: URL of location to fetch desired
            configuration from.
        :param export_configuration_location: URL of location to save the
            configuration to.
        """
        # Import is async operation, setting sub-step to store export config
        # and indicate that it's being executed as part of composite step
        info = task.node.driver_internal_info
        info['export_configuration_location'] = export_configuration_location
        task.node.driver_internal_info = info
        task.node.save()

        return self.import_configuration(task, import_configuration_location)
        # Export executed as part of Import async periodic task status check

    @METRICS.timer('DracRedfishManagement._query_import_configuration_status')
    @periodics.periodic(
        spacing=CONF.drac.query_import_config_job_status_interval,
        enabled=CONF.drac.query_import_config_job_status_interval > 0)
    def _query_import_configuration_status(self, manager, context):
        """Period job to check import configuration task."""

        filters = {'reserved': False, 'maintenance': False}
        fields = ['driver_internal_info']
        node_list = manager.iter_nodes(fields=fields, filters=filters)
        for (node_uuid, driver, conductor_group,
             driver_internal_info) in node_list:
            try:

                task_monitor_url = driver_internal_info.get(
                    'import_task_monitor_url')
                # NOTE(TheJulia): Evaluate if a task montitor URL exists
                # based upon our inital DB query before pulling a task for
                # every node in the deployment which reduces the overall
                # number of DB queries triggering in the background where
                # no work is required.
                if not task_monitor_url:
                    continue

                lock_purpose = 'checking async import configuration task'
                with task_manager.acquire(context, node_uuid,
                                          purpose=lock_purpose,
                                          shared=True) as task:
                    if not isinstance(task.driver.management,
                                      DracRedfishManagement):
                        continue
                    self._check_import_configuration_task(
                        task, task_monitor_url)
            except exception.NodeNotFound:
                LOG.info('During _query_import_configuration_status, node '
                         '%(node)s was not found and presumed deleted by '
                         'another process.', {'node': node_uuid})
            except exception.NodeLocked:
                LOG.info('During _query_import_configuration_status, node '
                         '%(node)s was already locked by another process. '
                         'Skip.', {'node': node_uuid})

    def _check_import_configuration_task(self, task, task_monitor_url):
        """Checks progress of running import configuration task"""

        node = task.node
        task_monitor = redfish_utils.get_task_monitor(node, task_monitor_url)

        if not task_monitor.is_processing:
            import_task = task_monitor.get_task()

            task.upgrade_lock()
            info = node.driver_internal_info
            info.pop('import_task_monitor_url', None)
            node.driver_internal_info = info

            succeeded = False
            if (import_task.task_state == sushy.TASK_STATE_COMPLETED
                and import_task.task_status in
                    [sushy.HEALTH_OK, sushy.HEALTH_WARNING]):

                # Task could complete with errors (partial success)
                # iDRAC 5.00.00.00 has stopped reporting Critical messages
                # so checking also by message_id
                succeeded = not any(m.message for m in import_task.messages
                                    if (m.severity
                                        and m.severity != sushy.SEVERITY_OK)
                                    or (m.message_id and 'SYS055'
                                        in m.message_id))

            if succeeded:
                LOG.info('Configuration import %(task_monitor_url)s '
                         'successful for node %(node)s',
                         {'node': node.uuid,
                          'task_monitor_url': task_monitor_url})

                # If import executed as part of import_export_configuration
                export_configuration_location =\
                    info.get('export_configuration_location')
                if export_configuration_location:
                    # then do sync export configuration before finishing
                    self._cleanup_export_substep(node)
                    try:
                        self.export_configuration(
                            task, export_configuration_location)
                    except (sushy.exceptions.SushyError,
                            exception.IronicException) as e:
                        error_msg = (_("Failed export configuration. %(exc)s" %
                                       {'exc': e}))
                        log_msg = ("Export configuration failed for node "
                                   "%(node)s. %(error)s" %
                                   {'node': task.node.uuid,
                                    'error': error_msg})
                        self._set_failed(task, log_msg, error_msg)
                        return
                self._set_success(task)
            else:
                # Select all messages, skipping OEM messages that don't have
                # `message` field populated.
                messages = [m.message for m in import_task.messages
                            if m.message is not None
                            and ((m.severity
                                  and m.severity != sushy.SEVERITY_OK)
                                 or (m.message_id
                                     and 'SYS055' in m.message_id))]
                error_msg = (_("Failed import configuration task: "
                               "%(task_monitor_url)s. Message: '%(message)s'.")
                             % {'task_monitor_url': task_monitor_url,
                                'message': ', '.join(messages)})
                log_msg = ("Import configuration task failed for node "
                           "%(node)s. %(error)s" % {'node': task.node.uuid,
                                                    'error': error_msg})
                self._set_failed(task, log_msg, error_msg)
            node.save()
        else:
            LOG.debug('Import configuration %(task_monitor_url)s in progress '
                      'for node %(node)s',
                      {'node': node.uuid,
                       'task_monitor_url': task_monitor_url})

    def _set_success(self, task):
        if task.node.clean_step:
            manager_utils.notify_conductor_resume_clean(task)
        else:
            manager_utils.notify_conductor_resume_deploy(task)

    def _set_failed(self, task, log_msg, error_msg):
        if task.node.clean_step:
            manager_utils.cleaning_error_handler(task, log_msg, error_msg)
        else:
            manager_utils.deploying_error_handler(task, log_msg, error_msg)

    def _cleanup_export_substep(self, node):
        driver_internal_info = node.driver_internal_info
        driver_internal_info.pop('export_configuration_location', None)
        node.driver_internal_info = driver_internal_info

    @METRICS.timer('DracRedfishManagement.clear_job_queue')
    @base.clean_step(priority=0)
    def clear_job_queue(self, task):
        """Clear iDRAC job queue.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        drac_utils.execute_oem_manager_method(
            task, 'clear job queue',
            lambda m: m.job_service.delete_jobs(job_ids=['JID_CLEARALL']))

    @METRICS.timer('DracRedfishManagement.reset_idrac')
    @base.clean_step(priority=0)
    def reset_idrac(self, task):
        """Reset the iDRAC.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        drac_utils.execute_oem_manager_method(
            task, 'reset iDRAC', lambda m: m.reset_idrac())
        redfish_utils.wait_until_get_system_ready(task.node)
        LOG.info('Reset iDRAC for node %(node)s done',
                 {'node': task.node.uuid})

    @METRICS.timer('DracRedfishManagement.known_good_state')
    @base.clean_step(priority=0)
    def known_good_state(self, task):
        """Reset iDRAC to known good state.

        An iDRAC is reset to a known good state by resetting it and
        clearing its job queue.

        :param task: a TaskManager instance containing the node to act
                     on.
        :raises: RedfishError on an error.
        """
        self.reset_idrac(task)
        self.clear_job_queue(task)
        LOG.info('Reset iDRAC to known good state for node %(node)s',
                 {'node': task.node.uuid})


class DracWSManManagement(base.ManagementInterface):

    def get_properties(self):
        """Return the properties of the interface."""
        return drac_common.COMMON_PROPERTIES

    @METRICS.timer('DracManagement.validate')
    def validate(self, task):
        """Validate the driver-specific info supplied.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.

        """
        return drac_common.parse_driver_info(task.node)

    @METRICS.timer('DracManagement.get_supported_boot_devices')
    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a TaskManager instance containing the node to act on.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        return list(_BOOT_DEVICES_MAP)

    @METRICS.timer('DracManagement.get_boot_device')
    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Returns the current boot device of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: DracOperationError on an error from python-dracclient.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: whether the boot device will persist to all future
                boots or not, None if it is unknown.
        """
        node = task.node

        boot_device = node.driver_internal_info.get('drac_boot_device')
        if boot_device is not None:
            return boot_device

        return _get_boot_device(node)

    @METRICS.timer('DracManagement.set_boot_device')
    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a TaskManager instance containing the node to act on.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified.
        """
        node = task.node

        if device not in _BOOT_DEVICES_MAP:
            raise exception.InvalidParameterValue(
                _("set_boot_device called with invalid device '%(device)s' "
                  "for node %(node_id)s.") % {'device': device,
                                              'node_id': node.uuid})

        # NOTE(ifarkas): DRAC interface doesn't allow changing the boot device
        #                multiple times in a row without a reboot. This is
        #                because a change need to be committed via a
        #                configuration job, and further configuration jobs
        #                cannot be created until the previous one is processed
        #                at the next boot. As a workaround, saving it to
        #                driver_internal_info and committing the change during
        #                power state change.
        driver_internal_info = node.driver_internal_info
        driver_internal_info['drac_boot_device'] = {'boot_device': device,
                                                    'persistent': persistent}
        node.driver_internal_info = driver_internal_info
        node.save()

    @METRICS.timer('DracManagement.get_sensors_data')
    def get_sensors_data(self, task):
        """Get sensors data.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :returns: returns a consistent format dict of sensor data grouped by
                  sensor type, which can be processed by Ceilometer.
        """
        raise NotImplementedError()

    @METRICS.timer('DracManagement.reset_idrac')
    @base.clean_step(priority=0)
    def reset_idrac(self, task):
        """Reset the iDRAC.

        :param task: a TaskManager instance containing the node to act on.
        :returns: None if it is completed.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        client = drac_common.get_drac_client(node)
        client.reset_idrac(force=True, wait=True)

    @METRICS.timer('DracManagement.known_good_state')
    @base.clean_step(priority=0)
    def known_good_state(self, task):
        """Reset the iDRAC, Clear the job queue.

        :param task: a TaskManager instance containing the node to act on.
        :returns: None if it is completed.
        :raises: DracOperationError on an error from python-dracclient.
        """
        node = task.node

        client = drac_common.get_drac_client(node)
        client.reset_idrac(force=True, wait=True)
        client.delete_jobs(job_ids=[_CLEAR_JOB_IDS])

    @METRICS.timer('DracManagement.clear_job_queue')
    @base.clean_step(priority=0)
    def clear_job_queue(self, task):
        """Clear the job queue.

        :param task: a TaskManager instance containing the node to act on.
        :returns: None if it is completed.
        :raises: DracOperationError on an error from python-dracclient.
        """
        try:
            node = task.node

            client = drac_common.get_drac_client(node)
            client.delete_jobs(job_ids=[_CLEAR_JOB_IDS])
        except drac_exceptions.BaseClientException as exc:
            LOG.error('DRAC driver failed to clear the job queue for node '
                      '%(node_uuid)s. Reason: %(error)s.',
                      {'node_uuid': node.uuid, 'error': exc})
            raise exception.DracOperationError(error=exc)


class DracManagement(DracWSManManagement):
    """Class alias of class DracWSManManagement.

    This class provides ongoing support of the deprecated 'idrac'
    management interface implementation entrypoint.

    All bug fixes and new features should be implemented in its base
    class, DracWSManManagement. That makes them available to both the
    deprecated 'idrac' and new 'idrac-wsman' entrypoints. Such changes
    should not be made to this class.
    """

    def __init__(self):
        super(DracManagement, self).__init__()
        LOG.warning("Management interface 'idrac' is deprecated and may be "
                    "removed in a future release. Use 'idrac-wsman' instead.")
