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

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.openstack.common import excutils
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


@task_manager.require_exclusive_lock
def node_set_boot_device(task, node, device, persistent=False):
    """Set the boot device for a node.

    :param task: a TaskManager instance.
    :param node: The Node.
    :param device: Boot device. Values are vendor-specific.
    :param persistent: Whether to set next-boot, or make the change
        permanent. Default: False.

    """
    try:
        task.driver.vendor.vendor_passthru(task, node,
                                           device=device,
                                           persistent=persistent,
                                           method='set_boot_device')
    except exception.UnsupportedDriverExtension:
        # NOTE(deva): Some drivers, like SSH, do not support set_boot_device.
        #             This is not a fatal exception.
        pass


@task_manager.require_exclusive_lock
def node_power_action(task, node, state):
    """Change power state or reset for a node.

    Validate whether the given power transition is possible and perform
    power action.

    :param task: a TaskManager instance.
    :param node: the Node object to act upon.
    :param state: Any power state from ironic.common.states. If the
        state is 'REBOOT' then a reboot will be attempted, otherwise
        the node power state is directly set to 'state'.
    :raises: InvalidParameterValue when the wrong state is specified
             or the wrong driver info is specified.
    :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.

    """
    context = task.context
    new_state = states.POWER_ON if state == states.REBOOT else state
    try:
        task.driver.power.validate(task, node)
        if state != states.REBOOT:
            curr_state = task.driver.power.get_power_state(task, node)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            node['last_error'] = \
                 _("Failed to change power state to '%(target)s'. "
                   "Error: %(error)s") % {
                     'target': new_state, 'error': e}
            node.save(context)

    if state != states.REBOOT and curr_state == new_state:
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
        node.save(context)
        LOG.warn(_("Not going to change_node_power_state because "
                    "current state = requested state = '%(state)s'.")
                    % {'state': curr_state})
        return

    # Set the target_power_state and clear any last_error, since we're
    # starting a new operation. This will expose to other processes
    # and clients that work is in progress.
    node['target_power_state'] = new_state
    node['last_error'] = None
    node.save(context)

    # take power action
    try:
        if state != states.REBOOT:
            task.driver.power.set_power_state(task, node, new_state)
        else:
            task.driver.power.reboot(task, node)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            node['last_error'] = \
                _("Failed to change power state to '%(target)s'. "
                  "Error: %(error)s") % {
                    'target': new_state, 'error': e}
    else:
        # success!
        node['power_state'] = new_state
    finally:
        node['target_power_state'] = states.NOSTATE
        node.save(context)


@task_manager.require_exclusive_lock
def cleanup_after_timeout(task):
    """Cleanup deploy task after timeout.

    :param task: a TaskManager instance.
    """
    node = task.node
    context = task.context
    error_msg = _('Cleanup failed for node %(node)s after deploy timeout: '
                  ' %(error)s')
    try:
        task.driver.deploy.clean_up(task, node)
    except exception.IronicException as e:
        msg = error_msg % {'node': node.uuid, 'error': e}
        LOG.error(msg)
        node.last_error = msg
        node.save(context)
    except Exception as e:
        msg = error_msg % {'node': node.uuid, 'error': e}
        LOG.error(msg)
        node.last_error = _('Deploy timed out, but an unhandled exception was '
                            'encountered while aborting. More info may be '
                            'found in the log file.')
        node.save(context)
