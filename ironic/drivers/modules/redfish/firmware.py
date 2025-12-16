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

import time
from urllib.parse import urlparse

from oslo_log import log
from oslo_utils import timeutils
import sushy

from ironic.common import async_steps
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import metrics_utils
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


class RedfishFirmware(base.FirmwareInterface):

    _FW_SETTINGS_ARGSINFO = {
        'settings': {
            'description': (
                'A list of dicts with firmware components to be updated'
            ),
            'required': True
        }
    }

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
        # firmware information through the redfish system and manager.

        system = redfish_utils.get_system(task.node)

        if system.bios_version:
            bios_fw = {'component': redfish_utils.BIOS,
                       'current_version': system.bios_version}
            settings.append(bios_fw)
        else:
            LOG.debug('Could not retrieve BiosVersion in node %(node_uuid)s '
                      'system %(system)s', {'node_uuid': task.node.uuid,
                                            'system': system.identity})

        # NOTE(iurygregory): normally we only relay on the System to
        # perform actions, but to retrieve the BMC Firmware we need to
        # access the Manager.
        try:
            manager = redfish_utils.get_manager(task.node, system)
            if manager.firmware_version:
                bmc_fw = {'component': redfish_utils.BMC,
                          'current_version': manager.firmware_version}
                settings.append(bmc_fw)
            else:
                LOG.debug('Could not retrieve FirmwareVersion in node '
                          '%(node_uuid)s manager %(manager)s',
                          {'node_uuid': task.node.uuid,
                           'manager': manager.identity})
        except exception.RedfishError:
            LOG.warning('No manager available to retrieve Firmware '
                        'from the bmc of node %s', task.node.uuid)

        nic_components = None
        try:
            nic_components = self.retrieve_nic_components(task, system)
        except (exception.RedfishError,
                sushy.exceptions.BadRequestError) as e:
            # NOTE(janders) if an exception is raised, log a warning
            # with exception details. This is important for HP hardware
            # which at the time of writing this are known to return 400
            # responses to GET NetworkAdapters while OS isn't fully booted
            LOG.warning('Unable to access NetworkAdapters on node '
                        '%(node_uuid)s, Error: %(error)s',
                        {'node_uuid': task.node.uuid, 'error': e})
        # NOTE(janders) if no exception is raised but no NICs are returned,
        # state that clearly but in a lower severity message
        if nic_components == []:
            LOG.debug('Could not retrieve Firmware Package Version from '
                      'NetworkAdapters on node %(node_uuid)s',
                      {'node_uuid': task.node.uuid})
        elif nic_components:
            settings.extend(nic_components)

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

    def retrieve_nic_components(self, task, system):
        """Helper function to retrieve all NICs components on a given node.

        :param task: a TaskManager instance.
        :param system: a Redfish System object
        :returns: a list of NIC components
        """
        nic_list = []
        try:
            chassis = redfish_utils.get_chassis(task.node, system)
        except exception.RedfishError:
            LOG.debug('No chassis available to retrieve NetworkAdapters '
                      'firmware information on node %(node_uuid)s',
                      {'node_uuid': task.node.uuid})
            return nic_list

        try:
            network_adapters = chassis.network_adapters
            if network_adapters is None:
                LOG.debug('NetworkAdapters not available on chassis for '
                          'node %(node_uuid)s',
                          {'node_uuid': task.node.uuid})
                return nic_list
            adapters = network_adapters.get_members()
        except sushy.exceptions.MissingAttributeError:
            LOG.debug('NetworkAdapters not available on chassis for '
                      'node %(node_uuid)s',
                      {'node_uuid': task.node.uuid})
            return nic_list

        for net_adp in adapters:
            for net_adp_ctrl in net_adp.controllers:
                fw_pkg_v = net_adp_ctrl.firmware_package_version
                if not fw_pkg_v:
                    continue
                net_adp_fw = {'component': redfish_utils.NIC_COMPONENT_PREFIX
                              + net_adp.identity, 'current_version': fw_pkg_v}
                nic_list.append(net_adp_fw)

        return nic_list

    @METRICS.timer('RedfishFirmware.update')
    @base.deploy_step(priority=0, argsinfo=_FW_SETTINGS_ARGSINFO)
    @base.clean_step(priority=0, abortable=False,
                     argsinfo=_FW_SETTINGS_ARGSINFO,
                     requires_ramdisk=True)
    @base.service_step(priority=0, abortable=False,
                       argsinfo=_FW_SETTINGS_ARGSINFO,
                       requires_ramdisk=False)
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
        firmware_utils.validate_firmware_interface_update_args(settings)
        node = task.node
        update_service = redfish_utils.get_update_service(node)

        LOG.debug('Updating Firmware on node %(node_uuid)s with settings '
                  '%(settings)s',
                  {'node_uuid': node.uuid, 'settings': settings})
        self._execute_firmware_update(node, update_service, settings)

        # Store updated settings and start time for overall timeout tracking
        node.set_driver_internal_info('redfish_fw_updates', settings)
        node.set_driver_internal_info(
            'redfish_fw_update_start_time',
            timeutils.utcnow().isoformat())
        node.save()

        # Return wait state to keep the step active and let polling handle
        # the monitoring and eventual completion/reboot
        return async_steps.get_return_state(node)

    def _setup_bmc_update_monitoring(self, node, fw_upd):
        """Set up monitoring for BMC firmware update.

        BMC updates do not reboot immediately. Instead, we check the BMC
        version periodically. If the version changed, we continue without
        reboot. If timeout expires without version change, we trigger a reboot.

        :param node: the Ironic node object
        :param fw_upd: firmware update settings dict
        """
        # Record current BMC version before update
        try:
            system = redfish_utils.get_system(node)
            manager = redfish_utils.get_manager(node, system)
            current_bmc_version = manager.firmware_version
            node.set_driver_internal_info(
                'bmc_fw_version_before_update', current_bmc_version)
            LOG.debug('BMC version before update for node %(node)s: '
                      '%(version)s',
                      {'node': node.uuid, 'version': current_bmc_version})
        except Exception as e:
            LOG.warning('Could not read BMC version before update for '
                        'node %(node)s: %(error)s',
                        {'node': node.uuid, 'error': e})

        node.set_driver_internal_info(
            'bmc_fw_check_start_time',
            str(timeutils.utcnow().isoformat()))

        LOG.info('BMC firmware update for node %(node)s. '
                 'Monitoring BMC version instead of immediate reboot.',
                 {'node': node.uuid})

        # Use wait_interval or default reboot delay
        wait_interval = fw_upd.get('wait')
        if wait_interval is None:
            wait_interval = CONF.redfish.firmware_update_reboot_delay
        fw_upd['wait'] = wait_interval
        # Set wait_start_time so polling can detect when task monitor
        # becomes unresponsive and transition to version checking
        fw_upd['wait_start_time'] = str(timeutils.utcnow().isoformat())
        # Mark this as a BMC update so we can handle timeouts properly
        fw_upd['component_type'] = redfish_utils.BMC

        # BMC: Set async flags without immediate reboot
        deploy_utils.set_async_step_flags(
            node,
            reboot=False,
            polling=True
        )

    def _setup_nic_update_monitoring(self, node):
        """Set up monitoring for NIC firmware update.

        NIC firmware behavior varies by hardware. Some NICs update immediately,
        some need reboot to start. The handler will wait 30s and decide whether
        to reboot.

        :param node: the Ironic node object
        """
        LOG.info('NIC firmware update for node %(node)s. Will monitor '
                 'task state to determine if reboot is needed.',
                 {'node': node.uuid})

        # NIC: Set async flags with reboot enabled
        # (reboot will be triggered conditionally if hardware needs it)
        deploy_utils.set_async_step_flags(
            node,
            reboot=True,
            polling=True
        )

    def _setup_bios_update_monitoring(self, node):
        """Set up monitoring for BIOS firmware update.

        BIOS updates require a reboot to apply, so we trigger it as soon
        as the update task begins rather than waiting for completion.

        :param node: the Ironic node object
        """
        LOG.info('BIOS firmware update for node %(node)s. Will reboot '
                 'when update task starts.',
                 {'node': node.uuid})

        # BIOS: Set async flags with reboot enabled
        deploy_utils.set_async_step_flags(
            node,
            reboot=True,
            polling=True
        )

    def _setup_default_update_monitoring(self, node, fw_upd):
        """Set up monitoring for unknown/default firmware component types.

        Default behavior for unknown component types uses standard reboot
        handling with configurable wait interval.

        :param node: the Ironic node object
        :param fw_upd: firmware update settings dict
        """
        component = fw_upd.get('component', '')
        LOG.warning(
            'Unknown component type %(component)s for node %(node)s. '
            'Using default firmware update behavior.',
            {'component': component, 'node': node.uuid})

        wait_interval = fw_upd.get('wait')
        if wait_interval is None:
            wait_interval = (
                node.driver_info.get('firmware_update_unresponsive_bmc_wait')
                or CONF.redfish.firmware_update_wait_unresponsive_bmc)
            fw_upd['wait'] = wait_interval

        # Default: Set async flags with reboot enabled
        deploy_utils.set_async_step_flags(
            node,
            reboot=True,
            polling=True
        )


    def _get_current_bmc_version(self, node):
        """Get current BMC firmware version.

        Note: BMC may be temporarily unresponsive after firmware update.
        Expected exceptions (timeouts, connection refused, HTTP errors) are
        caught and logged, returning None to indicate version unavailable.

        :param node: the Ironic node object
        :returns: Current BMC firmware version string, or None if BMC
                  is unresponsive/inaccessible
        """
        try:
            system = redfish_utils.get_system(node)
            manager = redfish_utils.get_manager(node, system)
            return manager.firmware_version
        except (exception.RedfishError,
                exception.RedfishConnectionError,
                sushy.exceptions.SushyError) as e:
            # BMC unresponsiveness is expected after firmware update
            # (timeouts, connection refused, HTTP 4xx/5xx errors)
            LOG.debug('BMC temporarily unresponsive for node %(node)s: '
                      '%(error)s', {'node': node.uuid, 'error': e})
            return None

    def _handle_bmc_update_completion(self, task, update_service,
                                      settings, current_update):
        """Handle BMC firmware update completion with version checking.

        For BMC updates, we don't reboot immediately. Instead, we check
        the BMC version periodically. If the version changed, we continue
        without reboot. If timeout expires without version change, we trigger
        a reboot.

        :param task: a TaskManager instance
        :param update_service: the sushy firmware update service
        :param settings: firmware update settings
        :param current_update: the current firmware update being processed
        """
        node = task.node

        # Try to get current BMC version
        # Note: BMC may be unresponsive after firmware update - expected
        current_version = self._get_current_bmc_version(node)
        version_before = node.driver_internal_info.get(
            'bmc_fw_version_before_update')

        # If we can read the version and it changed, update is complete
        if (current_version is not None
                and version_before is not None
                and current_version != version_before):
            LOG.info(
                'BMC firmware version for node %(node)s changed from '
                '%(old)s to %(new)s. Update complete. Continuing without '
                'reboot.',
                {'node': node.uuid, 'old': version_before,
                 'new': current_version})
            node.del_driver_internal_info('bmc_fw_check_start_time')
            node.del_driver_internal_info('bmc_fw_version_before_update')
            node.save()
            self._continue_updates(task, update_service, settings)
            return

        # Check if we've been checking for too long
        check_start_time = node.driver_internal_info.get(
            'bmc_fw_check_start_time')

        if check_start_time:
            check_start = timeutils.parse_isotime(check_start_time)
            elapsed_time = timeutils.utcnow(True) - check_start
            timeout = current_update.get(
                'wait', CONF.redfish.firmware_update_reboot_delay)
            if elapsed_time.seconds >= timeout:
                # Timeout: version didn't change or BMC unresponsive
                if (current_version is not None
                        and version_before is not None
                        and current_version == version_before):
                    # Version didn't change - skip reboot
                    LOG.info(
                        'BMC firmware version for node %(node)s did not '
                        'change (still %(version)s). Update appears to be '
                        'a no-op or does not require reboot. Continuing '
                        'without reboot.',
                        {'node': node.uuid, 'version': current_version})
                else:
                    # Version changed or we can't tell - reboot to apply
                    LOG.warning(
                        'BMC firmware version check timeout expired for '
                        'node %(node)s after %(elapsed)s seconds. '
                        'Will reboot to complete firmware update.',
                        {'node': node.uuid, 'elapsed': elapsed_time.seconds})
                    # Mark that reboot is needed
                    node.set_driver_internal_info(
                        'firmware_reboot_requested', True)
                    # Enable reboot flag now that we're ready to reboot
                    deploy_utils.set_async_step_flags(
                        node,
                        reboot=True,
                        polling=True
                    )

                node.del_driver_internal_info('bmc_fw_check_start_time')
                node.del_driver_internal_info('bmc_fw_version_before_update')
                node.save()
                self._continue_updates(task, update_service, settings)
                return

        # Continue checking - set wait to check again
        wait_interval = (
            CONF.redfish.firmware_update_bmc_version_check_interval)
        current_update['wait'] = wait_interval
        current_update['wait_start_time'] = str(
            timeutils.utcnow().isoformat())
        current_update['bmc_version_checking'] = True
        node.set_driver_internal_info('redfish_fw_updates', settings)
        node.save()

        LOG.debug('BMC firmware version check continuing for node %(node)s. '
                  'Will check again in %(interval)s seconds.',
                  {'node': node.uuid, 'interval': wait_interval})

    def _handle_nic_update_completion(self, task, update_service, settings,
                                      current_update):
        """Handle NIC firmware update completion.

        For NIC updates, check if a reboot is needed based on whether the
        task went through the Running state (needs reboot after completion)
        or if reboot already occurred during the Starting phase.

        :param task: a TaskManager instance
        :param update_service: the sushy firmware update service
        :param settings: firmware update settings
        :param current_update: the current firmware update being processed
        """
        node = task.node

        # Check if reboot is needed (task went to Running state)
        needs_reboot = current_update.get(
            'nic_needs_post_completion_reboot', False)

        if needs_reboot:
            LOG.info(
                'NIC firmware update task completed for node '
                '%(node)s. Reboot required to apply update.',
                {'node': node.uuid})

            # Mark that reboot is needed
            node.set_driver_internal_info(
                'firmware_reboot_requested', True)

            # Clean up flags
            current_update.pop('nic_needs_post_completion_reboot', None)
            current_update.pop('nic_starting_timestamp', None)
            current_update.pop('nic_reboot_triggered', None)
        else:
            LOG.info(
                'NIC firmware update task completed for node '
                '%(node)s. Reboot already occurred during update '
                'start.', {'node': node.uuid})
            # Clean up all NIC-related flags
            current_update.pop('nic_starting_timestamp', None)
            current_update.pop('nic_reboot_triggered', None)

        self._continue_updates(task, update_service, settings)

    def _execute_firmware_update(self, node, update_service, settings):
        """Executes the next firmware update to the node

        Executes the first firmware update in the settings list to the node.

        :param node: the node that will have a firmware update executed.
        :param update_service: the sushy firmware update service.
        :param settings: remaining settings for firmware update that needs
            to be executed.
        """
        fw_upd = settings[0]
        # Store power timeout to use on reboot operations
        fw_upd['power_timeout'] = CONF.redfish.firmware_update_reboot_delay
        # NOTE(janders) try to get the collection of Systems on the BMC
        # to determine if there may be more than one System
        try:
            systems_collection = redfish_utils.get_system_collection(node)
        except exception.RedfishError as e:
            LOG.error('Failed getting Redfish Systems Collection'
                      ' for node %(node)s. Error %(error)s',
                      {'node': node.uuid, 'error': e})
            raise exception.RedfishError(error=e)
        count = len(systems_collection.members_identities)
        # NOTE(janders) if we see more than one System on the BMC, assume that
        # we need to explicitly specify Target parameter when calling
        # SimpleUpdate. This is needed for compatibility with sushy-tools
        # in automated testing using VMs.
        if count > 1:
            target = node.driver_info.get('redfish_system_id')
            targets = [target]
        else:
            targets = None

        component_url, cleanup = self._stage_firmware_file(node, fw_upd)

        LOG.debug('Applying new firmware %(url)s for %(component)s on node '
                  '%(node_uuid)s',
                  {'url': fw_upd['url'], 'component': fw_upd['component'],
                   'node_uuid': node.uuid})
        try:
            if targets is not None:
                task_monitor = update_service.simple_update(component_url,
                                                            targets=targets)
            else:
                task_monitor = update_service.simple_update(component_url)
        except sushy.exceptions.MissingAttributeError as e:
            LOG.error('The attribute #UpdateService.SimpleUpdate is missing '
                      'on node %(node)s. Error: %(error)s',
                      {'node': node.uuid, 'error': e.message})
            raise exception.RedfishError(error=e)

        # Store task monitor URI for periodic task polling
        # NOTE(janders): Component-specific wait/reboot behavior is now
        # handled by the update() method and periodic polling, not here

        fw_upd['task_monitor'] = task_monitor.task_monitor_uri
        node.set_driver_internal_info('redfish_fw_updates', settings)

        if cleanup:
            fw_clean = node.driver_internal_info.get('firmware_cleanup')
            if not fw_clean:
                fw_clean = [cleanup]
            elif cleanup not in fw_clean:
                fw_clean.append(cleanup)
            node.set_driver_internal_info('firmware_cleanup', fw_clean)

        component = fw_upd.get('component', '')
        component_type = redfish_utils.get_component_type(component)

        if component_type == redfish_utils.BMC:
            self._setup_bmc_update_monitoring(node, fw_upd)
        elif component_type == redfish_utils.NIC:
            self._setup_nic_update_monitoring(node)
        elif component_type == redfish_utils.BIOS:
            self._setup_bios_update_monitoring(node)
        else:
            self._setup_default_update_monitoring(node, fw_upd)


    def _validate_resources_stability(self, node):
        """Validate that BMC resources are consistently available.

        Requires consecutive successful responses from System, Manager,
        and NetworkAdapters resources before considering them stable.
        The number of required successes is configured via
        CONF.redfish.firmware_update_required_successes.
        Timeout is configured via
        CONF.redfish.firmware_update_resource_validation_timeout.

        :param node: the Ironic node object
        :raises: RedfishError if resources don't stabilize within timeout
        """
        timeout = CONF.redfish.firmware_update_resource_validation_timeout
        required_successes = CONF.redfish.firmware_update_required_successes
        validation_interval = CONF.redfish.firmware_update_validation_interval

        # Skip validation if validation is disabled via configuration
        if required_successes == 0 or timeout == 0:
            reasons = []
            if required_successes == 0:
                reasons.append('required_successes=0')
            if timeout == 0:
                reasons.append('validation_timeout=0')

            LOG.info('BMC resource validation disabled (%s) for node %(node)s',
                     ', '.join(reasons), {'node': node.uuid})
            return

        LOG.debug('Starting resource stability validation for node %(node)s '
                  '(timeout: %(timeout)s seconds, '
                  'required_successes: %(required)s, '
                  'validation_interval: %(interval)s seconds)',
                  {'node': node.uuid, 'timeout': timeout,
                   'required': required_successes,
                   'interval': validation_interval})

        start_time = time.time()
        end_time = start_time + timeout
        consecutive_successes = 0
        last_exc = None

        while time.time() < end_time:
            try:
                # Test System resource
                system = redfish_utils.get_system(node)

                # Test Manager resource
                redfish_utils.get_manager(node, system)

                # Test Chassis and NetworkAdapters resource (if available)
                # Some systems may not have NetworkAdapters, which is valid
                chassis = redfish_utils.get_chassis(node, system)
                try:
                    network_adapters = chassis.network_adapters
                    if network_adapters is not None:
                        network_adapters.get_members()
                except sushy.exceptions.MissingAttributeError:
                    # NetworkAdapters not available is acceptable
                    pass

                # All resources successful
                consecutive_successes += 1
                LOG.debug('Resource validation success %(count)d/%(required)d '
                          'for node %(node)s',
                          {'count': consecutive_successes,
                           'required': required_successes,
                           'node': node.uuid})

                if consecutive_successes >= required_successes:
                    LOG.info('All tested Redfish resources stable and '
                             ' available for node %(node)s',
                             {'node': node.uuid})
                    return

            except (exception.RedfishError,
                    exception.RedfishConnectionError,
                    sushy.exceptions.SushyError) as e:
                LOG.debug('BMC resource validation failed for node %(node)s: '
                          '%(error)s. This may indicate the BMC is still '
                          'restarting or recovering from firmware update.',
                          {'node': node.uuid, 'error': e})
                # Resource not available yet, reset counter
                if consecutive_successes > 0:
                    LOG.debug('Resource validation interrupted for node '
                              '%(node)s, resetting success counter '
                              '(error: %(error)s)',
                              {'node': node.uuid, 'error': e})
                consecutive_successes = 0
                last_exc = e

            # Wait before next validation attempt
            time.sleep(validation_interval)
        # Timeout reached without achieving stability
        error_msg = _('BMC resources failed to stabilize within '
                      '%(timeout)s seconds for node %(node)s') % {
            'timeout': timeout, 'node': node.uuid}
        if last_exc:
            error_msg += _(', last error: %(error)s') % {'error': last_exc}
        LOG.error(error_msg)
        raise exception.RedfishError(error=error_msg)

    def _continue_updates(self, task, update_service, settings):
        """Continues processing the firmware updates

        Continues to process the firmware updates on the node.
        First monitors the current task completion, then validates resource
        stability before proceeding to next update or completion.

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
            # Last firmware update - check if reboot is needed
            reboot_requested = node.driver_internal_info.get(
                'firmware_reboot_requested', False)

            self._clear_updates(node)

            LOG.info('Firmware updates completed for node %(node)s',
                     {'node': node.uuid})

            # If reboot was requested (e.g., for BMC timeout or NIC
            # completion), trigger the reboot before notifying conductor
            if reboot_requested:
                LOG.info('Rebooting node %(node)s to apply firmware updates',
                         {'node': node.uuid})
                manager_utils.node_power_action(task, states.REBOOT)

            LOG.debug('Validating BMC responsiveness before resuming '
                      'conductor operations for node %(node)s',
                      {'node': node.uuid})
            self._validate_resources_stability(node)

            if task.node.clean_step:
                manager_utils.notify_conductor_resume_clean(task)
            elif task.node.service_step:
                manager_utils.notify_conductor_resume_service(task)
            elif task.node.deploy_step:
                manager_utils.notify_conductor_resume_deploy(task)

        else:
            # Validate BMC resources are stable before continuing next update
            LOG.info('Validating BMC responsiveness before continuing '
                     'to next firmware update for node %(node)s',
                     {'node': node.uuid})
            self._validate_resources_stability(node)

            settings.pop(0)
            self._execute_firmware_update(node,
                                          update_service,
                                          settings)
            node.save()

            # Only reboot if the component code requested it.
            if task.node.clean_step:
                reboot_field = async_steps.CLEANING_REBOOT
            elif task.node.deploy_step:
                reboot_field = async_steps.DEPLOYMENT_REBOOT
            elif task.node.service_step:
                reboot_field = async_steps.SERVICING_REBOOT
            else:
                reboot_field = None

            # Default to reboot=True for backwards compatibility.
            should_reboot = (node.driver_internal_info.get(reboot_field, True)
                             if reboot_field else True)

            if should_reboot:
                power_timeout = settings[0].get('power_timeout', 0)
                manager_utils.node_power_action(task, states.REBOOT,
                                                power_timeout)
            else:
                LOG.debug('Component requested no immediate reboot for node '
                          '%(node)s. Continuing with async polling.',
                          {'node': node.uuid})

    def _clear_updates(self, node):
        """Clears firmware updates artifacts

        Clears firmware updates from driver_internal_info and any files
        that were staged.

        Note that the caller must have an exclusive lock on the node.

        :param node: the node to clear the firmware updates from
        """
        firmware_utils.cleanup(node)
        node.del_driver_internal_info('redfish_fw_updates')
        node.del_driver_internal_info('redfish_fw_update_start_time')
        node.del_driver_internal_info('firmware_cleanup')
        node.del_driver_internal_info('firmware_reboot_requested')
        node.save()

    @METRICS.timer('RedfishFirmware._query_update_failed')
    @periodics.node_periodic(
        purpose='checking if async update of firmware component failed',
        spacing=CONF.redfish.firmware_update_fail_interval,
        filters={'reserved': False, 'provision_state_in': [states.CLEANFAIL,
                 states.DEPLOYFAIL, states.SERVICEFAIL], 'maintenance': True},
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
        filters={'reserved': False, 'provision_state_in': [states.CLEANWAIT,
                 states.DEPLOYWAIT, states.SERVICEWAIT]},
        predicate_extra_fields=['driver_internal_info'],
        predicate=lambda n: n.driver_internal_info.get('redfish_fw_updates'),
    )
    def _query_update_status(self, task, manager, context):
        """Periodic job to check firmware update tasks."""
        self._check_node_redfish_firmware_update(task)

    def _handle_task_completion(self, task, sushy_task, messages,
                                update_service, settings, current_update):
        """Handle firmware update task completion.

        :param task: a TaskManager instance
        :param sushy_task: the sushy task object
        :param messages: list of task messages
        :param update_service: the sushy firmware update service
        :param settings: firmware update settings
        :param current_update: the current firmware update being processed
        """
        node = task.node

        if (sushy_task.task_state == sushy.TASK_STATE_COMPLETED
                and sushy_task.task_status in
                [sushy.HEALTH_OK, sushy.HEALTH_WARNING]):
            LOG.info('Firmware update task completed for node %(node)s, '
                     'firmware %(firmware_image)s: %(messages)s.',
                     {'node': node.uuid,
                      'firmware_image': current_update['url'],
                      'messages': ", ".join(messages)})

            # Component-specific post-update handling
            component = current_update.get('component', '')
            component_type = redfish_utils.get_component_type(component)

            if component_type == redfish_utils.BMC:
                # BMC: Start version checking instead of immediate reboot
                self._handle_bmc_update_completion(
                    task, update_service, settings, current_update)
            elif component_type == redfish_utils.NIC:
                # NIC: Handle completion with appropriate reboot behavior
                self._handle_nic_update_completion(
                    task, update_service, settings, current_update)
            elif component_type == redfish_utils.BIOS:
                # BIOS: Check if reboot was actually triggered
                # Some BMCs (e.g., HPE iLO) complete the BIOS firmware task
                # very quickly (staging the firmware) before Ironic can poll
                # and trigger the reboot. In this case, we need to trigger
                # the reboot now to actually apply the firmware.
                if not current_update.get('bios_reboot_triggered'):
                    LOG.info('BIOS firmware update task completed for node '
                             '%(node)s but reboot was not triggered yet. '
                             'Triggering reboot now to apply staged firmware.',
                             {'node': node.uuid})
                    current_update['bios_reboot_triggered'] = True
                    node.set_driver_internal_info('redfish_fw_updates',
                                                  settings)
                    node.save()
                    power_timeout = current_update.get('power_timeout', 0)
                    manager_utils.node_power_action(task, states.REBOOT,
                                                    power_timeout)
                    return
                else:
                    # Reboot was already triggered when task started,
                    # just continue with next update
                    LOG.info('BIOS firmware update task completed for node '
                             '%(node)s. System was already rebooted. '
                             'Proceeding with continuation.',
                             {'node': node.uuid})
                    # Clean up the reboot trigger flag
                    current_update.pop('bios_reboot_triggered', None)
                    self._continue_updates(task, update_service, settings)
            else:
                # Default: continue as before
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
            elif task.node.deploy_step:
                manager_utils.deploying_error_handler(task, error_msg)
            elif task.node.service_step:
                manager_utils.servicing_error_handler(task, error_msg)

    def _handle_nic_task_starting(self, task, task_monitor, settings,
                                  current_update):
        """Handle NIC firmware update task when it starts.

        NIC firmware behavior varies by hardware:
        - Some NICs need reboot to START applying (task stays at Starting)
        - Some NICs can start immediately but need reboot to APPLY (goes to
          Running, then needs reboot after completion)

        This method waits for the configured time
        (CONF.redfish.firmware_update_nic_starting_wait) to determine which
        type:
        - If still Starting after wait time → trigger reboot to start
        - If moves to Running → let it finish, reboot will happen after
          completion

        :param task: a TaskManager instance
        :param task_monitor: the sushy task monitor
        :param settings: firmware update settings
        :param current_update: the current firmware update being processed
        :returns: True if should stop polling, False to continue
        """
        node = task.node

        # Upgrade lock at the start since we may modify driver_internal_info
        task.upgrade_lock()

        try:
            sushy_task = task_monitor.get_task()
            task_state = sushy_task.task_state

            LOG.debug('NIC update task state for node %(node)s: %(state)s',
                      {'node': node.uuid, 'state': task_state})

            # If task is Running, mark that reboot will be needed after
            # completion and let it continue
            if task_state == sushy.TASK_STATE_RUNNING:
                LOG.debug('NIC update task for node %(node)s is running. '
                          'Will wait for completion then reboot.',
                          {'node': node.uuid})
                # Clear flags since we're past the starting phase
                current_update.pop('nic_starting_timestamp', None)
                current_update.pop('nic_reboot_triggered', None)
                # Mark that reboot will be needed after completion
                current_update['nic_needs_post_completion_reboot'] = True
                node.set_driver_internal_info('redfish_fw_updates', settings)
                node.save()
                return False  # Continue polling until completion

            # If task is in STARTING, check if we need to wait or reboot
            if task_state == sushy.TASK_STATE_STARTING:
                # Check if we already triggered a reboot
                if current_update.get('nic_reboot_triggered'):
                    LOG.debug('NIC firmware update for node %(node)s: '
                              'reboot already triggered, waiting for task '
                              'to progress.', {'node': node.uuid})
                    return False  # Continue polling

                starting_time = current_update.get('nic_starting_timestamp')

                if not starting_time:
                    # First time seeing STARTING - record timestamp
                    current_update['nic_starting_timestamp'] = str(
                        timeutils.utcnow().isoformat())
                    node.set_driver_internal_info(
                        'redfish_fw_updates', settings)
                    node.save()
                    LOG.debug('NIC firmware update task for node %(node)s '
                              'is in STARTING state. Waiting to determine if '
                              'reboot is needed to start update.',
                              {'node': node.uuid})
                    return False  # Keep polling

                # Check if configured wait time has elapsed
                start_time = timeutils.parse_isotime(starting_time)
                elapsed = timeutils.utcnow(True) - start_time
                nic_starting_wait = (
                    CONF.redfish.firmware_update_nic_starting_wait)

                if elapsed.seconds < nic_starting_wait:
                    # Still within wait window, keep waiting
                    LOG.debug('NIC update for node %(node)s still in '
                              'STARTING after %(elapsed)s seconds. '
                              'Waiting...',
                              {'node': node.uuid,
                               'elapsed': elapsed.seconds})
                    return False  # Keep polling

                # Wait time elapsed and still STARTING - need reboot to start
                LOG.info('NIC firmware update task for node %(node)s '
                         'remained in STARTING state for %(wait)s+ seconds. '
                         'Hardware requires reboot to start update. '
                         'Triggering reboot.',
                         {'node': node.uuid, 'wait': nic_starting_wait})

                # Mark that we triggered a reboot to prevent repeat reboots
                current_update['nic_reboot_triggered'] = True
                # Clean up timestamp
                current_update.pop('nic_starting_timestamp', None)
                node.set_driver_internal_info('redfish_fw_updates', settings)
                node.save()

                # Trigger the reboot to start update
                power_timeout = current_update.get('power_timeout', 0)
                manager_utils.node_power_action(task, states.REBOOT,
                                                power_timeout)

                LOG.info('Reboot initiated for node %(node)s to start '
                         'NIC firmware update', {'node': node.uuid})
                return True  # Stop polling, reboot triggered

        except Exception as e:
            LOG.warning('Unable to check NIC task state for node '
                        '%(node)s: %(error)s. Will retry.',
                        {'node': node.uuid, 'error': e})

        return False  # Continue polling on error

    def _handle_bios_task_starting(self, task, task_monitor, settings,
                                   current_update):
        """Handle BIOS firmware update task when it starts.

        BIOS updates require a reboot to apply the firmware, so we trigger
        the reboot as soon as the update task reaches STARTING state rather
        than waiting for task completion.

        :param task: a TaskManager instance
        :param task_monitor: the sushy task monitor
        :param settings: firmware update settings
        :param current_update: the current firmware update being processed
        :returns: True if reboot was triggered, False otherwise
        """
        node = task.node

        if current_update.get('bios_reboot_triggered'):
            # Already triggered, just keep polling
            return False

        # Upgrade lock at the start since we may modify driver_internal_info
        task.upgrade_lock()

        try:
            sushy_task = task_monitor.get_task()
            LOG.debug('BIOS update task state for node %(node)s: '
                      '%(state)s',
                      {'node': node.uuid,
                       'state': sushy_task.task_state})

            # Check if task has started (STARTING state or beyond)
            # TaskState can be: New, Starting, Running, Suspended,
            # Interrupted, Pending, Stopping, Completed, Killed,
            # Exception, Service, Cancelling, Cancelled
            if sushy_task.task_state in [sushy.TASK_STATE_STARTING,
                                         sushy.TASK_STATE_RUNNING,
                                         sushy.TASK_STATE_PENDING]:
                LOG.info('BIOS firmware update task has started for '
                         'node %(node)s (state: %(state)s). '
                         'Triggering reboot to apply update.',
                         {'node': node.uuid,
                          'state': sushy_task.task_state})

                # Mark reboot as triggered to avoid repeated reboots
                current_update['bios_reboot_triggered'] = True
                node.set_driver_internal_info(
                    'redfish_fw_updates', settings)
                node.save()

                # Trigger the reboot
                power_timeout = current_update.get('power_timeout', 0)
                manager_utils.node_power_action(task, states.REBOOT,
                                                power_timeout)

                LOG.info('Reboot initiated for node %(node)s to apply '
                         'BIOS firmware update',
                         {'node': node.uuid})
                return True
        except Exception as e:
            LOG.warning('Unable to check BIOS task state for node '
                        '%(node)s: %(error)s. Will retry.',
                        {'node': node.uuid, 'error': e})

        return False

    def _handle_wait_completion(self, task, update_service, settings,
                                current_update):
        """Handle firmware update wait completion.

        :param task: a TaskManager instance
        :param update_service: the sushy firmware update service
        :param settings: firmware update settings
        :param current_update: the current firmware update being processed
        """
        node = task.node

        # Upgrade lock at the start since we may modify driver_internal_info
        task.upgrade_lock()

        # Check if this is BMC version checking
        if current_update.get('bmc_version_checking'):
            current_update.pop('bmc_version_checking', None)
            node.set_driver_internal_info(
                'redfish_fw_updates', settings)
            node.save()
            # Continue BMC version checking
            self._handle_bmc_update_completion(
                task, update_service, settings, current_update)
        elif current_update.get('component_type') == redfish_utils.BMC:
            # BMC update wait expired - check if task is still running
            # before transitioning to version checking
            task_still_running = False
            try:
                task_monitor = redfish_utils.get_task_monitor(
                    node, current_update['task_monitor'])
                if task_monitor.is_processing:
                    task_still_running = True
                    LOG.debug('BMC firmware update wait expired but task '
                              ' still processing for node %(node)s. '
                              'Continuing to monitor task completion.',
                              {'node': node.uuid})
            except exception.RedfishConnectionError as e:
                LOG.debug('Unable to communicate with task monitor for node '
                          '%(node)s during wait completion: %(error)s. '
                          'BMC may be resetting, will transition to version '
                          'checking.', {'node': node.uuid, 'error': e})
            except exception.RedfishError as e:
                LOG.debug('Task monitor unavailable for node %(node)s: '
                          '%(error)s. Task may have completed, transitioning '
                          'to version checking.',
                          {'node': node.uuid, 'error': e})

            if task_still_running:
                # Task is still running, continue to monitor task completion
                # Don't transition to version checking yet.
                node.set_driver_internal_info('redfish_fw_updates', settings)
                node.save()
                return

            # Task completed, deleted or BMC unavailable
            # Transition to version checking
            LOG.info('BMC firmware update wait expired for node %(node)s. '
                     'Task completed or unavailable. Transitioning to version '
                     'checking mode.',
                     {'node': node.uuid})
            self._handle_bmc_update_completion(
                task, update_service, settings, current_update)
        else:
            # Regular wait completion - mark reboot needed if this is the
            # last update. Note: BIOS components reboot immediately when
            # task starts, so they won't use this path.
            if len(settings) == 1:
                component = current_update.get('component', '')
                component_type = redfish_utils.get_component_type(component)
                # For default/unknown components, reboot may be needed
                if component_type is None:
                    node.set_driver_internal_info(
                        'firmware_reboot_requested', True)
                    node.save()
            # Continue with updates
            self._continue_updates(task, update_service, settings)

    def _check_overall_timeout(self, task):
        """Check if firmware update has exceeded overall timeout.

        :param task: A TaskManager instance
        :returns: True if timeout exceeded and error was handled,
                  False otherwise
        """
        node = task.node
        overall_timeout = CONF.redfish.firmware_update_overall_timeout
        if overall_timeout <= 0:
            return False

        start_time_str = node.driver_internal_info.get(
            'redfish_fw_update_start_time')
        if not start_time_str:
            return False

        start_time = timeutils.parse_isotime(start_time_str)
        elapsed = timeutils.utcnow(True) - start_time
        if elapsed.total_seconds() < overall_timeout:
            return False

        msg = (_('Firmware update on node %(node)s has exceeded '
                 'the overall timeout of %(timeout)s seconds. '
                 'Elapsed time: %(elapsed)s seconds.')
               % {'node': node.uuid,
                  'timeout': overall_timeout,
                  'elapsed': int(elapsed.total_seconds())})
        LOG.error(msg)
        task.upgrade_lock()
        self._clear_updates(node)
        manager_utils.servicing_error_handler(task, msg, traceback=False)
        return True

    @METRICS.timer('RedfishFirmware._check_node_redfish_firmware_update')
    def _check_node_redfish_firmware_update(self, task):
        """Check the progress of running firmware update on a node."""

        node = task.node

        # Check overall timeout for firmware update operation
        if self._check_overall_timeout(task):
            return

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
                        {'node': node.uuid, 'error': e})
            return

        # Touch provisioning to indicate progress is being monitored.
        # This prevents heartbeat timeout from triggering for steps that
        # don't require the ramdisk agent (requires_ramdisk=False).
        # Note: Only touch after successful BMC communication to ensure
        # the process eventually times out if the BMC is unresponsive.
        node.touch_provisioning()

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

                # Handle wait completion
                self._handle_wait_completion(
                    task, update_service, settings, current_update)
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
        except exception.RedfishConnectionError as e:
            # If the BMC firmware is being updated, the BMC will be
            # unavailable for some amount of time.
            LOG.warning('Unable to communicate with task monitor service '
                        'on node %(node)s. Will try again on the next poll. '
                        'Error: %(error)s',
                        {'node': node.uuid, 'error': e})
            return
        except exception.RedfishError:
            # The BMC deleted the Task before we could query it
            LOG.warning('Firmware update completed for node %(node)s, '
                        'firmware %(firmware_image)s, but success of the '
                        'update is unknown.  Assuming update was successful.',
                        {'node': node.uuid,
                         'firmware_image': current_update['url']})
            self._continue_updates(task, update_service, settings)
            return

        # Special handling for BIOS and NIC updates
        component = current_update.get('component', '')
        component_type = redfish_utils.get_component_type(component)

        if task_monitor.is_processing and component_type == redfish_utils.BIOS:
            # For BIOS, check if task has reached STARTING state
            # and trigger reboot immediately
            if self._handle_bios_task_starting(task, task_monitor, settings,
                                               current_update):
                return  # Reboot triggered, done
            # Task is still processing, keep polling
            return

        if task_monitor.is_processing and component_type == redfish_utils.NIC:
            # For NIC, wait 30s to see if hardware needs reboot
            if self._handle_nic_task_starting(task, task_monitor, settings,
                                              current_update):
                return  # Reboot triggered, done
            # Task is still processing (or waiting), keep polling
            return

        if not task_monitor.is_processing:
            # The last response does not necessarily contain a Task,
            # so get it
            sushy_task = task_monitor.get_task()

            # NOTE(iurygregory): Some BMCs (particularly HPE iLO) may return
            # is_processing=False while the task is still in RUNNING, STARTING,
            # or PENDING state. Only treat it as completion if the task state
            # indicates it's actually finished.
            if sushy_task.task_state in [sushy.TASK_STATE_RUNNING,
                                         sushy.TASK_STATE_STARTING,
                                         sushy.TASK_STATE_PENDING]:
                LOG.debug('Firmware update task for node %(node)s is in '
                          '%(state)s state. Continuing to poll.',
                          {'node': node.uuid, 'state': sushy_task.task_state})
                return

            # Only parse the messages if the BMC did not return parsed
            # messages
            messages = []
            if sushy_task.messages and not sushy_task.messages[0].message:
                sushy_task.parse_messages()

            if sushy_task.messages is not None:
                for m in sushy_task.messages:
                    msg = m.message
                    if not msg or msg.lower() in ['unknown', 'unknown error']:
                        msg = m.message_id
                    if msg:
                        messages.append(msg)

            task.upgrade_lock()
            self._handle_task_completion(task, sushy_task, messages,
                                         update_service, settings,
                                         current_update)
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
            raise
