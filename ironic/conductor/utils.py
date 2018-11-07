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

from oslo_config import cfg
from oslo_log import log
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import reflection

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import network
from ironic.common import states
from ironic.conductor import notification_utils as notify_utils
from ironic.conductor import task_manager
from ironic.objects import fields

LOG = log.getLogger(__name__)
CONF = cfg.CONF

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


def node_wait_for_power_state(task, new_state, timeout=None):
    """Wait for node to be in new power state.

    :param task: a TaskManager instance.
    :param new_state: the desired new power state, one of the power states
        in :mod:`ironic.common.states`.
    :param timeout: number of seconds to wait before giving up. If not
        specified, uses the conductor.power_state_change_timeout config value.
    :raises: PowerStateFailure if timed out
    """
    retry_timeout = (timeout or CONF.conductor.power_state_change_timeout)

    def _wait():
        status = task.driver.power.get_power_state(task)
        if status == new_state:
            raise loopingcall.LoopingCallDone(retvalue=status)
        # NOTE(sambetts): Return False to trigger BackOffLoopingCall to start
        # backing off.
        return False

    try:
        timer = loopingcall.BackOffLoopingCall(_wait)
        return timer.start(initial_delay=1, timeout=retry_timeout).wait()
    except loopingcall.LoopingCallTimeOut:
        LOG.error('Timed out after %(retry_timeout)s secs waiting for power '
                  '%(state)s on node %(node_id)s.',
                  {'retry_timeout': retry_timeout,
                   'state': new_state, 'node_id': task.node.uuid})
        raise exception.PowerStateFailure(pstate=new_state)


def _calculate_target_state(new_state):
    if new_state in (states.POWER_ON, states.REBOOT, states.SOFT_REBOOT):
        target_state = states.POWER_ON
    elif new_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
        target_state = states.POWER_OFF
    else:
        target_state = None
    return target_state


def _can_skip_state_change(task, new_state):
    """Check if we can ignore the power state change request for the node.

    Check if we should ignore the requested power state change. This can occur
    if the requested power state is already the same as our current state. This
    only works for power on and power off state changes. More complex power
    state changes, like reboot, are not skipped.

    :param task: a TaskManager instance containing the node to act on.
    :param new_state: The requested power state to change to. This can be any
                      power state from ironic.common.states.
    :returns: True if should ignore the requested power state change. False
              otherwise
    """
    # We only ignore certain state changes. So if the desired new_state is not
    # one of them, then we can return early and not do an un-needed
    # get_power_state() call
    if new_state not in (states.POWER_ON, states.POWER_OFF,
                         states.SOFT_POWER_OFF):
        return False

    node = task.node

    def _not_going_to_change():
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
        node['power_state'] = curr_state
        node['target_power_state'] = states.NOSTATE
        node.save()
        notify_utils.emit_power_set_notification(
            task, fields.NotificationLevel.INFO,
            fields.NotificationStatus.END, new_state)
        LOG.warning("Not going to change node %(node)s power state because "
                    "current state = requested state = '%(state)s'.",
                    {'node': node.uuid, 'state': curr_state})

    try:
        curr_state = task.driver.power.get_power_state(task)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            node['last_error'] = _(
                "Failed to change power state to '%(target)s'. "
                "Error: %(error)s") % {'target': new_state, 'error': e}
            node['target_power_state'] = states.NOSTATE
            node.save()
            notify_utils.emit_power_set_notification(
                task, fields.NotificationLevel.ERROR,
                fields.NotificationStatus.ERROR, new_state)

    if curr_state == states.POWER_ON:
        if new_state == states.POWER_ON:
            _not_going_to_change()
            return True
    elif curr_state == states.POWER_OFF:
        if new_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
            _not_going_to_change()
            return True
    else:
        # if curr_state == states.ERROR:
        # be optimistic and continue action
        LOG.warning("Driver returns ERROR power state for node %s.",
                    node.uuid)
    return False


@task_manager.require_exclusive_lock
def node_power_action(task, new_state, timeout=None):
    """Change power state or reset for a node.

    Perform the requested power action if the transition is required.

    :param task: a TaskManager instance containing the node to act on.
    :param new_state: Any power state from ironic.common.states.
    :param timeout: timeout (in seconds) positive integer (> 0) for any
      power state. ``None`` indicates to use default timeout.
    :raises: InvalidParameterValue when the wrong state is specified
             or the wrong driver info is specified.
    :raises: StorageError when a failure occurs updating the node's
             storage interface upon setting power on.
    :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.

    """
    notify_utils.emit_power_set_notification(
        task, fields.NotificationLevel.INFO, fields.NotificationStatus.START,
        new_state)
    node = task.node

    if _can_skip_state_change(task, new_state):
        return
    target_state = _calculate_target_state(new_state)

    # Set the target_power_state and clear any last_error, if we're
    # starting a new operation. This will expose to other processes
    # and clients that work is in progress.
    if node['target_power_state'] != target_state:
        node['target_power_state'] = target_state
        node['last_error'] = None
        node.save()

    # take power action
    try:
        if (target_state == states.POWER_ON and
                node.provision_state == states.ACTIVE):
            task.driver.storage.attach_volumes(task)

        if new_state != states.REBOOT:
            if ('timeout' in reflection.get_signature(
                    task.driver.power.set_power_state).parameters):
                task.driver.power.set_power_state(task, new_state,
                                                  timeout=timeout)
            else:
                # FIXME(naohirot):
                # After driver composition, we should print power interface
                # name here instead of driver.
                LOG.warning(
                    "The set_power_state method of %(driver_name)s "
                    "doesn't support 'timeout' parameter.",
                    {'driver_name': node.driver})
                task.driver.power.set_power_state(task, new_state)

        else:
            # TODO(TheJulia): We likely ought to consider toggling
            # volume attachments, although we have no mechanism to
            # really verify what cinder has connector wise.
            if ('timeout' in reflection.get_signature(
                    task.driver.power.reboot).parameters):
                task.driver.power.reboot(task, timeout=timeout)
            else:
                LOG.warning("The reboot method of %(driver_name)s "
                            "doesn't support 'timeout' parameter.",
                            {'driver_name': node.driver})
                task.driver.power.reboot(task)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            node['target_power_state'] = states.NOSTATE
            node['last_error'] = _(
                "Failed to change power state to '%(target_state)s' "
                "by '%(new_state)s'. Error: %(error)s") % {
                    'target_state': target_state,
                    'new_state': new_state,
                    'error': e}
            node.save()
            notify_utils.emit_power_set_notification(
                task, fields.NotificationLevel.ERROR,
                fields.NotificationStatus.ERROR, new_state)
    else:
        # success!
        node['power_state'] = target_state
        node['target_power_state'] = states.NOSTATE
        node.save()
        notify_utils.emit_power_set_notification(
            task, fields.NotificationLevel.INFO, fields.NotificationStatus.END,
            new_state)
        LOG.info('Successfully set node %(node)s power state to '
                 '%(target_state)s by %(new_state)s.',
                 {'node': node.uuid,
                  'target_state': target_state,
                  'new_state': new_state})
        # NOTE(TheJulia): Similarly to power-on, when we power-off
        # a node, we should detach any volume attachments.
        if (target_state == states.POWER_OFF and
                node.provision_state == states.ACTIVE):
            try:
                task.driver.storage.detach_volumes(task)
            except exception.StorageError as e:
                LOG.warning("Volume detachment for node %(node)s "
                            "failed. Error: %(error)s",
                            {'node': node.uuid, 'error': e})


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
        LOG.warning("No free conductor workers available to perform "
                    "an action on node %(node)s, setting node's "
                    "provision_state back to %(prov_state)s and "
                    "target_provision_state to %(tgt_prov_state)s.",
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
    # NOTE(rloo): this is called from the periodic task for cleanwait timeouts,
    # via the task manager's process_event(). The node has already been moved
    # to CLEANFAIL, so the error handler doesn't need to set the fail state.
    cleaning_error_handler(task, msg=last_error, set_fail_state=False)


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
            msg = ('Failed to tear down cleaning on node %(uuid)s, '
                   'reason: %(err)s' % {'err': e, 'uuid': node.uuid})
            LOG.exception(msg)

    if set_fail_state and node.provision_state != states.CLEANFAIL:
        target_state = states.MANAGEABLE if manual_clean else None
        task.process_event('fail', target_state=target_state)


def spawn_cleaning_error_handler(e, node):
    """Handle spawning error for node cleaning."""
    if isinstance(e, exception.NoFreeConductorWorker):
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning("No free conductor workers available to perform "
                    "cleaning on node %(node)s", {'node': node.uuid})


def power_state_error_handler(e, node, power_state):
    """Set the node's power states if error occurs.

    This hook gets called upon an exception being raised when spawning
    the worker thread to change the power state of a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param power_state: the power state to set on the node.

    """
    # NOTE This error will not emit a power state change notification since
    # this is related to spawning the worker thread, not the power state change
    # itself.
    if isinstance(e, exception.NoFreeConductorWorker):
        node.power_state = power_state
        node.target_power_state = states.NOSTATE
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning("No free conductor workers available to perform "
                    "an action on node %(node)s, setting node's "
                    "power state back to %(power_state)s.",
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
        driver_internal_info['clean_steps'] = (
            _validate_user_clean_steps(task, steps))

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
    :return: validated clean steps update with information from the driver
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

    result = []
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

        # Copy fields that should not be provided by a user
        user_step['abortable'] = driver_step.get('abortable', False)
        user_step['priority'] = driver_step.get('priority', 0)
        result.append(user_step)

    if errors:
        raise exception.InvalidParameterValue('; '.join(errors))
    return result


@task_manager.require_exclusive_lock
def validate_port_physnet(task, port_obj):
    """Validate the consistency of physical networks of ports in a portgroup.

    Validate the consistency of a port's physical network with other ports in
    the same portgroup.  All ports in a portgroup should have the same value
    (which may be None) for their physical_network field.

    During creation or update of a port in a portgroup we apply the
    following validation criteria:

    - If the portgroup has existing ports with different physical networks, we
      raise PortgroupPhysnetInconsistent. This shouldn't ever happen.
    - If the port has a physical network that is inconsistent with other
      ports in the portgroup, we raise exception.Conflict.

    If a port's physical network is None, this indicates that ironic's VIF
    attachment mapping algorithm should operate in a legacy (physical
    network unaware) mode for this port or portgroup. This allows existing
    ironic nodes to continue to function after an upgrade to a release
    including physical network support.

    :param task: a TaskManager instance
    :param port_obj: a port object to be validated.
    :raises: Conflict if the port is a member of a portgroup which is on a
             different physical network.
    :raises: PortgroupPhysnetInconsistent if the port's portgroup has
             ports which are not all assigned the same physical network.
    """
    if 'portgroup_id' not in port_obj or not port_obj.portgroup_id:
        return

    delta = port_obj.obj_what_changed()
    # We can skip this step if the port's portgroup membership or physical
    # network assignment is not being changed (during creation these will
    # appear changed).
    if not (delta & {'portgroup_id', 'physical_network'}):
        return

    # Determine the current physical network of the portgroup.
    pg_physnets = network.get_physnets_by_portgroup_id(task,
                                                       port_obj.portgroup_id,
                                                       exclude_port=port_obj)

    if not pg_physnets:
        return

    # Check that the port has the same physical network as any existing
    # member ports.
    pg_physnet = pg_physnets.pop()
    port_physnet = (port_obj.physical_network
                    if 'physical_network' in port_obj else None)
    if port_physnet != pg_physnet:
        portgroup = network.get_portgroup_by_id(task, port_obj.portgroup_id)
        msg = _("Port with physical network %(physnet)s cannot become a "
                "member of port group %(portgroup)s which has ports in "
                "physical network %(pg_physnet)s.")
        raise exception.Conflict(
            msg % {'portgroup': portgroup.uuid, 'physnet': port_physnet,
                   'pg_physnet': pg_physnet})
