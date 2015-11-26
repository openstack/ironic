# coding=utf-8

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

from oslo_log import log
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.conductor import task_manager

LOG = log.getLogger(__name__)

CLEANING_INTERFACE_PRIORITY = {
    # When two clean steps have the same priority, their order is determined
    # by which interface is implementing the clean step. The clean step of the
    # interface with the highest value here, will be executed first in that
    # case.
    'power': 4,
    'management': 3,
    'deploy': 2,
    'raid': 1,
}


@task_manager.require_exclusive_lock
def node_set_boot_device(task, device, persistent=False):
    """Set the boot device for a node.

    :param task: a TaskManager instance.
    :param device: Boot device. Values are vendor-specific.
    :param persistent: Whether to set next-boot, or make the change
        permanent. Default: False.
    :raises: InvalidParameterValue if the validation of the
        ManagementInterface fails.

    """
    if getattr(task.driver, 'management', None):
        task.driver.management.validate(task)
        task.driver.management.set_boot_device(task,
                                               device=device,
                                               persistent=persistent)


@task_manager.require_exclusive_lock
def node_power_action(task, new_state):
    """Change power state or reset for a node.

    Perform the requested power action if the transition is required.

    :param task: a TaskManager instance containing the node to act on.
    :param new_state: Any power state from ironic.common.states. If the
        state is 'REBOOT' then a reboot will be attempted, otherwise
        the node power state is directly set to 'state'.
    :raises: InvalidParameterValue when the wrong state is specified
             or the wrong driver info is specified.
    :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.

    """
    node = task.node
    target_state = states.POWER_ON if new_state == states.REBOOT else new_state

    if new_state != states.REBOOT:
        try:
            curr_state = task.driver.power.get_power_state(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                node['last_error'] = _(
                    "Failed to change power state to '%(target)s'. "
                    "Error: %(error)s") % {'target': new_state, 'error': e}
                node['target_power_state'] = states.NOSTATE
                node.save()

        if curr_state == new_state:
            # Neither the ironic service nor the hardware has erred. The
            # node is, for some reason, already in the requested state,
            # though we don't know why. eg, perhaps the user previously
            # requested the node POWER_ON, the network delayed those IPMI
            # packets, and they are trying again -- but the node finally
            # responds to the first request, and so the second request
            # gets to this check and stops.
            # This isn't an error, so we'll clear last_error field
            # (from previous operation), log a warning, and return.
            node['last_error'] = None
            # NOTE(dtantsur): under rare conditions we can get out of sync here
            node['power_state'] = new_state
            node['target_power_state'] = states.NOSTATE
            node.save()
            LOG.warning(_LW("Not going to change node power state because "
                            "current state = requested state = '%(state)s'."),
                        {'state': curr_state})
            return

        if curr_state == states.ERROR:
            # be optimistic and continue action
            LOG.warning(_LW("Driver returns ERROR power state for node %s."),
                        node.uuid)

    # Set the target_power_state and clear any last_error, if we're
    # starting a new operation. This will expose to other processes
    # and clients that work is in progress.
    if node['target_power_state'] != target_state:
        node['target_power_state'] = target_state
        node['last_error'] = None
        node.save()

    # take power action
    try:
        if new_state != states.REBOOT:
            task.driver.power.set_power_state(task, new_state)
        else:
            task.driver.power.reboot(task)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            node['last_error'] = _(
                "Failed to change power state to '%(target)s'. "
                "Error: %(error)s") % {'target': target_state, 'error': e}
    else:
        # success!
        node['power_state'] = target_state
        LOG.info(_LI('Successfully set node %(node)s power state to '
                     '%(state)s.'),
                 {'node': node.uuid, 'state': target_state})
    finally:
        node['target_power_state'] = states.NOSTATE
        node.save()


@task_manager.require_exclusive_lock
def cleanup_after_timeout(task):
    """Cleanup deploy task after timeout.

    :param task: a TaskManager instance.
    """
    node = task.node
    msg = (_('Timeout reached while waiting for callback for node %s')
           % node.uuid)
    node.last_error = msg
    LOG.error(msg)
    node.save()

    error_msg = _('Cleanup failed for node %(node)s after deploy timeout: '
                  ' %(error)s')
    try:
        task.driver.deploy.clean_up(task)
    except Exception as e:
        msg = error_msg % {'node': node.uuid, 'error': e}
        LOG.error(msg)
        if isinstance(e, exception.IronicException):
            node.last_error = msg
        else:
            node.last_error = _('Deploy timed out, but an unhandled '
                                'exception was encountered while aborting. '
                                'More info may be found in the log file.')
        node.save()


def provisioning_error_handler(e, node, provision_state,
                               target_provision_state):
    """Set the node's provisioning states if error occurs.

    This hook gets called upon an exception being raised when spawning
    the worker to do the deployment or tear down of a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param provision_state: the provision state to be set on
        the node.
    :param target_provision_state: the target provision state to be
        set on the node.

    """
    if isinstance(e, exception.NoFreeConductorWorker):
        # NOTE(deva): there is no need to clear conductor_affinity
        #             because it isn't updated on a failed deploy
        node.provision_state = provision_state
        node.target_provision_state = target_provision_state
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning(_LW("No free conductor workers available to perform "
                        "an action on node %(node)s, setting node's "
                        "provision_state back to %(prov_state)s and "
                        "target_provision_state to %(tgt_prov_state)s."),
                    {'node': node.uuid, 'prov_state': provision_state,
                     'tgt_prov_state': target_provision_state})


def cleaning_error_handler(task, msg, tear_down_cleaning=True,
                           set_fail_state=True):
    """Put a failed node in CLEANFAIL or ZAPFAIL and maintenance."""
    # Reset clean step, msg should include current step
    if task.node.provision_state in (states.CLEANING, states.CLEANWAIT):
        task.node.clean_step = {}
    task.node.last_error = msg
    task.node.maintenance = True
    task.node.maintenance_reason = msg
    task.node.save()
    if tear_down_cleaning:
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
            msg = (_LE('Failed to tear down cleaning on node %(uuid)s, '
                       'reason: %(err)s'), {'err': e, 'uuid': task.node.uuid})
            LOG.exception(msg)

    if set_fail_state:
        task.process_event('fail')


def power_state_error_handler(e, node, power_state):
    """Set the node's power states if error occurs.

    This hook gets called upon an exception being raised when spawning
    the worker thread to change the power state of a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param power_state: the power state to set on the node.

    """
    if isinstance(e, exception.NoFreeConductorWorker):
        node.power_state = power_state
        node.target_power_state = states.NOSTATE
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning(_LW("No free conductor workers available to perform "
                        "an action on node %(node)s, setting node's "
                        "power state back to %(power_state)s."),
                    {'node': node.uuid, 'power_state': power_state})


def _step_key(step):
    """Sort by priority, then interface priority in event of tie.

    :param step: cleaning step dict to get priority for.
    """
    return (step.get('priority'),
            CLEANING_INTERFACE_PRIORITY[step.get('interface')])


def _get_cleaning_steps(task, enabled=False):
    """Get sorted cleaning steps for task.node

    :param task: A TaskManager object
    :param enabled: If True, returns only enabled (priority > 0) steps. If
        False, returns all clean steps.
    :returns: A list of clean steps dictionaries, sorted with largest priority
        as the first item
    """
    # Iterate interfaces and get clean steps from each
    steps = list()
    for interface in CLEANING_INTERFACE_PRIORITY:
        interface = getattr(task.driver, interface)
        if interface:
            interface_steps = [x for x in interface.get_clean_steps(task)
                               if not enabled or x['priority'] > 0]
            steps.extend(interface_steps)
    # Sort the steps from higher priority to lower priority
    return sorted(steps, key=_step_key, reverse=True)


def set_node_cleaning_steps(task):
    """Get the list of clean steps, save them to the node."""
    # Get the prioritized steps, store them.
    node = task.node
    driver_internal_info = node.driver_internal_info
    driver_internal_info['clean_steps'] = _get_cleaning_steps(task,
                                                              enabled=True)
    node.driver_internal_info = driver_internal_info
    node.clean_step = {}
    node.save()
