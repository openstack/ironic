#    Copyright 2015, Cisco Systems.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Ironic Cisco UCSM interfaces.
Provides basic power control of servers managed by Cisco UCSM using PyUcs Sdk.
"""

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.ucs import helper as ucs_helper

ucs_power = importutils.try_import('UcsSdk.utils.power')
ucs_error = importutils.try_import('UcsSdk.utils.exception')

LOG = logging.getLogger(__name__)

UCS_TO_IRONIC_POWER_STATE = {
    'up': states.POWER_ON,
    'down': states.POWER_OFF,
}

IRONIC_TO_UCS_POWER_STATE = {
    states.POWER_ON: 'up',
    states.POWER_OFF: 'down',
    states.REBOOT: 'hard-reset-immediate'
}


def _wait_for_state_change(target_state, ucs_power_handle):
    """Wait and check for the power state change."""
    state = [None]
    retries = [0]

    def _wait(state, retries):
        state[0] = ucs_power_handle.get_power_state()
        if ((retries[0] != 0) and (
           UCS_TO_IRONIC_POWER_STATE.get(state[0]) == target_state)):
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.cisco_ucs.max_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()

        retries[0] += 1

    timer = loopingcall.FixedIntervalLoopingCall(_wait, state, retries)
    timer.start(interval=CONF.cisco_ucs.action_interval).wait()
    return UCS_TO_IRONIC_POWER_STATE.get(state[0], states.ERROR)


class Power(base.PowerInterface):
    """Cisco Power Interface.

    This PowerInterface class provides a mechanism for controlling the
    power state of servers managed by Cisco UCS Manager.
    """

    def get_properties(self):
        """Returns common properties of the driver."""
        return ucs_helper.COMMON_PROPERTIES

    def validate(self, task):
        """Check that node 'driver_info' is valid.

        Check that node 'driver_info' contains the required fields.

        :param task: instance of `ironic.manager.task_manager.TaskManager`.
        :raises: MissingParameterValue if required CiscoDriver parameters
            are missing.
        """
        ucs_helper.parse_driver_info(task.node)

    @ucs_helper.requires_ucs_client
    def get_power_state(self, task, helper=None):
        """Get the current power state.

        Poll the host for the current power state of the node.

        :param task: instance of `ironic.manager.task_manager.TaskManager`.
        :param helper: ucs helper instance
        :raises: MissingParameterValue if required CiscoDriver parameters
            are missing.
        :raises: UcsOperationError on error from UCS Client.
        :returns: power state. One of :class:`ironic.common.states`.
        """

        try:
            power_handle = ucs_power.UcsPower(helper)
            power_status = power_handle.get_power_state()
        except ucs_error.UcsOperationError as ucs_exception:
            LOG.error("%(driver)s: get_power_state operation failed for "
                      "node %(uuid)s with error: %(msg)s.",
                      {'driver': task.node.driver, 'uuid': task.node.uuid,
                       'msg': ucs_exception})
            operation = _('getting power status')
            raise exception.UcsOperationError(operation=operation,
                                              error=ucs_exception,
                                              node=task.node.uuid)
        return UCS_TO_IRONIC_POWER_STATE.get(power_status, states.ERROR)

    @task_manager.require_exclusive_lock
    @ucs_helper.requires_ucs_client
    def set_power_state(self, task, pstate, helper=None):
        """Turn the power on or off.

        Set the power state of a node.

        :param task: instance of `ironic.manager.task_manager.TaskManager`.
        :param pstate: Either POWER_ON or POWER_OFF from :class:
            `ironic.common.states`.
        :param helper: ucs helper instance
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: MissingParameterValue if required CiscoDriver parameters
            are missing.
        :raises: UcsOperationError on error from UCS Client.
        :raises: PowerStateFailure if the desired power state couldn't be set.
        """

        if pstate not in (states.POWER_ON, states.POWER_OFF):
            msg = _("set_power_state called with invalid power state "
                    "'%s'") % pstate
            raise exception.InvalidParameterValue(msg)

        try:
            ucs_power_handle = ucs_power.UcsPower(helper)
            power_status = ucs_power_handle.get_power_state()
            if UCS_TO_IRONIC_POWER_STATE.get(power_status) != pstate:
                ucs_power_handle.set_power_state(
                    IRONIC_TO_UCS_POWER_STATE.get(pstate))
            else:
                return
        except ucs_error.UcsOperationError as ucs_exception:
            LOG.error("%(driver)s: set_power_state operation failed for "
                      "node %(uuid)s with error: %(msg)s.",
                      {'driver': task.node.driver, 'uuid': task.node.uuid,
                       'msg': ucs_exception})
            operation = _("setting power status")
            raise exception.UcsOperationError(operation=operation,
                                              error=ucs_exception,
                                              node=task.node.uuid)
        state = _wait_for_state_change(pstate, ucs_power_handle)
        if state != pstate:
            timeout = CONF.cisco_ucs.action_interval * CONF.cisco_ucs.max_retry
            LOG.error("%(driver)s: driver failed to change node %(uuid)s "
                      "power state to %(state)s within %(timeout)s "
                      "seconds.",
                      {'driver': task.node.driver, 'uuid': task.node.uuid,
                          'state': pstate, 'timeout': timeout})
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    @ucs_helper.requires_ucs_client
    def reboot(self, task, helper=None):
        """Cycles the power to a node.

        :param task: a TaskManager instance.
        :param helper: ucs helper instance.
        :raises: UcsOperationError on error from UCS Client.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.
        """
        try:
            ucs_power_handle = ucs_power.UcsPower(helper)
            ucs_power_handle.reboot()
        except ucs_error.UcsOperationError as ucs_exception:
            LOG.error("%(driver)s: driver failed to reset node %(uuid)s "
                      "power state.",
                      {'driver': task.node.driver, 'uuid': task.node.uuid})
            operation = _("rebooting")
            raise exception.UcsOperationError(operation=operation,
                                              error=ucs_exception,
                                              node=task.node.uuid)

        state = _wait_for_state_change(states.POWER_ON, ucs_power_handle)
        if state != states.POWER_ON:
            timeout = CONF.cisco_ucs.action_interval * CONF.cisco_ucs.max_retry
            LOG.error("%(driver)s: driver failed to reboot node %(uuid)s "
                      "within %(timeout)s seconds.",
                      {'driver': task.node.driver,
                       'uuid': task.node.uuid, 'timeout': timeout})
            raise exception.PowerStateFailure(pstate=states.POWER_ON)
