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
from ironic.common.i18n import _, _LE, _LI, _LW
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

    Sets the boot device for a node if the node's driver interface
    contains a 'management' interface.

    If the node that the boot device change is being requested for
    is in ADOPTING state, the boot device will not be set as that
    change could potentially result in the future running state of
    an adopted node being modified erroneously.

    :param task: a TaskManager instance.
    :param device: Boot device. Values are vendor-specific.
    :param persistent: Whether to set next-boot, or make the change
        permanent. Default: False.
    :raises: InvalidParameterValue if the validation of the
        ManagementInterface fails.

    """
    if getattr(task.driver, 'management', None):
        task.driver.management.validate(task)
        if task.node.provision_state != states.ADOPTING:
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
            LOG.warning(_LW("Not going to change node %(node)s power "
                            "state because current state = requested state "
                            "= '%(state)s'."),
                        {'node': node.uuid, 'state': curr_state})
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
    the worker to do some provisioning to a node like deployment, tear down,
    or cleaning.

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


def cleanup_cleanwait_timeout(task):
    """Cleanup a cleaning task after timeout.

    :param task: a TaskManager instance.
    """
    last_error = (_("Timeout reached while cleaning the node. Please "
                    "check if the ramdisk responsible for the cleaning is "
                    "running on the node. Failed on step %(step)s.") %
                  {'step': task.node.clean_step})
    cleaning_error_handler(task, msg=last_error,
                           set_fail_state=True)


def cleaning_error_handler(task, msg, tear_down_cleaning=True,
                           set_fail_state=True):
    """Put a failed node in CLEANFAIL and maintenance."""
    node = task.node
    if node.provision_state in (
            states.CLEANING,
            states.CLEANWAIT,
            states.CLEANFAIL):
        # Clear clean step, msg should already include current step
        node.clean_step = {}
        info = node.driver_internal_info
        info.pop('clean_step_index', None)
        # Clear any leftover metadata about cleaning reboots
        info.pop('cleaning_reboot', None)
        node.driver_internal_info = info
    # For manual cleaning, the target provision state is MANAGEABLE, whereas
    # for automated cleaning, it is AVAILABLE.
    manual_clean = node.target_provision_state == states.MANAGEABLE
    node.last_error = msg
    node.maintenance = True
    node.maintenance_reason = msg
    node.save()
    if tear_down_cleaning:
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
            msg = (_LE('Failed to tear down cleaning on node %(uuid)s, '
                       'reason: %(err)s'), {'err': e, 'uuid': node.uuid})
            LOG.exception(msg)

    if set_fail_state:
        target_state = states.MANAGEABLE if manual_clean else None
        task.process_event('fail', target_state=target_state)


def spawn_cleaning_error_handler(e, node):
    """Handle spawning error for node cleaning."""
    if isinstance(e, exception.NoFreeConductorWorker):
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning(_LW("No free conductor workers available to perform "
                        "cleaning on node %(node)s"), {'node': node.uuid})


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


def _get_cleaning_steps(task, enabled=False, sort=True):
    """Get cleaning steps for task.node.

    :param task: A TaskManager object
    :param enabled: If True, returns only enabled (priority > 0) steps. If
        False, returns all clean steps.
    :param sort: If True, the steps are sorted from highest priority to lowest
        priority. For steps having the same priority, they are sorted from
        highest interface priority to lowest.
    :raises: NodeCleaningFailure if there was a problem getting the
        clean steps.
    :returns: A list of clean step dictionaries
    """
    # Iterate interfaces and get clean steps from each
    steps = list()
    for interface in CLEANING_INTERFACE_PRIORITY:
        interface = getattr(task.driver, interface)
        if interface:
            interface_steps = [x for x in interface.get_clean_steps(task)
                               if not enabled or x['priority'] > 0]
            steps.extend(interface_steps)
    if sort:
        # Sort the steps from higher priority to lower priority
        steps = sorted(steps, key=_step_key, reverse=True)
    return steps


def set_node_cleaning_steps(task):
    """Set up the node with clean step information for cleaning.

    For automated cleaning, get the clean steps from the driver.
    For manual cleaning, the user's clean steps are known but need to be
    validated against the driver's clean steps.

    :raises: InvalidParameterValue if there is a problem with the user's
             clean steps.
    :raises: NodeCleaningFailure if there was a problem getting the
             clean steps.
    """
    node = task.node
    driver_internal_info = node.driver_internal_info

    # For manual cleaning, the target provision state is MANAGEABLE, whereas
    # for automated cleaning, it is AVAILABLE.
    manual_clean = node.target_provision_state == states.MANAGEABLE

    if not manual_clean:
        # Get the prioritized steps for automated cleaning
        driver_internal_info['clean_steps'] = _get_cleaning_steps(task,
                                                                  enabled=True)
    else:
        # For manual cleaning, the list of cleaning steps was specified by the
        # user and already saved in node.driver_internal_info['clean_steps'].
        # Now that we know what the driver's available clean steps are, we can
        # do further checks to validate the user's clean steps.
        steps = node.driver_internal_info['clean_steps']
        _validate_user_clean_steps(task, steps)

    node.clean_step = {}
    driver_internal_info['clean_step_index'] = None
    node.driver_internal_info = driver_internal_info
    node.save()


def _validate_user_clean_steps(task, user_steps):
    """Validate the user-specified clean steps.

    :param task: A TaskManager object
    :param user_steps: a list of clean steps. A clean step is a dictionary
        with required keys 'interface' and 'step', and optional key 'args'::

              { 'interface': <driver_interface>,
                'step': <name_of_clean_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>} }

            For example::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }
    :raises: InvalidParameterValue if validation of clean steps fails.
    :raises: NodeCleaningFailure if there was a problem getting the
        clean steps from the driver.
    """

    def step_id(step):
        return '.'.join([step['step'], step['interface']])

    errors = []

    # The clean steps from the driver. A clean step dictionary is of the form:
    #   { 'interface': <driver_interface>,
    #      'step': <name_of_clean_step>,
    #      'priority': <integer>
    #      'abortable': Optional. <Boolean>.
    #      'argsinfo': Optional. A dictionary of {<arg_name>:<arg_info_dict>}
    #                  entries. <arg_info_dict> is a dictionary with
    #                  { 'description': <description>,
    #                    'required': <Boolean> }
    #   }
    driver_steps = {}
    for s in _get_cleaning_steps(task, enabled=False, sort=False):
        driver_steps[step_id(s)] = s

    for user_step in user_steps:
        # Check if this user_specified clean step isn't supported by the driver
        try:
            driver_step = driver_steps[step_id(user_step)]
        except KeyError:
            error = (_('node does not support this clean step: %(step)s')
                     % {'step': user_step})
            errors.append(error)
            continue

        # Check that the user-specified arguments are valid
        argsinfo = driver_step.get('argsinfo') or {}
        user_args = user_step.get('args') or {}
        invalid = set(user_args) - set(argsinfo)
        if invalid:
            error = _('clean step %(step)s has these invalid arguments: '
                      '%(invalid)s') % {'step': user_step,
                                        'invalid': ', '.join(invalid)}
            errors.append(error)

        # Check that all required arguments were specified by the user
        missing = []
        for (arg_name, arg_info) in argsinfo.items():
            if arg_info.get('required', False) and arg_name not in user_args:
                msg = arg_name
                if arg_info.get('description'):
                    msg += ' (%(desc)s)' % {'desc': arg_info['description']}
                missing.append(msg)
        if missing:
            error = _('clean step %(step)s is missing these required keyword '
                      'arguments: %(miss)s') % {'step': user_step,
                                                'miss': ', '.join(missing)}
            errors.append(error)

    if errors:
        raise exception.InvalidParameterValue('; '.join(errors))
