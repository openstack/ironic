# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
iLO Power Driver
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.ilo import common as ilo_common

ilo_error = importutils.try_import('proliantutils.exception')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


def _attach_boot_iso_if_needed(task):
    """Attaches boot ISO for a deployed node.

    This method checks the instance info of the baremetal node for a
    boot iso. If the instance info has a value of key 'ilo_boot_iso',
    it indicates that 'boot_option' is 'netboot'. Therefore it attaches
    the boot ISO on the baremetal node and then sets the node to boot from
    virtual media cdrom.

    :param task: a TaskManager instance containing the node to act on.
    """
    i_info = task.node.instance_info
    node_state = task.node.provision_state

    # NOTE: On instance rebuild, ilo_boot_iso will be present in
    # instance_info but the node will be in DEPLOYING state.
    # In such a scenario, the ilo_boot_iso shouldn't be
    # attached to the node while powering on the node (the node
    # should boot from deploy ramdisk instead, which will already
    # be attached by the deploy driver).
    if 'ilo_boot_iso' in i_info and node_state == states.ACTIVE:
        ilo_common.setup_vmedia_for_boot(task, i_info['ilo_boot_iso'])
        manager_utils.node_set_boot_device(task, boot_devices.CDROM)


def _get_power_state(node):
    """Returns the current power state of the node.

    :param node: The node.
    :returns: power state, one of :mod: `ironic.common.states`.
    :raises: InvalidParameterValue if required iLO credentials are missing.
    :raises: IloOperationError on an error from IloClient library.
    """

    ilo_object = ilo_common.get_ilo_object(node)

    # Check the current power state.
    try:
        power_status = ilo_object.get_host_power_status()

    except ilo_error.IloError as ilo_exception:
        LOG.error("iLO get_power_state failed for node %(node_id)s with "
                  "error: %(error)s.",
                  {'node_id': node.uuid, 'error': ilo_exception})
        operation = _('iLO get_power_status')
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)

    if power_status == "ON":
        return states.POWER_ON
    elif power_status == "OFF":
        return states.POWER_OFF
    else:
        return states.ERROR


def _wait_for_state_change(node, target_state):
    """Wait for the power state change to get reflected."""
    state = [None]
    retries = [0]

    def _wait(state):

        state[0] = _get_power_state(node)

        # NOTE(rameshg87): For reboot operations, initially the state
        # will be same as the final state. So defer the check for one retry.
        if retries[0] != 0 and state[0] == target_state:
            raise loopingcall.LoopingCallDone()

        if retries[0] > CONF.ilo.power_retry:
            state[0] = states.ERROR
            raise loopingcall.LoopingCallDone()

        retries[0] += 1

    # Start a timer and wait for the operation to complete.
    timer = loopingcall.FixedIntervalLoopingCall(_wait, state)
    timer.start(interval=CONF.ilo.power_wait).wait()

    return state[0]


def _set_power_state(task, target_state):
    """Turns the server power on/off or do a reboot.

    :param task: a TaskManager instance containing the node to act on.
    :param target_state: target state of the node.
    :raises: InvalidParameterValue if an invalid power state was specified.
    :raises: IloOperationError on an error from IloClient library.
    :raises: PowerStateFailure if the power couldn't be set to target_state.
    """

    node = task.node
    ilo_object = ilo_common.get_ilo_object(node)

    # Trigger the operation based on the target state.
    try:
        if target_state == states.POWER_OFF:
            ilo_object.hold_pwr_btn()
        elif target_state == states.POWER_ON:
            _attach_boot_iso_if_needed(task)
            ilo_object.set_host_power('ON')
        elif target_state == states.REBOOT:
            _attach_boot_iso_if_needed(task)
            ilo_object.reset_server()
            target_state = states.POWER_ON
        else:
            msg = _("_set_power_state called with invalid power state "
                    "'%s'") % target_state
            raise exception.InvalidParameterValue(msg)

    except ilo_error.IloError as ilo_exception:
        LOG.error("iLO set_power_state failed to set state to %(tstate)s "
                  " for node %(node_id)s with error: %(error)s",
                  {'tstate': target_state, 'node_id': node.uuid,
                   'error': ilo_exception})
        operation = _('iLO set_power_state')
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)

    # Wait till the state change gets reflected.
    state = _wait_for_state_change(node, target_state)

    if state != target_state:
        timeout = (CONF.ilo.power_wait) * (CONF.ilo.power_retry)
        LOG.error("iLO failed to change state to %(tstate)s "
                  "within %(timeout)s sec",
                  {'tstate': target_state, 'timeout': timeout})
        raise exception.PowerStateFailure(pstate=target_state)


class IloPower(base.PowerInterface):

    def get_properties(self):
        return ilo_common.COMMON_PROPERTIES

    @METRICS.timer('IloPower.validate')
    def validate(self, task):
        """Check if node.driver_info contains the required iLO credentials.

        :param task: a TaskManager instance.
        :param node: Single node object.
        :raises: InvalidParameterValue if required iLO credentials are missing.
        """
        ilo_common.parse_driver_info(task.node)

    @METRICS.timer('IloPower.get_power_state')
    def get_power_state(self, task):
        """Gets the current power state.

        :param task: a TaskManager instance.
        :param node: The Node.
        :returns: one of :mod:`ironic.common.states` POWER_OFF,
            POWER_ON or ERROR.
        :raises: InvalidParameterValue if required iLO credentials are missing.
        :raises: IloOperationError on an error from IloClient library.
        """
        return _get_power_state(task.node)

    @METRICS.timer('IloPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state):
        """Turn the current power state on or off.

        :param task: a TaskManager instance.
        :param node: The Node.
        :param power_state: The desired power state POWER_ON,POWER_OFF or
            REBOOT from :mod:`ironic.common.states`.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: IloOperationError on an error from IloClient library.
        :raises: PowerStateFailure if the power couldn't be set to power_state.
        """
        _set_power_state(task, power_state)

    @METRICS.timer('IloPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Reboot the node

        :param task: a TaskManager instance.
        :param node: The Node.
        :raises: PowerStateFailure if the final state of the node is not
            POWER_ON.
        :raises: IloOperationError on an error from IloClient library.
        """
        node = task.node
        current_pstate = _get_power_state(node)
        if current_pstate == states.POWER_ON:
            _set_power_state(task, states.REBOOT)
        elif current_pstate == states.POWER_OFF:
            _set_power_state(task, states.POWER_ON)
