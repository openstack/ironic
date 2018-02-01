# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.drivers.modules.oneview import management

client_exception = importutils.try_import('hpOneView.exceptions')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

POWER_ON = {'powerState': 'On'}
POWER_OFF = {'powerState': 'Off', 'powerControl': 'PressAndHold'}
REBOOT = {'powerState': 'On', 'powerControl': 'ColdBoot'}
SOFT_REBOOT = {'powerState': 'On', 'powerControl': 'Reset'}
SOFT_POWER_OFF = {'powerState': 'Off', 'powerControl': 'MomentaryPress'}

GET_POWER_STATE_MAP = {
    'On': states.POWER_ON,
    'Off': states.POWER_OFF,
    'Resetting': states.REBOOT,
    'PoweringOff': states.POWER_ON,
    'PoweringOn': states.POWER_OFF
}

SET_POWER_STATE_MAP = {
    states.POWER_ON: POWER_ON,
    states.POWER_OFF: POWER_OFF,
    states.REBOOT: REBOOT,
    states.SOFT_REBOOT: SOFT_REBOOT,
    states.SOFT_POWER_OFF: SOFT_POWER_OFF
}


class OneViewPower(base.PowerInterface):

    def get_properties(self):
        return deploy_utils.get_properties()

    @METRICS.timer('OneViewPower.validate')
    def validate(self, task):
        """Checks required info on 'driver_info' and validates node with OneView

        Validates whether the 'oneview_info' property of the supplied
        task's node contains the required info such as server_hardware_uri,
        server_hardware_type, server_profile_template_uri and
        enclosure_group_uri. Also, checks if the server profile of the node is
        applied, if NICs are valid for the server profile of the node, and if
        the server hardware attributes (ram, memory, vcpus count) are
        consistent with OneView. It validates if the node is being used by
        Oneview.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: InvalidParameterValue if parameters set are inconsistent with
                 resources in OneView
        :raises: InvalidParameterValue if the node in use by OneView.
        :raises: OneViewError if not possible to get OneView's information
                 for the given node, if not possible to retrieve Server
                 Hardware from OneView.
        """
        common.verify_node_info(task.node)

        try:
            common.validate_oneview_resources_compatibility(task)
            if deploy_utils.is_node_in_use_by_oneview(task.node):
                raise exception.InvalidParameterValue(
                    _("Node %s is in use by OneView.") % task.node.uuid)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)

    @METRICS.timer('OneViewPower.get_power_state')
    def get_power_state(self, task):
        """Gets the current power state.

        :param task: a TaskManager instance.
        :returns: one of :mod:`ironic.common.states` POWER_OFF,
                  POWER_ON or ERROR.
        :raises: OneViewError if fails to retrieve power state of OneView
                 resource
        """
        oneview_client = common.get_hponeview_client()
        server_hardware = task.node.driver_info.get('server_hardware_uri')
        try:
            server_hardware = oneview_client.server_hardware.get(
                server_hardware)
        except client_exception.HPOneViewException as exc:
            LOG.error(
                "Error getting power state for node %(node)s. Error:"
                "%(error)s",
                {'node': task.node.uuid, 'error': exc}
            )
            raise exception.OneViewError(error=exc)
        else:
            power_state = server_hardware.get('powerState')
            return GET_POWER_STATE_MAP.get(power_state)

    @METRICS.timer('OneViewPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state, timeout=None):
        """Turn the current power state on or off.

        :param task: a TaskManager instance.
        :param power_state: The desired power state POWER_ON, POWER_OFF or
                            REBOOT from :mod:`ironic.common.states`.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
                        power state. ``None`` indicates the default timeout.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: PowerStateFailure if the power couldn't be set to power_state.
        :raises: OneViewError if OneView fails setting the power state.
        """
        oneview_client = common.get_hponeview_client()

        if deploy_utils.is_node_in_use_by_oneview(task.node):
            raise exception.PowerStateFailure(_(
                "Cannot set power state '%(power_state)s' to node %(node)s. "
                "The node is in use by OneView.") %
                {'power_state': power_state,
                 'node': task.node.uuid})

        if power_state not in SET_POWER_STATE_MAP:
            raise exception.InvalidParameterValue(
                _("set_power_state called with invalid power state %(state)s "
                  "on node: %(node)s") % {
                    'state': power_state,
                    'node': task.node.uuid
                })

        LOG.debug('Setting power state of node %(node_uuid)s to '
                  '%(power_state)s',
                  {'node_uuid': task.node.uuid, 'power_state': power_state})

        server_hardware = task.node.driver_info.get('server_hardware_uri')
        timeout = -1 if timeout is None else timeout

        try:
            if power_state == states.POWER_ON:
                management.set_boot_device(task)
                oneview_client.server_hardware.update_power_state(
                    SET_POWER_STATE_MAP.get(power_state),
                    server_hardware, timeout=timeout)
            elif (power_state == states.REBOOT or
                  power_state == states.SOFT_REBOOT):
                power_off_mode = (states.POWER_OFF
                                  if power_state == states.REBOOT
                                  else states.SOFT_POWER_OFF)

                oneview_client.server_hardware.update_power_state(
                    SET_POWER_STATE_MAP.get(power_off_mode),
                    server_hardware, timeout=timeout)
                management.set_boot_device(task)
                oneview_client.server_hardware.update_power_state(
                    SET_POWER_STATE_MAP.get(states.POWER_ON),
                    server_hardware, timeout=timeout)
            else:
                oneview_client.server_hardware.update_power_state(
                    SET_POWER_STATE_MAP.get(power_state),
                    server_hardware, timeout=timeout)
        except client_exception.HPOneViewException as exc:
            raise exception.OneViewError(
                _("Failed to setting power state on node: %(node)s. "
                  "Error: %(error)s.") % {
                      'node': task.node.uuid,
                      'error': exc
                })

    @METRICS.timer('OneViewPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task, timeout=None):
        """Reboot the node.

        :param task: a TaskManager instance.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
                        power state. ``None`` indicates to use default timeout.
        :raises: PowerStateFailure if the final state of the node is not
                 POWER_ON.
        """
        current_power_state = self.get_power_state(task)
        if current_power_state == states.POWER_ON:
            self.set_power_state(task, states.REBOOT, timeout=timeout)
        else:
            self.set_power_state(task, states.POWER_ON, timeout=timeout)

    @METRICS.timer('OneViewPower.get_supported_power_states')
    def get_supported_power_states(self, task):
        """Get a list of the supported power states.

        :param task: A TaskManager instance containing the node to act on.
                     Currently not used.
        :returns: A list with the supported power states defined
                  in :mod:`ironic.common.states`.
        """
        return [states.POWER_ON, states.POWER_OFF, states.REBOOT,
                states.SOFT_REBOOT, states.SOFT_POWER_OFF]
