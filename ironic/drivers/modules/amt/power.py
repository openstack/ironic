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
AMT Power Driver
"""
import copy

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _, _LE, _LI, _LW
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.amt import common as amt_common
from ironic.drivers.modules.amt import resource_uris

pywsman = importutils.try_import('pywsman')

LOG = logging.getLogger(__name__)

AMT_POWER_MAP = {
    states.POWER_ON: '2',
    states.POWER_OFF: '8',
}


def _generate_power_action_input(action):
    """Generate Xmldoc as set_power_state input.

    This generates a Xmldoc used as input for set_power_state.

    :param action: the power action.
    :returns: Xmldoc.
    """
    method_input = "RequestPowerStateChange_INPUT"
    address = 'http://schemas.xmlsoap.org/ws/2004/08/addressing'
    anonymous = ('http://schemas.xmlsoap.org/ws/2004/08/addressing/'
                 'role/anonymous')
    wsman = 'http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd'
    namespace = resource_uris.CIM_PowerManagementService

    doc = pywsman.XmlDoc(method_input)
    root = doc.root()
    root.set_ns(namespace)
    root.add(namespace, 'PowerState', action)

    child = root.add(namespace, 'ManagedElement', None)
    child.add(address, 'Address', anonymous)

    grand_child = child.add(address, 'ReferenceParameters', None)
    grand_child.add(wsman, 'ResourceURI', resource_uris.CIM_ComputerSystem)

    g_grand_child = grand_child.add(wsman, 'SelectorSet', None)
    g_g_grand_child = g_grand_child.add(wsman, 'Selector', 'ManagedSystem')
    g_g_grand_child.attr_add(wsman, 'Name', 'Name')
    return doc


def _set_power_state(node, target_state):
    """Set power state of the AMT Client.

    :param node: a node object.
    :param target_state: desired power state.
    :raises: AMTFailure
    :raises: AMTConnectFailure
    """
    amt_common.awake_amt_interface(node)
    client = amt_common.get_wsman_client(node)

    method = 'RequestPowerStateChange'
    options = pywsman.ClientOptions()
    options.add_selector('Name', 'Intel(r) AMT Power Management Service')

    doc = _generate_power_action_input(AMT_POWER_MAP[target_state])
    try:
        client.wsman_invoke(options, resource_uris.CIM_PowerManagementService,
                            method, doc)
    except (exception.AMTFailure, exception.AMTConnectFailure) as e:
        with excutils.save_and_reraise_exception():
            LOG.exception(_LE("Failed to set power state %(state)s for "
                              "node %(node_id)s with error: %(error)s."),
                          {'state': target_state, 'node_id': node.uuid,
                           'error': e})
    else:
        LOG.info(_LI("Power state set to %(state)s for node %(node_id)s"),
                 {'state': target_state, 'node_id': node.uuid})


def _power_status(node):
    """Get the power status for a node.

    :param node: a node object.
    :returns: one of ironic.common.states POWER_OFF, POWER_ON or ERROR.
    :raises: AMTFailure.
    :raises: AMTConnectFailure.
    """
    amt_common.awake_amt_interface(node)
    client = amt_common.get_wsman_client(node)
    namespace = resource_uris.CIM_AssociatedPowerManagementService
    try:
        doc = client.wsman_get(namespace)
    except (exception.AMTFailure, exception.AMTConnectFailure) as e:
        with excutils.save_and_reraise_exception():
            LOG.exception(_LE("Failed to get power state for node %(node_id)s "
                              "with error: %(error)s."),
                          {'node_id': node.uuid, 'error': e})

    item = "PowerState"
    power_state = amt_common.xml_find(doc, namespace, item).text
    for state in AMT_POWER_MAP:
        if power_state == AMT_POWER_MAP[state]:
            return state
    return states.ERROR


def _set_and_wait(task, target_state):
    """Helper function for DynamicLoopingCall.

    This method changes the power state and polls AMT until the desired
    power state is reached.

    :param task: a TaskManager instance contains the target node.
    :param target_state: desired power state.
    :returns: one of ironic.common.states.
    :raises: PowerStateFailure if cannot set the node to target_state.
    :raises: AMTFailure.
    :raises: AMTConnectFailure
    :raises: InvalidParameterValue
    """
    node = task.node
    driver = task.driver
    if target_state not in (states.POWER_ON, states.POWER_OFF):
        raise exception.InvalidParameterValue(_('Unsupported target_state: %s')
                                              % target_state)
    elif target_state == states.POWER_ON:
        boot_device = node.driver_internal_info.get('amt_boot_device')
        if boot_device and boot_device != amt_common.DEFAULT_BOOT_DEVICE:
            driver.management.ensure_next_boot_device(node, boot_device)

    def _wait(status):
        status['power'] = _power_status(node)
        if status['power'] == target_state:
            raise loopingcall.LoopingCallDone()

        if status['iter'] >= CONF.amt.max_attempts:
            status['power'] = states.ERROR
            LOG.warning(_LW("AMT failed to set power state %(state)s after "
                            "%(tries)s retries on node %(node_id)s."),
                        {'state': target_state, 'tries': status['iter'],
                         'node_id': node.uuid})
            raise loopingcall.LoopingCallDone()

        try:
            _set_power_state(node, target_state)
        except Exception:
            # Log failures but keep trying
            LOG.warning(_LW("AMT set power state %(state)s for node %(node)s "
                            "- Attempt %(attempt)s times of %(max_attempt)s "
                            "failed."),
                        {'state': target_state, 'node': node.uuid,
                         'attempt': status['iter'] + 1,
                         'max_attempt': CONF.amt.max_attempts})
        status['iter'] += 1

    status = {'power': None, 'iter': 0}

    timer = loopingcall.FixedIntervalLoopingCall(_wait, status)
    timer.start(interval=CONF.amt.action_wait).wait()

    if status['power'] != target_state:
        raise exception.PowerStateFailure(pstate=target_state)

    return status['power']


class AMTPower(base.PowerInterface):
    """AMT Power interface.

    This Power interface control the power of node by providing power on/off
    and reset functions.
    """

    def get_properties(self):
        return copy.deepcopy(amt_common.COMMON_PROPERTIES)

    def validate(self, task):
        """Validate the driver_info in the node.

        Check if the driver_info contains correct required fields

        :param task: a TaskManager instance contains the target node.
        :raises: MissingParameterValue if any required parameters are missing.
        :raises: InvalidParameterValue if any parameters have invalid values.
        """
        # FIXME(lintan): validate hangs if unable to reach AMT, so dont
        # connect to the node until bug 1314961 is resolved.
        amt_common.parse_driver_info(task.node)

    def get_power_state(self, task):
        """Get the power state from the node.

        :param task: a TaskManager instance contains the target node.
        :raises: AMTFailure.
        :raises: AMTConnectFailure.
        """
        return _power_status(task.node)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, pstate):
        """Set the power state of the node.

        Turn the node power on or off.

        :param task: a TaskManager instance contains the target node.
        :param pstate: The desired power state of the node.
        :raises: PowerStateFailure if the power cannot set to pstate.
        :raises: AMTFailure.
        :raises: AMTConnectFailure.
        :raises: InvalidParameterValue
        """
        _set_and_wait(task, pstate)

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Cycle the power of the node

        :param task: a TaskManager instance contains the target node.
        :raises: PowerStateFailure if failed to reboot.
        :raises: AMTFailure.
        :raises: AMTConnectFailure.
        :raises: InvalidParameterValue
        """
        _set_and_wait(task, states.POWER_OFF)
        _set_and_wait(task, states.POWER_ON)
