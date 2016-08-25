# Copyright 2015 FUJITSU LIMITED
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
iRMC Power Driver using the Base Server Profile
"""
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _, _LE
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.drivers.modules.irmc import common as irmc_common


scci = importutils.try_import('scciclient.irmc.scci')

LOG = logging.getLogger(__name__)

if scci:
    STATES_MAP = {states.POWER_OFF: scci.POWER_OFF,
                  states.POWER_ON: scci.POWER_ON,
                  states.REBOOT: scci.POWER_RESET}


def _set_power_state(task, target_state):
    """Turns the server power on/off or do a reboot.

    :param task: a TaskManager instance containing the node to act on.
    :param target_state: target state of the node.
    :raises: InvalidParameterValue if an invalid power state was specified.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    :raises: IRMCOperationError on an error from SCCI
    """

    node = task.node
    irmc_client = irmc_common.get_irmc_client(node)

    if target_state in (states.POWER_ON, states.REBOOT):
        irmc_boot.attach_boot_iso_if_needed(task)

    try:
        irmc_client(STATES_MAP[target_state])

    except KeyError:
        msg = _("_set_power_state called with invalid power state "
                "'%s'") % target_state
        raise exception.InvalidParameterValue(msg)

    except scci.SCCIClientError as irmc_exception:
        LOG.error(_LE("iRMC set_power_state failed to set state to %(tstate)s "
                      " for node %(node_id)s with error: %(error)s"),
                  {'tstate': target_state, 'node_id': node.uuid,
                   'error': irmc_exception})
        operation = _('iRMC set_power_state')
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)


class IRMCPower(base.PowerInterface):
    """Interface for power-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return irmc_common.COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node power info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        irmc_common.parse_driver_info(task.node)

    def get_power_state(self, task):
        """Return the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: a power state. One of :mod:`ironic.common.states`.
        :raises: InvalidParameterValue if required ipmi parameters are missing.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: IPMIFailure on an error from ipmitool (from _power_status
            call).
        """
        irmc_common.update_ipmi_properties(task)
        ipmi_power = ipmitool.IPMIPower()
        return ipmi_power.get_power_state(task)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state):
        """Set the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param power_state: Any power state from :mod:`ironic.common.states`.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: MissingParameterValue if some mandatory information
            is missing on the node
        :raises: IRMCOperationError if failed to set the power state.
        """
        _set_power_state(task, power_state)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Perform a hard reboot of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: IRMCOperationError if failed to set the power state.
        """
        current_pstate = self.get_power_state(task)
        if current_pstate == states.POWER_ON:
            _set_power_state(task, states.REBOOT)
        elif current_pstate == states.POWER_OFF:
            _set_power_state(task, states.POWER_ON)
