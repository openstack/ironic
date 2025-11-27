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


from oslo_log import log as logging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as cond_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils

LOG = logging.getLogger(__name__)

# Internal field to mark whether ironic or inspector manages boot for the node
_IRONIC_MANAGES_BOOT = 'inspector_manage_boot'


def tear_down_managed_boot(task, always_power_off=False):
    errors = []

    ironic_manages_boot = utils.pop_node_nested_field(
        task.node, 'driver_internal_info', _IRONIC_MANAGES_BOOT)

    if ironic_manages_boot:
        try:
            task.driver.boot.clean_up_ramdisk(task)
        except Exception as exc:
            errors.append(_('unable to clean up ramdisk boot: %s') % exc)
            LOG.exception('Unable to clean up ramdisk boot for node %s',
                          task.node.uuid)
        try:
            with cond_utils.power_state_for_network_configuration(task):
                task.driver.network.remove_inspection_network(task)
        except Exception as exc:
            errors.append(_('unable to remove inspection ports: %s') % exc)
            LOG.exception('Unable to remove inspection network for node %s',
                          task.node.uuid)

    if ((ironic_manages_boot or always_power_off)
            and CONF.inspector.power_off
            and not utils.fast_track_enabled(task.node)):
        if task.node.disable_power_off:
            LOG.debug('Rebooting node %s instead of powering it off because '
                      'disable_power_off is set to True', task.node.uuid)
            power_state = states.REBOOT
            err_msg = _('unable to reboot the node: %s')
        else:
            power_state = states.POWER_OFF
            err_msg = _('unable to power off the node: %s')

        try:
            cond_utils.node_power_action(task, power_state)
        except Exception as exc:
            errors.append(err_msg % exc)
            LOG.exception(err_msg, task.node.uuid)

    return errors


def inspection_error_handler(task, error, raise_exc=False, clean_up=True):
    if clean_up:
        tear_down_managed_boot(task)

    task.node.last_error = error
    if raise_exc:
        task.node.save()
        raise exception.HardwareInspectionFailure(error=error)
    else:
        task.process_event('fail')


def ironic_manages_boot(task, raise_exc=False):
    """Whether ironic should manage boot for this node."""
    try:
        task.driver.boot.validate_inspection(task)
    except exception.UnsupportedDriverExtension as e:
        LOG.debug('The boot interface %(iface)s of the node %(node)s does '
                  'not support managed boot for in-band inspection or '
                  'the required options are not populated: %(exc)s',
                  {'node': task.node.uuid,
                   'iface': task.node.get_interface('boot'),
                   'exc': e})
        if raise_exc:
            raise
        return False

    try:
        task.driver.network.validate_inspection(task)
    except exception.UnsupportedDriverExtension as e:
        LOG.debug('The network interface %(iface)s of the node %(node)s does '
                  'not support managed boot for in-band inspection or '
                  'the required options are not populated: %(exc)s',
                  {'node': task.node.uuid,
                   'iface': task.node.get_interface('network'),
                   'exc': e})
        if raise_exc:
            raise
        return False

    return True


def prepare_managed_inspection(task, endpoint):
    """Prepare the boot interface for managed inspection."""
    params = dict(
        utils.parse_kernel_params(CONF.inspector.extra_kernel_params),
        **{'ipa-inspection-callback-url': endpoint})
    if CONF.inspector.force_dhcp:
        # Ensure LLDP collection for inspection on all interfaces.
        params.setdefault('ipa-collect-lldp', '1')
    if utils.fast_track_enabled(task.node):
        params['ipa-api-url'] = deploy_utils.get_ironic_api_url()

    if not task.node.disable_power_off:
        cond_utils.node_power_action(task, states.POWER_OFF)
    with cond_utils.power_state_for_network_configuration(task):
        task.driver.network.add_inspection_network(task)
    task.driver.boot.prepare_ramdisk(task, ramdisk_params=params)


class Common(base.InspectInterface):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return {}  # no properties

    def validate(self, task):
        """Validate the driver-specific inspection information.

        If invalid, raises an exception; otherwise returns None.

        :param task: a task from TaskManager.
        :raises: UnsupportedDriverExtension
        """
        utils.parse_kernel_params(CONF.inspector.extra_kernel_params)
        if CONF.inspector.require_managed_boot:
            ironic_manages_boot(task, raise_exc=True)

    def inspect_hardware(self, task):
        """Inspect hardware to obtain the hardware properties.

        Results will be checked in a periodic task.

        :param task: a task from TaskManager.
        :returns: states.INSPECTWAIT
        :raises: HardwareInspectionFailure on failure
        """
        try:
            inspect_utils.create_ports_if_not_exist(task)
        except exception.UnsupportedDriverExtension:
            LOG.debug('Pre-creating ports prior to inspection not supported'
                      ' on node %s.', task.node.uuid)

        manage_boot = ironic_manages_boot(
            task, raise_exc=CONF.inspector.require_managed_boot)

        utils.set_node_nested_field(task.node, 'driver_internal_info',
                                    _IRONIC_MANAGES_BOOT, manage_boot)
        # Make this interface work with the Ironic own /continue_inspection
        # endpoint to simplify migration to the new in-band inspection
        # implementation.
        inspect_utils.cache_lookup_addresses(task.node)
        task.node.save()

        LOG.debug('Starting inspection for node %(uuid)s. Booting is '
                  '%(managed)s by ironic',
                  {'uuid': task.node.uuid,
                   'managed': manage_boot})

        if manage_boot:
            try:
                self._start_managed_inspection(task)
            except Exception as exc:
                LOG.exception('Unable to start managed inspection for node '
                              '%(uuid)s: %(err)s',
                              {'uuid': task.node.uuid, 'err': exc})
                error = _('unable to start inspection: %s') % exc
                inspection_error_handler(task, error, raise_exc=True)
        else:
            self._start_unmanaged_inspection(task)
        return states.INSPECTWAIT

    def _power_on_or_reboot(self, task):
        # Handles disable_power_off properly
        next_state = (states.REBOOT if task.node.disable_power_off
                      else states.POWER_ON)
        cond_utils.node_power_action(task, next_state)


def clean_up(task, finish=True, always_power_off=False):
    errors = tear_down_managed_boot(task, always_power_off=always_power_off)
    if errors:
        errors = ', '.join(errors)
        LOG.error('Inspection clean up failed for node %(uuid)s: %(err)s',
                  {'uuid': task.node.uuid, 'err': errors})
        msg = _('Inspection clean up failed: %s') % errors
        inspection_error_handler(task, msg, raise_exc=False, clean_up=False)
    elif finish:
        LOG.info('Inspection finished successfully for node %s',
                 task.node.uuid)
        task.process_event('done')
