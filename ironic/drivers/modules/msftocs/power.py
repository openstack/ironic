# Copyright 2015 Cloudbase Solutions Srl
# All Rights Reserved.
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
MSFT OCS Power Driver
"""
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _, _LE
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.msftocs import common as msftocs_common
from ironic.drivers.modules.msftocs import msftocsclient

LOG = log.getLogger(__name__)

POWER_STATES_MAP = {
    msftocsclient.POWER_STATUS_ON: states.POWER_ON,
    msftocsclient.POWER_STATUS_OFF: states.POWER_OFF,
}


class MSFTOCSPower(base.PowerInterface):
    def get_properties(self):
        """Returns the driver's properties."""
        return msftocs_common.get_properties()

    def validate(self, task):
        """Validate the driver_info in the node.

        Check if the driver_info contains correct required fields.

        :param task: a TaskManager instance containing the target node.
        :raises: MissingParameterValue if any required parameters are missing.
        :raises: InvalidParameterValue if any parameters have invalid values.
        """
        msftocs_common.parse_driver_info(task.node)

    def get_power_state(self, task):
        """Get the power state from the node.

        :param task: a TaskManager instance containing the target node.
        :raises: MSFTOCSClientApiException.
        """
        client, blade_id = msftocs_common.get_client_info(
            task.node.driver_info)
        return POWER_STATES_MAP[client.get_blade_state(blade_id)]

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Set the power state of the node.

        Turn the node power on or off.

        :param task: a TaskManager instance contains the target node.
        :param pstate: The desired power state of the node.
        :raises: PowerStateFailure if the power cannot set to pstate.
        :raises: InvalidParameterValue
        """
        client, blade_id = msftocs_common.get_client_info(
            task.node.driver_info)

        try:
            if pstate == states.POWER_ON:
                client.set_blade_on(blade_id)
            elif pstate == states.POWER_OFF:
                client.set_blade_off(blade_id)
            else:
                raise exception.InvalidParameterValue(
                    _('Unsupported target_state: %s') % pstate)
        except exception.MSFTOCSClientApiException as ex:
            LOG.exception(_LE("Changing the power state to %(pstate)s failed. "
                              "Error: %(err_msg)s"),
                          {"pstate": pstate, "err_msg": ex})
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycle the power of the node

        :param task: a TaskManager instance contains the target node.
        :raises: PowerStateFailure if failed to reboot.
        """
        client, blade_id = msftocs_common.get_client_info(
            task.node.driver_info)
        try:
            client.set_blade_power_cycle(blade_id)
        except exception.MSFTOCSClientApiException as ex:
            LOG.exception(_LE("Reboot failed. Error: %(err_msg)s"),
                          {"err_msg": ex})
            raise exception.PowerStateFailure(pstate=states.REBOOT)
