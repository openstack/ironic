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

from urllib.parse import urlparse

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import importutils
from oslo_utils import timeutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import firmware_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

sushy = importutils.try_import('sushy')


class RedfishFirmware(base.FirmwareInterface):

    _FW_SETTINGS_ARGSINFO = {
        'settings': {
            'description': (
                'A list of dicts with firmware components to be updated'
            ),
            'required': True
        }
    }

    def __init__(self):
        super(RedfishFirmware, self).__init__()
        if sushy is None:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_("Unable to import the sushy library"))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the redfish driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        redfish_utils.parse_driver_info(task.node)

    @METRICS.timer('RedfishFirmware.cache_firmware_components')
    def cache_firmware_components(self, task):
        """Store or update Firmware Components on the given node.

        This method stores Firmware Components to the firmware_information
        table during 'cleaning' operation. It will also update the timestamp
        of each Firmware Component.

        :param task: a TaskManager instance.
        :raises: UnsupportedDriverExtension, if the node's driver doesn't
            support getting Firmware Components from bare metal.
        """

        node_id = task.node.id
        settings = []
        # NOTE(iurygregory): currently we will only retrieve BIOS and BMC
        # firmware information trough the redfish system and manager.

        system = redfish_utils.get_system(task.node)

        if system.bios_version:
            bios_fw = {'component': 'bios',
                       'current_version': system.bios_version}
            settings.append(bios_fw)

        # NOTE(iurygregory): normally we only relay on the System to
        # perform actions, but to retrieve the BMC Firmware we need to
        # access the Manager.
        try:
            manager = redfish_utils.get_manager(task.node, system)
            if manager.firmware_version:
                bmc_fw = {'component': 'bmc',
                          'current_version': manager.firmware_version}
                settings.append(bmc_fw)
        except exception.RedfishError:
            LOG.warning('No manager available to retrieve Firmware '
                        'from the bmc of node %s', task.node.uuid)

        if not settings:
            error_msg = (_('Cannot retrieve firmware for node %s: no '
                           'supported components') % task.node.uuid)
            LOG.error(error_msg)
            raise exception.UnsupportedDriverExtension(error_msg)

        create_list, update_list, nochange_list = (
            objects.FirmwareComponentList.sync_firmware_components(
                task.context, node_id, settings))

        if create_list:
            for new_fw in create_list:
                new_fw_cmp = objects.FirmwareComponent(
                    task.context,
                    node_id=node_id,
                    component=new_fw['component'],
                    current_version=new_fw['current_version']
                )
                new_fw_cmp.create()
        if update_list:
            for up_fw in update_list:
                up_fw_cmp = objects.FirmwareComponent.get(
                    task.context,
                    node_id=node_id,
                    name=up_fw['component']
                )
                up_fw_cmp.last_version_flashed = up_fw.get('current_version')
                up_fw_cmp.current_version = up_fw.get('current_version')
                up_fw_cmp.save()

    @METRICS.timer('RedfishFirmware.update')
    @base.deploy_step(priority=0, argsinfo=_FW_SETTINGS_ARGSINFO)
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_FW_SETTINGS_ARGSINFO,
                     requires_ramdisk=True)
    @base.cache_firmware_components
    def update(self, task, settings):
        """Update the Firmware on the node using the settings for components.

        :param task: a TaskManager instance.
        :param settings: a list of dictionaries, each dictionary contains the
            component name and the url that will be used to update the
            firmware.
        :raises: UnsupportedDriverExtension, if the node's driver doesn't
            support update via the interface.
        :raises: InvalidParameterValue, if validation of the settings fails.
        :raises: MissingParamterValue, if some required parameters are
            missing.
        :returns: states.CLEANWAIT if Firmware update with the settings is in
            progress asynchronously of None if it is complete.
        """
        node = task.node

        update_service = redfish_utils.get_update_service(node)

        LOG.debug('Updating Firmware on node %(node_uuid)s with settings '
                  '%(settings)s',
                  {'node_uuid': node.uuid, 'settings': settings})

        self._execute_firmware_update(node, update_service, settings)

        fw_upd = settings[0]
        wait_interval = fw_upd.get('wait')

        deploy_utils.set_async_step_flags(
            node,
            reboot=True,
            skip_current_step=True,
            polling=True
        )

        return deploy_utils.reboot_to_finish_step(task, timeout=wait_interval)

    def _execute_firmware_update(self, node, update_service, settings):
        """Executes the next firmware update to the node

        Executes the first firmware update in the settings list to the node.

        :param node: the node that will have a firmware update executed.
        :param update_service: the sushy firmware update service.
        :param settings: remaining settings for firmware update that needs
            to be executed.
        """
        fw_upd = settings[0]
        component_url, cleanup = self._stage_firmware_file(node, fw_upd)

        LOG.debug('Applying new firmware %(url)s for %(component)s on node '
                  '%(node_uuid)s',
                  {'url': fw_upd['url'], 'component': fw_upd['component'],
                   'node_uuid': node.uuid})

        task_monitor = update_service.simple_update(component_url)

        fw_upd['task_monitor'] = task_monitor.task_monitor_uri
        node.set_driver_internal_info('redfish_fw_updates', settings)

        if cleanup:
            fw_clean = node.driver_internal_info.get('firmware_cleanup')
            if not fw_clean:
                fw_clean = [cleanup]
            elif cleanup not in fw_clean:
                fw_clean.append(cleanup)
            node.set_driver_internal_info('firmware_cleanup', fw_clean)

    def _continue_updates(self, task, update_service, settings):
        """Continues processing the firmware updates

        Continues to process the firmware updates on the node.

        Note that the caller must have an exclusive lock on the node.

        :param task: a TaskManager instance containing the node to act on.
        :param update_service: the sushy firmware update service
        :param settings: the remaining firmware updates to apply
        """
        node = task.node
        fw_upd = settings[0]
        wait_interval = fw_upd.get('wait')
        if wait_interval:
            time_now = str(timeutils.utcnow().isoformat())
            fw_upd['wait_start_time'] = time_now

            LOG.debug('Waiting at %(time)s for %(seconds)s seconds after '
                      '%(component)s firmware update %(url)s '
                      'on node %(node)s',
                      {'time': time_now,
                       'seconds': wait_interval,
                       'component': fw_upd['component'],
                       'url': fw_upd['url'],
                       'node': node.uuid})

            node.set_driver_internal_info('redfish_fw_updates', settings)
            node.save()
            return

        if len(settings) == 1:
            self._clear_updates(node)

            LOG.info('Firmware updates completed for node %(node)s',
                     {'node': node.uuid})

            manager_utils.notify_conductor_resume_clean(task)
        else:
            settings.pop(0)
            self._execute_firmware_update(node,
                                          update_service,
                                          settings)
            node.save()
            manager_utils.node_power_action(task, states.REBOOT)

    def _clear_updates(self, node):
        """Clears firmware updates artifacts

        Clears firmware updates from driver_internal_info and any files
        that were staged.

        Note that the caller must have an exclusive lock on the node.

        :param node: the node to clear the firmware updates from
        """
        firmware_utils.cleanup(node)
        node.del_driver_internal_info('redfish_fw_updates')
        node.del_driver_internal_info('firmware_cleanup')
        node.save()

    @METRICS.timer('RedfishFirmware._query_update_failed')
    @periodics.node_periodic(
        purpose='checking if async update of firmware component failed',
        spacing=CONF.redfish.firmware_update_fail_interval,
        filters={'reserved': False, 'provision_state': states.CLEANFAIL,
                 'maintenance': True},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('redfish_fw_updates'),
    )
    def _query_update_failed(self, task, manager, context):

        """Periodic job to check for failed firmware updates."""
        # A firmware update failed. Discard any remaining firmware
        # updates so when the user takes the node out of
        # maintenance mode, pending firmware updates do not
        # automatically continue.
        LOG.error('Update firmware failed for node %(node)s. '
                  'Discarding remaining firmware updates.',
                  {'node': task.node.uuid})

        task.upgrade_lock()
        self._clear_updates(task.node)

    @METRICS.timer('RedfishFirmware._query_update_status')
    @periodics.node_periodic(
        purpose='checking async update of firmware component',
        spacing=CONF.redfish.firmware_update_fail_interval,
        filters={'reserved': False, 'provision_state': states.CLEANWAIT},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('redfish_fw_updates'),
    )
    def _query_update_status(self, task, manager, context):
        """Periodic job to check firmware update tasks."""
        self._check_node_redfish_firmware_update(task)

    @METRICS.timer('RedfishFirmware._check_node_redfish_firmware_update')
    def _check_node_redfish_firmware_update(self, task):
        """Check the progress of running firmware update on a node."""

        node = task.node

        settings = node.driver_internal_info['redfish_fw_updates']
        current_update = settings[0]

        try:
            update_service = redfish_utils.get_update_service(node)
        except exception.RedfishConnectionError as e:
            # If the BMC firmware is being updated, the BMC will be
            # unavailable for some amount of time.
            LOG.warning('Unable to communicate with firmware update service '
                        'on node %(node)s. Will try again on the next poll. '
                        'Error: %(error)s',
                        {'node': node.uuid,
                         'error': e})
            return

        wait_start_time = current_update.get('wait_start_time')
        if wait_start_time:
            wait_start = timeutils.parse_isotime(wait_start_time)

            elapsed_time = timeutils.utcnow(True) - wait_start
            if elapsed_time.seconds >= current_update['wait']:
                LOG.debug('Finished waiting after firmware update '
                          '%(firmware_image)s on node %(node)s. '
                          'Elapsed time: %(seconds)s seconds',
                          {'firmware_image': current_update['url'],
                           'node': node.uuid,
                           'seconds': elapsed_time.seconds})
                current_update.pop('wait', None)
                current_update.pop('wait_start_time', None)

                self._continue_updates(task, update_service, settings)
            else:
                LOG.debug('Continuing to wait after firmware update '
                          '%(firmware_image)s on node %(node)s. '
                          'Elapsed time: %(seconds)s seconds',
                          {'firmware_image': current_update['url'],
                           'node': node.uuid,
                           'seconds': elapsed_time.seconds})

            return

        try:
            task_monitor = redfish_utils.get_task_monitor(
                node, current_update['task_monitor'])
        except exception.RedfishError:
            # The BMC deleted the Task before we could query it
            LOG.warning('Firmware update completed for node %(node)s, '
                        'firmware %(firmware_image)s, but success of the '
                        'update is unknown.  Assuming update was successful.',
                        {'node': node.uuid,
                         'firmware_image': current_update['url']})
            self._continue_updates(task, update_service, settings)
            return

        if not task_monitor.is_processing:
            # The last response does not necessarily contain a Task,
            # so get it
            sushy_task = task_monitor.get_task()

            # Only parse the messages if the BMC did not return parsed
            # messages
            messages = []
            if sushy_task.messages and not sushy_task.messages[0].message:
                sushy_task.parse_messages()

            if sushy_task.messages is not None:
                messages = [m.message for m in sushy_task.messages]

            task.upgrade_lock()
            if (sushy_task.task_state == sushy.TASK_STATE_COMPLETED
                    and sushy_task.task_status in
                    [sushy.HEALTH_OK, sushy.HEALTH_WARNING]):
                LOG.info('Firmware update succeeded for node %(node)s, '
                         'firmware %(firmware_image)s: %(messages)s',
                         {'node': node.uuid,
                          'firmware_image': current_update['url'],
                          'messages': ", ".join(messages)})

                self._continue_updates(task, update_service, settings)
            else:
                error_msg = (_('Firmware update failed for node %(node)s, '
                               'firmware %(firmware_image)s. '
                               'Error: %(errors)s') %
                             {'node': node.uuid,
                              'firmware_image': current_update['url'],
                              'errors': ",  ".join(messages)})

                self._clear_updates(node)
                if task.node.clean_step:
                    manager_utils.cleaning_error_handler(task, error_msg)
                else:
                    manager_utils.deploying_error_handler(task, error_msg)

        else:
            LOG.debug('Firmware update in progress for node %(node)s, '
                      'firmware %(firmware_image)s.',
                      {'node': node.uuid,
                       'firmware_image': current_update['url']})

    def _stage_firmware_file(self, node, component_update):

        try:
            url = component_update['url']
            name = component_update['component']
            parsed_url = urlparse(url)
            scheme = parsed_url.scheme.lower()
            source = (CONF.redfish.firmware_source).lower()

            # Keep it simple, in further processing TLS does not matter
            if scheme == 'https':
                scheme = 'http'

            # If source and scheme is HTTP, then no staging,
            # returning original location
            if scheme == 'http' and source == scheme:
                LOG.debug('For node %(node)s serving firmware for '
                          '%(component)s from original location %(url)s',
                          {'node': node.uuid, 'component': name, 'url': url})
                return url, None

            # If source and scheme is Swift, then not moving, but
            # returning Swift temp URL
            if scheme == 'swift' and source == scheme:
                temp_url = firmware_utils.get_swift_temp_url(parsed_url)
                LOG.debug('For node %(node)s serving original firmware at '
                          'for %(component)s at %(url)s via Swift temporary '
                          'url %(temp_url)s',
                          {'node': node.uuid, 'component': name, 'url': url,
                           'temp_url': temp_url})
                return temp_url, None

            # For remaining, download the image to temporary location
            temp_file = firmware_utils.download_to_temp(node, url)

            return firmware_utils.stage(node, source, temp_file)

        except exception.IronicException:
            firmware_utils.cleanup(node)
