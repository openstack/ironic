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
iBMC Power Interface
"""

from oslo_log import log
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as cond_utils
from ironic.drivers import base
from ironic.drivers.modules.ibmc import mappings
from ironic.drivers.modules.ibmc import utils

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')

LOG = log.getLogger(__name__)

EXPECT_POWER_STATE_MAP = {
    states.REBOOT: states.POWER_ON,
    states.SOFT_REBOOT: states.POWER_ON,
    states.SOFT_POWER_OFF: states.POWER_OFF,
}


class IBMCPower(base.PowerInterface):

    # NOTE(TheJulia): Deprecating November 2023 in favor of Redfish
    # and due to a lack of active driver maintenance.
    supported = False

    def __init__(self):
        """Initialize the iBMC power interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(IBMCPower, self).__init__()
        if not ibmc_client:
            raise exception.DriverLoadError(
                driver='ibmc',
                reason=_('Unable to import the python-ibmcclient library'))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the iBMC driver.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        utils.parse_driver_info(task.node)

    @utils.handle_ibmc_exception('get iBMC power state')
    def get_power_state(self, task):
        """Get the current power state of the task's node.

        :param task: A TaskManager instance containing the node to act on.
        :returns: A power state. One of :mod:`ironic.common.states`.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            system = conn.system.get()
            return mappings.GET_POWER_STATE_MAP.get(system.power_state)

    @task_manager.require_exclusive_lock
    @utils.handle_ibmc_exception('set iBMC power state')
    def set_power_state(self, task, power_state, timeout=None):
        """Set the power state of the task's node.

        :param task: A TaskManager instance containing the node to act on.
        :param power_state: Any power state from :mod:`ironic.common.states`.
        :param timeout: Time to wait for the node to reach the requested state.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            reset_type = mappings.SET_POWER_STATE_MAP.get(power_state)
            conn.system.reset(reset_type)

        target_state = EXPECT_POWER_STATE_MAP.get(power_state, power_state)
        cond_utils.node_wait_for_power_state(task, target_state,
                                             timeout=timeout)

    @task_manager.require_exclusive_lock
    @utils.handle_ibmc_exception('reboot iBMC')
    def reboot(self, task, timeout=None):
        """Perform a hard reboot of the task's node.

        :param task: A TaskManager instance containing the node to act on.
        :param timeout: Time to wait for the node to become powered on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IBMCConnectionError when it fails to connect to iBMC
        :raises: IBMCError when iBMC responses an error information
        """
        ibmc = utils.parse_driver_info(task.node)
        with ibmc_client.connect(**ibmc) as conn:
            system = conn.system.get()
            current_power_state = (
                mappings.GET_POWER_STATE_MAP.get(system.power_state)
            )
            if current_power_state == states.POWER_ON:
                conn.system.reset(
                    mappings.SET_POWER_STATE_MAP.get(states.REBOOT))
            else:
                conn.system.reset(
                    mappings.SET_POWER_STATE_MAP.get(states.POWER_ON))

        cond_utils.node_wait_for_power_state(task, states.POWER_ON,
                                             timeout=timeout)

    def get_supported_power_states(self, task):
        """Get a list of the supported power states.

        :param task: A TaskManager instance containing the node to act on.
            Not used by this driver at the moment.
        :returns: A list with the supported power states defined
                  in :mod:`ironic.common.states`.
        """
        return list(mappings.SET_POWER_STATE_MAP)
