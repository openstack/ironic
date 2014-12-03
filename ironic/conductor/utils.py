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

from oslo.utils import excutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.conductor import task_manager
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


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
            node['target_power_state'] = states.NOSTATE
            node.save()
            LOG.warn(_LW("Not going to change_node_power_state because "
                         "current state = requested state = '%(state)s'."),
                     {'state': curr_state})
            return

        if curr_state == states.ERROR:
            # be optimistic and continue action
            LOG.warn(_LW("Driver returns ERROR power state for node %s."),
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
        LOG.info(_LI('Succesfully set node %(node)s power state to '
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
    task.process_event('fail')
    msg = (_('Timeout reached while waiting for callback for node %s')
             % node.uuid)
    node.last_error = msg
    LOG.error(msg)
    node.save()

    error_msg = _('Cleanup failed for node %(node)s after deploy timeout: '
                  ' %(error)s')
    try:
        task.driver.deploy.clean_up(task)
    except exception.IronicException as e:
        msg = error_msg % {'node': node.uuid, 'error': e}
        LOG.error(msg)
        node.last_error = msg
        node.save()
    except Exception as e:
        msg = error_msg % {'node': node.uuid, 'error': e}
        LOG.error(msg)
        node.last_error = _('Deploy timed out, but an unhandled exception was '
                            'encountered while aborting. More info may be '
                            'found in the log file.')
        node.save()
