# Copyright 2015, Cisco Systems.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_service import loopingcall
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.cimc import common

imcsdk = importutils.try_import('ImcSdk')


if imcsdk:
    CIMC_TO_IRONIC_POWER_STATE = {
        imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON: states.POWER_ON,
        imcsdk.ComputeRackUnit.CONST_OPER_POWER_OFF: states.POWER_OFF,
    }

    IRONIC_TO_CIMC_POWER_STATE = {
        states.POWER_ON: imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_UP,
        states.POWER_OFF: imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_DOWN,
        states.REBOOT:
            imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_HARD_RESET_IMMEDIATE
    }


def _wait_for_state_change(target_state, task):
    """Wait and check for the power state change

    :param target_state: The target state we are waiting for.
    :param task: a TaskManager instance containing the node to act on.
    :raises: CIMCException if there is an error communicating with CIMC
    """
    store = {'state': None, 'retries': CONF.cimc.max_retry}

    def _wait(store):

        current_power_state = None
        with common.cimc_handle(task) as handle:
            try:
                rack_unit = handle.get_imc_managedobject(
                    None, None, params={"Dn": "sys/rack-unit-1"}
                )
            except imcsdk.ImcException as e:
                raise exception.CIMCException(node=task.node.uuid, error=e)
            else:
                current_power_state = rack_unit[0].get_attr("OperPower")
        store['state'] = CIMC_TO_IRONIC_POWER_STATE.get(current_power_state)

        if store['state'] == target_state:
            raise loopingcall.LoopingCallDone()

        store['retries'] -= 1
        if store['retries'] <= 0:
            store['state'] = states.ERROR
            raise loopingcall.LoopingCallDone()

    timer = loopingcall.FixedIntervalLoopingCall(_wait, store)
    timer.start(interval=CONF.cimc.action_interval).wait()
    return store['state']


class Power(base.PowerInterface):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return common.COMMON_PROPERTIES

    def validate(self, task):
        """Check if node.driver_info contains the required CIMC credentials.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue if required CIMC credentials are
                 missing.
        """
        common.parse_driver_info(task.node)

    def get_power_state(self, task):
        """Return the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: a power state. One of :mod:`ironic.common.states`.
        :raises: CIMCException if there is an error communicating with CIMC
        """
        current_power_state = None
        with common.cimc_handle(task) as handle:
            try:
                rack_unit = handle.get_imc_managedobject(
                    None, None, params={"Dn": "sys/rack-unit-1"}
                )
            except imcsdk.ImcException as e:
                raise exception.CIMCException(node=task.node.uuid, error=e)
            else:
                current_power_state = rack_unit[0].get_attr("OperPower")
        return CIMC_TO_IRONIC_POWER_STATE.get(current_power_state,
                                              states.ERROR)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Set the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param pstate: Any power state from :mod:`ironic.common.states`.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: InvalidParameterValue if an invalid power state is passed
        :raises: CIMCException if there is an error communicating with CIMC
        """
        if pstate not in IRONIC_TO_CIMC_POWER_STATE:
            msg = _("set_power_state called for %(node)s with "
                    "invalid state %(state)s")
            raise exception.InvalidParameterValue(
                msg % {"node": task.node.uuid, "state": pstate})
        with common.cimc_handle(task) as handle:
            try:
                handle.set_imc_managedobject(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER:
                            IRONIC_TO_CIMC_POWER_STATE[pstate],
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })
            except imcsdk.ImcException as e:
                raise exception.CIMCException(node=task.node.uuid, error=e)

        if pstate is states.REBOOT:
            pstate = states.POWER_ON

        state = _wait_for_state_change(pstate, task)
        if state != pstate:
            raise exception.PowerStateFailure(pstate=pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Perform a hard reboot of the task's node.

        If the node is already powered on then it shall reboot the node, if
        its off then the node will just be turned on.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: CIMCException if there is an error communicating with CIMC
        """
        current_power_state = self.get_power_state(task)

        if current_power_state == states.POWER_ON:
            self.set_power_state(task, states.REBOOT)
        elif current_power_state == states.POWER_OFF:
            self.set_power_state(task, states.POWER_ON)
