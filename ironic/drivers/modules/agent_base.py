# -*- coding: utf-8 -*-
#
# Copyright 2014 Rackspace, Inc.
# Copyright 2015 Red Hat, Inc.
# All Rights Reserved.
#
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

import collections

from oslo_log import log

from ironic.common import async_steps
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import metrics_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import cleaning
from ironic.conductor import deployments
from ironic.conductor import servicing
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic.drivers import utils as driver_utils
from ironic import objects

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

# This contains a nested dictionary containing the post clean/deploy step hooks
# registered for each clean/deploy step of every interface.
# Every key is an interface and its value is a dictionary. For this inner
# dictionary, the key is the name of the clean-/deploy-step method in the
# interface, and the value is the post clean-/deploy-step hook -- the function
# that is to be called after successful completion of the clean/deploy step.
#
# For example:
# _POST_STEP_HOOKS = {
#   {'clean':
#    {
#     'raid': {'create_configuration': <post-create function>,
#              'delete_configuration': <post-delete function>}
#    }
#  }
#
# It means that method '<post-create function>' is to be called after
# successfully completing the clean step 'create_configuration' of
# raid interface. '<post-delete function>' is to be called after
# completing 'delete_configuration' of raid interface.
_POST_STEP_HOOKS = {'clean': {}, 'deploy': {}}

VENDOR_PROPERTIES = {
    'deploy_forces_oob_reboot': _(
        'Whether Ironic should force a reboot of the Node via the out-of-band '
        'channel after deployment is complete. Provides compatibility with '
        'older deploy ramdisks. Defaults to False. Optional.'),
    'agent_verify_ca': _(
        'Either a Boolean value, a path to a CA_BUNDLE file or directory with '
        'certificates of trusted CAs. If set to True ironic will verify '
        'the agent\'s certificate; if False the driver will ignore verifying '
        'the SSL certificate. If it\'s a path the driver will use the '
        'specified certificate or one of the certificates in the '
        'directory. Defaults to True. Optional'),
}

__HEARTBEAT_RECORD_ONLY = (states.ENROLL, states.MANAGEABLE, states.AVAILABLE,
                           states.CLEANING, states.DEPLOYING, states.RESCUING,
                           states.DEPLOYHOLD, states.CLEANHOLD,
                           states.SERVICING, states.SERVICEHOLD)
_HEARTBEAT_RECORD_ONLY = frozenset(__HEARTBEAT_RECORD_ONLY)

_HEARTBEAT_ALLOWED = (states.DEPLOYWAIT, states.CLEANWAIT, states.RESCUEWAIT,
                      # These are allowed but don't cause any actions since
                      # they're also in HEARTBEAT_RECORD_ONLY.
                      states.DEPLOYING, states.CLEANING, states.RESCUING,
                      states.DEPLOYHOLD, states.CLEANHOLD, states.SERVICING,
                      states.SERVICEWAIT, states.SERVICEHOLD)
HEARTBEAT_ALLOWED = frozenset(_HEARTBEAT_ALLOWED)

_FASTTRACK_HEARTBEAT_ALLOWED = _HEARTBEAT_ALLOWED + (states.MANAGEABLE,
                                                     states.AVAILABLE,
                                                     states.ENROLL)
FASTTRACK_HEARTBEAT_ALLOWED = frozenset(_FASTTRACK_HEARTBEAT_ALLOWED)

_VALID_STEP_TYPES = ('clean', 'deploy', 'service')


@METRICS.timer('AgentBase.post_clean_step_hook')
def post_clean_step_hook(interface, step):
    """Decorator method for adding a post clean step hook.

    This is a mechanism for adding a post clean step hook for a particular
    clean step.  The hook will get executed after the clean step gets executed
    successfully.  The hook is not invoked on failure of the clean step.

    Any method to be made as a hook may be decorated with @post_clean_step_hook
    mentioning the interface and step after which the hook should be executed.
    A TaskManager instance and the object for the last completed command
    (provided by agent) will be passed to the hook method. The return value of
    this method will be ignored. Any exception raised by this method will be
    treated as a failure of the clean step and the node will be moved to
    CLEANFAIL state.

    :param interface: name of the interface
    :param step: The name of the step after which it should be executed.
    :returns: A method which registers the given method as a post clean
        step hook.
    """
    def decorator(func):
        _POST_STEP_HOOKS['clean'].setdefault(interface, {})[step] = func
        return func

    return decorator


@METRICS.timer('AgentBase.post_deploy_step_hook')
def post_deploy_step_hook(interface, step):
    """Decorator method for adding a post deploy step hook.

    This is a mechanism for adding a post deploy step hook for a particular
    deploy step.  The hook will get executed after the deploy step gets
    executed successfully.  The hook is not invoked on failure of the deploy
    step.

    Any method to be made as a hook may be decorated with
    @post_deploy_step_hook mentioning the interface and step after which the
    hook should be executed.  A TaskManager instance and the object for the
    last completed command (provided by agent) will be passed to the hook
    method. The return value of this method will be ignored. Any exception
    raised by this method will be treated as a failure of the deploy step and
    the node will be moved to DEPLOYFAIL state.

    :param interface: name of the interface
    :param step: The name of the step after which it should be executed.
    :returns: A method which registers the given method as a post deploy
        step hook.
    """
    def decorator(func):
        _POST_STEP_HOOKS['deploy'].setdefault(interface, {})[step] = func
        return func

    return decorator


def _get_post_step_hook(node, step_type):
    """Get post clean/deploy step hook for the currently executing step.

    :param node: a node object
    :param step_type: 'clean' or 'deploy' or 'service'
    :returns: a method if there is a post clean step hook for this clean
        step; None otherwise
    """

    step_obj = getattr(node, "%s_step" % step_type)
    interface = step_obj.get('interface')
    step = step_obj.get('step')
    try:
        return _POST_STEP_HOOKS[step_type][interface][step]
    except KeyError:
        pass


def _post_step_reboot(task, step_type):
    """Reboots a node out of band after a step that requires it.

    If an agent step has 'reboot_requested': True, reboots the node when
    the step is completed. Will put the node in CLEANFAIL/DEPLOYFAIL if
    the node cannot be rebooted.

    :param task: a TaskManager instance
    :param step_type: 'clean' or 'deploy' or 'service'
    """
    current_step = getattr(task.node, '%s_step' % step_type)
    try:
        # NOTE(fellypefca): ensure that the baremetal node boots back into
        # the ramdisk after reboot.
        deploy_utils.reboot_to_finish_step(task)
    except Exception as e:
        msg = (_('Reboot requested by %(type)s step %(step)s failed for '
                 'node %(node)s: %(err)s') %
               {'step': current_step,
                'node': task.node.uuid,
                'err': e,
                'type': step_type})
        traceback = not isinstance(e, exception.IronicException)
        # do not set cleaning_reboot if we didn't reboot
        if step_type == 'clean':
            manager_utils.cleaning_error_handler(task, msg,
                                                 traceback=traceback)
        elif step_type == 'deploy':
            manager_utils.deploying_error_handler(task, msg,
                                                  traceback=traceback)
        elif step_type == 'service':
            manager_utils.servicing_error_handler(task, msg,
                                                  traceback=traceback)
        return

    # Signify that we've rebooted
    async_steps.set_node_flags(task.node, reboot=True, step_type=step_type)
    task.node.save()


def _freshly_booted(commands, step_type):
    """Check if the ramdisk has just started.

    On the very first boot we fetch the available steps, hence the only command
    agent executed will be get_XXX_steps. For later reboots the list of
    commands will be empty.
    """
    if not commands:
        # Empty list, most likely unit testing or immediately after a reboot.
        return True
    step_name = 'get_%s_steps' % step_type
    # Make a list of resulting commands which do not match the expected
    # get_XXX_steps command.
    result = [x for x in commands if not x['command_name'] == step_name]
    # If the length of the result is greater than 0, then this is not a freshly
    # booted agent.
    return not len(result) > 0


def _get_completed_command(task, commands, step_type):
    """Returns None or a completed clean/deploy command from the agent.

    :param task: a TaskManager instance to act on.
    :param commands: a set of command results from the agent, typically
                     fetched with agent_client.get_commands_status().
    """
    assert commands, 'BUG: _get_completed_command called with no commands'

    last_command = commands[-1]

    if last_command['command_name'] != 'execute_%s_step' % step_type:
        # catches race condition where execute_step is still
        # processing so the command hasn't started yet
        LOG.debug('Expected agent last command to be "execute_%(type)s_step" '
                  'for node %(node)s, instead got "%(command)s". An out-of-'
                  'band step may be running. Waiting for next heartbeat.',
                  {'node': task.node.uuid,
                   'command': last_command['command_name'],
                   'type': step_type})
        return

    last_result = last_command.get('command_result') or {}
    last_step = last_result.get('%s_step' % step_type)
    current_step = getattr(task.node, '%s_step' % step_type)
    if last_command['command_status'] == 'RUNNING':
        LOG.debug('%(type)s step still running for node %(node)s: %(step)s',
                  {'step': last_step, 'node': task.node.uuid,
                   'type': step_type.capitalize()})
        return
    elif (last_command['command_status'] == 'SUCCEEDED'
          and (not last_step
               or not conductor_steps.is_equivalent(last_step, current_step))):
        # A previous step was running, the new command has not yet started.
        LOG.debug('%(type)s step %(step)s is not currently running for node '
                  '%(node)s. Not yet started or an out-of-band step is in '
                  'progress. The last finished step is %(previous)s.',
                  {'step': current_step, 'node': task.node.uuid,
                   'type': step_type.capitalize(), 'previous': last_step})
        return
    else:
        return last_command


@METRICS.timer('AgentBase.log_and_raise_deployment_error')
def log_and_raise_deployment_error(task, msg, collect_logs=True, exc=None):
    """Helper method to log the error and raise exception.

    :param task: a TaskManager instance containing the node to act on.
    :param msg: the message to set in last_error of the node.
    :param collect_logs: Boolean indicating whether to attempt to collect
                         logs from IPA-based ramdisk. Defaults to True.
                         Actual log collection is also affected by
                         CONF.agent.deploy_logs_collect config option.
    :param exc: Exception that caused the failure.
    """
    log_traceback = (exc is not None
                     and not isinstance(exc, exception.IronicException))

    # Replicate the logic in do_next_deploy_step to prepend the current step
    step_id = (conductor_steps.step_id(task.node.deploy_step)
               if task.node.deploy_step else None)
    if step_id and step_id not in msg:
        msg = _("Deploy step %(step)s failed: %(err)s") % {
            'step': step_id, 'err': msg
        }

    LOG.error(msg, exc_info=log_traceback)
    deploy_utils.set_failed_state(task, msg, collect_logs=collect_logs)
    raise exception.InstanceDeployFailure(msg)


def get_steps(task, step_type, interface=None, override_priorities=None):
    """Get the list of cached clean or deploy steps from the agent.

    The steps cache is updated at the beginning of cleaning or deploy.

    :param task: a TaskManager object containing the node
    :param step_type: 'clean' or 'deploy'
    :param interface: The interface for which clean/deploy steps
        are to be returned. If this is not provided, it returns the
        steps for all interfaces.
    :param override_priorities: a dictionary with keys being step names and
        values being new priorities for them. If a step isn't in this
        dictionary, the step's original priority is used.
    :returns: A list of clean/deploy step dictionaries
    """
    node = task.node
    try:
        all_steps = node.driver_internal_info['agent_cached_%s_steps'
                                              % step_type]
    except KeyError:
        LOG.debug('%(type)s steps are not yet available for node %(node)s',
                  {'type': step_type.capitalize(), 'node': node.uuid})
        return []

    if interface:
        steps = [step.copy() for step in all_steps.get(interface, [])]
    else:
        steps = [step.copy() for step_list in all_steps.values()
                 for step in step_list]

    if not steps or not override_priorities:
        return steps

    for step in steps:
        new_priority = override_priorities.get(step.get('step'))
        if new_priority is not None:
            step['priority'] = new_priority

    return steps


def find_step(task, step_type, interface, name):
    """Find the given in-band step."""
    steps = get_steps(task, step_type, interface)
    return conductor_steps.find_step(
        steps, {'interface': interface, 'step': name})


def _validate_step_type(step_type):
    if step_type not in _VALID_STEP_TYPES:
        err_msg = _('Invalid step type "%(step_type)s". Valid step types: '
                    '%(valid_step_types)s') % {
                        'step_type': step_type,
                        'valid_step_types': _VALID_STEP_TYPES}
        LOG.error(err_msg)
        raise exception.InvalidParameterValue(err_msg)


def _raise(step_type, msg):
    _validate_step_type(step_type)
    step_to_exc = {
        'clean': exception.NodeCleaningFailure,
        'deploy': exception.InstanceDeployFailure,
        'service': exception.NodeServicingFailure,
    }
    raise step_to_exc[step_type](msg)


def execute_step(task, step, step_type, client=None):
    """Execute a clean or deploy step asynchronously on the agent.

    :param task: a TaskManager object containing the node
    :param step: a step dictionary to execute
    :param step_type: 'clean' or 'deploy'
    :param client: agent client (if available)
    :raises: NodeCleaningFailure (clean step) or InstanceDeployFailure (deploy
        step) or NodeServicingFailure (service step) if the agent does not
        return a command status.
    :returns: states.CLEANWAIT/DEPLOYWAIT/SERVICEWAIT to signify the step will
        be completed async
    """
    if client is None:
        client = agent_client.get_client(task)
    ports = objects.Port.list_by_node_id(
        task.context, task.node.id)
    call = getattr(client, 'execute_%s_step' % step_type)
    result = call(step, task.node, ports)
    if not result.get('command_status'):
        _raise(step_type, _(
            'Agent on node %(node)s returned bad command result: '
            '%(result)s') % {'node': task.node.uuid, 'result': result})
    _validate_step_type(step_type)
    step_to_state = {
        'clean': states.CLEANWAIT,
        'deploy': states.DEPLOYWAIT,
        'service': states.SERVICEWAIT,
    }
    return step_to_state[step_type]


def execute_clean_step(task, step):
    # NOTE(dtantsur): left for compatibility with agent-based hardware types.
    return execute_step(task, step, 'clean')


def _step_failure_handler(task, msg, step_type, traceback=False):
    driver_utils.collect_ramdisk_logs(
        task.node, label='cleaning' if step_type == 'clean' else None)
    if step_type == 'clean':
        manager_utils.cleaning_error_handler(task, msg, traceback=traceback)
    else:
        manager_utils.deploying_error_handler(task, msg, traceback=traceback)


def _continue_steps(task, step_type):
    if step_type == 'clean':
        task.resume_cleaning()
        cleaning.continue_node_clean(task)
    else:
        task.process_event('resume')
        if step_type == 'deploy':
            deployments.continue_node_deploy(task)
        else:
            servicing.continue_node_service(task)


class HeartbeatMixin(object):
    """Mixin class implementing heartbeat processing."""

    collect_deploy_logs = True

    def reboot_to_instance(self, task):
        """Method invoked after the deployment is completed.

        :param task: a TaskManager instance

        """

    def refresh_steps(self, task, step_type):
        """Refresh the node's cached clean steps

        :param task: a TaskManager instance
        :param step_type: "clean" or "deploy"
        """

    def refresh_clean_steps(self, task):
        """Refresh the node's cached clean steps

        :param task: a TaskManager instance
        """
        return self.refresh_steps(task, 'clean')

    def refresh_service_steps(self, task):
        """Refresh the node's cached service steps

        :param task: a TaskManager instance
        """
        return self.refresh_steps(task, 'service')

    def process_next_step(self, task, step_type):
        """Start the next step if the previous one is complete.

        :param task: a TaskManager instance
        :param step_type: "clean", "deploy", "service"
        """

    def continue_cleaning(self, task):
        """Start the next cleaning step if the previous one is complete.

        :param task: a TaskManager instance
        """
        return self.process_next_step(task, 'clean')

    def continue_servicing(self, task):
        """Start the next cleaning step if the previous one is complete.

        :param task: a TaskManager instance
        """
        return self.process_next_step(task, 'service')

    def heartbeat_allowed(self, node):
        if utils.fast_track_enabled(node):
            return node.provision_state in FASTTRACK_HEARTBEAT_ALLOWED
        else:
            return node.provision_state in HEARTBEAT_ALLOWED

    def _heartbeat_in_maintenance(self, task):
        node = task.node
        if (node.provision_state in (states.CLEANING, states.CLEANWAIT)
                and not CONF.conductor.allow_provisioning_in_maintenance):
            log_msg = ('Aborting cleaning for node %s, as it is in '
                       'maintenance mode' % node.uuid)
            last_error = _('Cleaning aborted as node is in maintenance mode')
            manager_utils.cleaning_error_handler(task, log_msg,
                                                 errmsg=last_error)
        elif (node.provision_state in (states.DEPLOYING, states.DEPLOYWAIT)
              and not CONF.conductor.allow_provisioning_in_maintenance):
            LOG.error('Aborting deployment for node %s, as it is in '
                      'maintenance mode', node.uuid)
            last_error = _('Deploy aborted as node is in maintenance mode')
            deploy_utils.set_failed_state(task, last_error, collect_logs=False)
        elif (node.provision_state in (states.RESCUING, states.RESCUEWAIT)
              and not CONF.conductor.allow_provisioning_in_maintenance):
            LOG.error('Aborting rescuing for node %s, as it is in '
                      'maintenance mode', node.uuid)
            last_error = _('Rescue aborted as node is in maintenance mode')
            manager_utils.rescuing_error_handler(task, last_error)
        elif (node.provision_state in (states.SERVICING, states.SERVICEWAIT)
              and not CONF.conductor.allow_provisioning_in_maintenance):
            LOG.error('Aborting service for node %s, as it is in '
                      'maintenance mode', node.uuid)
            last_error = _('Service aborted as node is in maintenance mode')
            manager_utils.servicing_error_handler(task, last_error)
        else:
            LOG.warning('Heartbeat from node %(node)s in '
                        'maintenance mode; not taking any action.',
                        {'node': node.uuid})

    def _heartbeat_deploy_wait(self, task):
        msg = _('Unexpected exception')
        node = task.node
        try:
            # NOTE(dtantsur): on first heartbeat, load in-band steps.
            if not node.driver_internal_info.get('agent_cached_deploy_steps'):
                msg = _('Failed to load in-band deploy steps')
                # Refresh steps since this is the first time IPA has
                # booted and we need to collect in-band steps.
                self.refresh_steps(task, 'deploy')

            node.touch_provisioning()
            # Check if the driver is polling for completion of
            # a step, via the 'deployment_polling' flag.
            polling = node.driver_internal_info.get(
                async_steps.DEPLOYMENT_POLLING, False)
            if not polling:
                msg = _('Failed to process the next deploy step')
                self.process_next_step(task, 'deploy')
        except Exception as e:
            last_error = _('%(msg)s: %(exc)s') % {'msg': msg, 'exc': e}
            LOG.exception('Asynchronous exception for node %(node)s: %(err)s',
                          {'node': task.node.uuid, 'err': last_error})
            # Do not call the error handler is the node is already DEPLOYFAIL
            if node.provision_state in (states.DEPLOYING, states.DEPLOYWAIT):
                deploy_utils.set_failed_state(
                    task, last_error, collect_logs=self.collect_deploy_logs)

    def _heartbeat_clean_wait(self, task):
        node = task.node
        msg = _('Failed checking if cleaning is done')
        try:
            node.touch_provisioning()
            if not node.clean_step:
                kind = ('manual'
                        if node.target_provision_state == states.MANAGEABLE
                        else 'automated')
                LOG.debug('Node %s just booted to start %s cleaning',
                          node.uuid, kind)
                msg = _('Node failed to start the first cleaning step')
                task.resume_cleaning()
                # First, cache the clean steps
                self.refresh_clean_steps(task)
                # Then set/verify node clean steps and start cleaning
                conductor_steps.set_node_cleaning_steps(task)
                cleaning.continue_node_clean(task)
            else:
                msg = _('Node failed to check cleaning progress')
                # Check if the driver is polling for completion of a step,
                # via the 'cleaning_polling' flag.
                polling = node.driver_internal_info.get(
                    async_steps.CLEANING_POLLING, False)
                if not polling:
                    self.continue_cleaning(task)
        except Exception as e:
            last_error = _('%(msg)s: %(exc)s') % {'msg': msg, 'exc': e}
            log_msg = ('Asynchronous exception for node %(node)s: %(err)s' %
                       {'node': task.node.uuid, 'err': last_error})
            if node.provision_state in (states.CLEANING, states.CLEANWAIT):
                manager_utils.cleaning_error_handler(task, log_msg,
                                                     errmsg=last_error)

    def _heartbeat_rescue_wait(self, task):
        msg = _('Node failed to perform rescue operation')
        try:
            self._finalize_rescue(task)
        except Exception as e:
            last_error = _('%(msg)s: %(exc)s') % {'msg': msg, 'exc': e}
            LOG.exception('Asynchronous exception for node %(node)s: %(err)s',
                          {'node': task.node.uuid, 'err': last_error})
            if task.node.provision_state in (states.RESCUING,
                                             states.RESCUEWAIT):
                manager_utils.rescuing_error_handler(task, last_error)

    def _heartbeat_service_wait(self, task):
        node = task.node
        msg = _('Failed checking if service is done')
        try:
            node.touch_provisioning()
            if not node.service_step:
                LOG.debug('Node %s just booted to start service',
                          node.uuid)
                msg = _('Node failed to start the first service step')
                task.process_event('resume')
                # First, cache the service steps
                self.refresh_service_steps(task)
                # Then set/verify node servicesteps and start service
                conductor_steps.set_node_service_steps(task)
                servicing.continue_node_service(task)
            else:
                msg = _('Node failed to check service progress')
                # Check if the driver is polling for completion of a step,
                # via the 'servicing_polling' flag.
                polling = node.driver_internal_info.get(
                    async_steps.SERVICING_POLLING, False)
                if not polling:
                    self.continue_servicing(task)
        except Exception as e:
            last_error = _('%(msg)s: %(exc)s') % {'msg': msg, 'exc': e}
            log_msg = ('Asynchronous exception for node %(node)s: %(err)s' %
                       {'node': task.node.uuid, 'err': last_error})
            if node.provision_state in (states.SERVICING, states.SERVICEWAIT):
                manager_utils.servicing_error_handler(task, log_msg,
                                                      errmsg=last_error)

    @METRICS.timer('HeartbeatMixin.heartbeat')
    def heartbeat(self, task, callback_url, agent_version,
                  agent_verify_ca=None, agent_status=None,
                  agent_status_message=None):
        """Process a heartbeat.

        :param task: task to work with.
        :param callback_url: agent HTTP API URL.
        :param agent_version: The version of the agent that is heartbeating
        :param agent_verify_ca: TLS certificate for the agent.
        :param agent_status: Status of the heartbeating agent
        :param agent_status_message: Status message that describes the
            agent_status
        """
        # NOTE(pas-ha) immediately skip the rest if nothing to do
        if (not self.heartbeat_allowed(task.node)
                and not manager_utils.fast_track_able(task)):
            LOG.error('Heartbeat from node %(node)s in unsupported '
                      'provision state %(state)s, not taking any action.',
                      {'node': task.node.uuid,
                       'state': task.node.provision_state})
            return

        try:
            task.upgrade_lock(retry=False)
        except exception.NodeLocked:
            LOG.warning('Node %s is currently locked, skipping heartbeat '
                        'processing (will retry on the next heartbeat)',
                        task.node.uuid)
            return
        except Exception as e:
            LOG.warning('Node %s failed to lock for a heartbeat operation '
                        'with an unknown cause. Error: %s', task.node.uuid, e)
            return

        node = task.node
        LOG.debug('Heartbeat from node %s in state %s (target state %s)',
                  node.uuid, node.provision_state, node.target_provision_state)
        node.set_driver_internal_info('agent_url', callback_url)
        node.set_driver_internal_info('agent_version', agent_version)
        # Record the last heartbeat event time
        node.timestamp_driver_internal_info('agent_last_heartbeat')
        if agent_verify_ca:
            node.set_driver_internal_info('agent_verify_ca', agent_verify_ca)
        if agent_status:
            node.set_driver_internal_info('agent_status', agent_status)
        if agent_status_message:
            node.set_driver_internal_info('agent_status_message',
                                          agent_status_message)
        node.save()

        if node.provision_state in _HEARTBEAT_RECORD_ONLY:
            # We shouldn't take any additional action. The agent will
            # silently continue to heartbeat to ironic until user initiated
            # state change occurs causing it to match a state below.
            LOG.debug('Heartbeat from %(node)s recorded to identify the '
                      'node as on-line.', {'node': task.node.uuid})
            return

        if node.maintenance:
            return self._heartbeat_in_maintenance(task)
        if node.provision_state == states.DEPLOYWAIT:
            self._heartbeat_deploy_wait(task)
        elif node.provision_state == states.CLEANWAIT:
            self._heartbeat_clean_wait(task)
        elif node.provision_state == states.RESCUEWAIT:
            self._heartbeat_rescue_wait(task)
        elif node.provision_state == states.SERVICEWAIT:
            self._heartbeat_service_wait(task)

    def _finalize_rescue(self, task):
        """Call ramdisk to prepare rescue mode and verify result.

        :param task: A TaskManager instance
        :raises: InstanceRescueFailure, if rescuing failed
        """
        node = task.node
        try:
            client = agent_client.get_client(task)
            result = client.finalize_rescue(node)
        except exception.IronicException as e:
            raise exception.InstanceRescueFailure(node=node.uuid,
                                                  instance=node.instance_uuid,
                                                  reason=e)
        if ((not result.get('command_status'))
                or result.get('command_status') != 'SUCCEEDED'):
            # NOTE(mariojv) Caller will clean up failed rescue in exception
            # handler.
            fail_reason = (_('Agent returned bad result for command '
                             'finalize_rescue: %(result)s') %
                           {'result': agent_client.get_command_error(result)})
            raise exception.InstanceRescueFailure(node=node.uuid,
                                                  instance=node.instance_uuid,
                                                  reason=fail_reason)
        task.process_event('resume')
        task.driver.rescue.clean_up(task)
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.configure_tenant_networks(task)
        task.process_event('done')


class AgentBaseMixin(object):
    """Mixin with base methods not relying on any deploy steps.

    Provides full support for in-band and out-of-band cleaning and
    the machinery to support both deploy and clean in-band steps.
    """

    def should_manage_boot(self, task):
        """Whether agent boot is managed by ironic."""
        return True

    @METRICS.timer('AgentBaseMixin.tear_down')
    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Power off the node. All actual clean-up is done in the clean_up()
        method which should be called separately.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        :raises: NetworkError if the cleaning ports cannot be removed.
        :raises: InvalidParameterValue when the wrong state is specified
             or the wrong driver info is specified.
        :raises: StorageError when volume detachment fails.
        :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.
        """
        if not task.node.disable_power_off:
            manager_utils.node_power_action(task, states.POWER_OFF)
        task.driver.storage.detach_volumes(task)
        deploy_utils.tear_down_storage_configuration(task)
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.unconfigure_tenant_networks(task)
            # NOTE(mgoddard): If the deployment was unsuccessful the node may
            # have ports on the provisioning network which were not deleted.
            task.driver.network.remove_provisioning_network(task)
        return states.DELETED

    @METRICS.timer('AgentBaseMixin.clean_up')
    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Unlinks TFTP and instance images and triggers image cache cleanup.
        Removes the TFTP configuration files for this node.

        :param task: a TaskManager instance containing the node to act on.
        """
        if self.should_manage_boot(task):
            task.driver.boot.clean_up_ramdisk(task)
        task.driver.boot.clean_up_instance(task)
        provider = dhcp_factory.DHCPFactory()
        provider.clean_dhcp(task)
        # NOTE(dtantsur): in a regular case, this is handled by tear_down, but
        # we cannot power off the node there, so making sure it no longer runs
        # the instance image by rebooting after boot.clean_up_instance.
        if task.node.disable_power_off:
            manager_utils.node_power_action(task, states.REBOOT)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        :param task: a TaskManager instance.
        """
        pass

    @METRICS.timer('AgentBaseMixin.prepare_cleaning')
    def prepare_cleaning(self, task):
        """Boot into the agent to prepare for cleaning.

        :param task: a TaskManager object containing the node
        :raises: NodeCleaningFailure, NetworkError if the previous cleaning
            ports cannot be removed or if new cleaning ports cannot be created.
        :raises: InvalidParameterValue if cleaning network UUID config option
            has an invalid value.
        :returns: states.CLEANWAIT to signify an asynchronous prepare
        """
        result = deploy_utils.prepare_inband_cleaning(
            task, manage_boot=self.should_manage_boot(task))
        if result is None:
            # Fast-track, ensure the steps are available.
            self.refresh_steps(task, 'clean')
        return result

    @METRICS.timer('AgentBaseMixin.tear_down_cleaning')
    def tear_down_cleaning(self, task):
        """Clean up the PXE and DHCP files after cleaning.

        :param task: a TaskManager object containing the node
        :raises: NodeCleaningFailure, NetworkError if the cleaning ports cannot
            be removed
        """
        deploy_utils.tear_down_inband_cleaning(
            task, manage_boot=self.should_manage_boot(task))

    @METRICS.timer('AgentBaseMixin.prepare_cleaning')
    def prepare_service(self, task):
        """Boot into the agent to prepare for service.

        :param task: a TaskManager object containing the node
        :raises: NodeServiceFailure, NetworkError if: the previous service
            ports cannot be removed or if new service ports cannot be created.
        :raises: InvalidParameterValue if cleaning network UUID config option
            has an invalid value.
        :returns: states.SERVICEWAIT to signify an asynchronous prepare
        """
        result = deploy_utils.prepare_inband_service(task)
        if result is None:
            # Fast-track, ensure the steps are available.
            self.refresh_steps(task, 'service')
        return result

    @METRICS.timer('AgentBaseMixin.tear_down_service')
    def tear_down_service(self, task):
        """Clean up the PXE and DHCP files after service.

        :param task: a TaskManager object containing the node
        :raises: NodeServiceFailure, NetworkError if the servicing ports
            cannot be removed
        """
        if task.node.disable_power_off:
            LOG.debug('Locking down the agent on node %s before exiting '
                      'servicing', task.node.uuid)
            agent_client.get_client(task).lockdown(
                # NOTE(dtantsur): we cannot assume the agent is still running
                # hence fail_if_unavailable=False.
                task.node, fail_if_unavailable=False)
        deploy_utils.tear_down_inband_service(task)

    @METRICS.timer('AgentBaseMixin.get_clean_steps')
    def get_clean_steps(self, task):
        """Get the list of clean steps from the agent.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the clean steps are not yet
            available (cached), for example, when a node has just been
            enrolled and has not been cleaned yet.
        :returns: A list of clean step dictionaries
        """
        new_priorities = {
            'erase_devices': CONF.deploy.erase_devices_priority,
            'erase_devices_metadata':
                CONF.deploy.erase_devices_metadata_priority,
        }
        return get_steps(
            task, 'clean', interface='deploy',
            override_priorities=new_priorities)

    @METRICS.timer('AgentBaseMixin.get_service_steps')
    def get_service_steps(self, task):
        """Get the list of clean steps from the agent.

        :param task: a TaskManager object containing the node
        :returns: A list of service step dictionaries, if an error
                  occurs, then an empty list is returned.
        """
        return get_steps(task, 'service')

    @METRICS.timer('AgentBaseMixin.refresh_steps')
    def refresh_steps(self, task, step_type):
        """Refresh the node's cached clean/deploy steps from the booted agent.

        Gets the node's steps from the booted agent and caches them.
        The steps are cached to make get_clean_steps() calls synchronous, and
        should be refreshed as soon as the agent boots to start cleaning/deploy
        or if cleaning is restarted because of a hardware manager version
        mismatch.

        :param task: a TaskManager instance
        :param step_type: 'clean' or 'deploy'
        :raises: NodeCleaningFailure or InstanceDeployFailure if the agent
            returns invalid results
        """
        node = task.node
        previous_steps = node.driver_internal_info.get(
            'agent_cached_%s_steps' % step_type)
        LOG.debug('Refreshing agent %(type)s step cache for node %(node)s. '
                  'Previously cached steps: %(steps)s',
                  {'node': node.uuid, 'type': step_type,
                   'steps': previous_steps})
        client = agent_client.get_client(task)
        call = getattr(client, 'get_%s_steps' % step_type)
        try:
            agent_result = call(node, task.ports).get('command_result', {})
        except exception.AgentInProgress as exc:
            LOG.debug('Agent for node %(node)s is busy with a command, '
                      'will refresh steps on the next heartbeat.',
                      {'node': task.node.uuid})
            return

            # TODO(dtantsur): change to just 'raise'
            if step_type == 'clean':
                raise
            else:
                LOG.warning('Agent running on node %(node)s does not support '
                            'in-band deploy steps: %(err)s. Support for old '
                            'agents will be removed in the V release.',
                            {'node': node.uuid, 'err': exc})
                return

        missing = set(['%s_steps' % step_type,
                       'hardware_manager_version']).difference(agent_result)
        if missing:
            _raise(step_type, _(
                'agent get_%(type)s_steps for node %(node)s returned an '
                'invalid result. Keys: %(keys)s are missing from result: '
                '%(result)s.')
                % ({'node': node.uuid, 'keys': missing,
                    'result': agent_result, 'type': step_type}))

        # agent_result['clean_steps'] looks like
        # {'HardwareManager': [{step1},{steps2}...], ...}
        steps = collections.defaultdict(list)
        for step_list in agent_result['%s_steps' % step_type].values():
            for step in step_list:
                missing = set(['interface', 'step', 'priority']).difference(
                    step)
                if missing:
                    _raise(step_type, _(
                        'agent get_%(type)s_steps for node %(node)s returned '
                        'an invalid %(type)s step. Keys: %(keys)s are missing '
                        'from step: %(step)s.') % ({'node': node.uuid,
                                                    'keys': missing,
                                                    'step': step,
                                                    'type': step_type}))

                if step_type == 'clean':
                    step['requires_ramdisk'] = True
                steps[step['interface']].append(step)

        # Save hardware manager version, steps, and date
        node.set_driver_internal_info('hardware_manager_version',
                                      agent_result['hardware_manager_version'])
        node.set_driver_internal_info('agent_cached_%s_steps' % step_type,
                                      dict(steps))
        node.timestamp_driver_internal_info(
            'agent_cached_%s_steps_refreshed' % step_type)
        node.save()
        LOG.debug('Refreshed agent %(type)s step cache for node %(node)s: '
                  '%(steps)s', {'node': node.uuid, 'steps': steps,
                                'type': step_type})

    @METRICS.timer('AgentBaseMixin.execute_clean_step')
    def execute_clean_step(self, task, step):
        """Execute a clean step asynchronously on the agent.

        :param task: a TaskManager object containing the node
        :param step: a clean step dictionary to execute
        :raises: NodeCleaningFailure if the agent does not return a command
            status
        :returns: states.CLEANWAIT to signify the step will be completed async
        """
        return execute_step(task, step, 'clean')

    @METRICS.timer('AgentBaseMixin.execute_service_step')
    def execute_service_step(self, task, step):
        """Execute a service step asynchronously on the agent.

        :param task: a TaskManager object containing the node
        :param step: a service step dictionary to execute
        :raises: NodeServicingFailure if the agent does not return a command
            status
        :returns: states.SERVICEWAIT to signify the step will be completed
            async
        """
        return execute_step(task, step, 'service')

    def _process_version_mismatch(self, task, step_type):
        node = task.node
        # For manual clean, the target provision state is MANAGEABLE, whereas
        # for automated cleaning, it is (the default) AVAILABLE.
        manual_clean = node.target_provision_state == states.MANAGEABLE

        # Cache the new clean steps (and 'hardware_manager_version')
        try:
            self.refresh_steps(task, step_type)
        except exception.NodeCleaningFailure as e:
            msg = (_('Could not continue cleaning on node '
                     '%(node)s: %(err)s.') %
                   {'node': node.uuid, 'err': e})
            return manager_utils.cleaning_error_handler(task, msg,
                                                        traceback=True)
        except exception.InstanceDeployFailure as e:
            msg = (_('Could not continue deployment on node '
                     '%(node)s: %(err)s.') %
                   {'node': node.uuid, 'err': e})
            return manager_utils.deploying_error_handler(task, msg,
                                                         traceback=True)

        if manual_clean:
            # Don't restart manual cleaning if agent reboots to a new
            # version. Both are operator actions, unlike automated
            # cleaning. Manual clean steps are not necessarily idempotent
            # like automated clean steps and can be even longer running.
            LOG.info('During manual cleaning, node %(node)s detected '
                     'a clean version mismatch. Re-executing and '
                     'continuing from current step %(step)s.',
                     {'node': node.uuid, 'step': node.clean_step})

            node.set_driver_internal_info(
                async_steps.SKIP_CURRENT_CLEAN_STEP, False)
            node.save()
        else:
            # Restart the process, agent must have rebooted to new version
            LOG.info('During %(type)s, node %(node)s detected a '
                     '%(type)s version mismatch. Resetting %(type)s steps '
                     'and rebooting the node.',
                     {'type': step_type, 'node': node.uuid})
            try:
                conductor_steps.set_node_cleaning_steps(task)
            except exception.NodeCleaningFailure as e:
                msg = (_('Could not restart automated cleaning on node '
                         '%(node)s after step %(step)s: %(err)s.') %
                       {'node': node.uuid, 'err': e,
                        'step': node.clean_step})
                return manager_utils.cleaning_error_handler(task, msg,
                                                            traceback=True)
            except exception.InstanceDeployFailure as e:
                msg = (_('Could not restart deployment on node '
                         '%(node)s after step %(step)s: %(err)s.') %
                       {'node': node.uuid, 'err': e,
                        'step': node.deploy_step})
                return manager_utils.deploying_error_handler(task, msg,
                                                             traceback=True)

        _continue_steps(task, step_type)

    @METRICS.timer('AgentBaseMixin.process_next_step')
    def process_next_step(self, task, step_type, **kwargs):
        """Start the next clean/deploy step if the previous one is complete.

        In order to avoid errors and make agent upgrades painless, the agent
        compares the version of all hardware managers at the start of the
        process (the agent's get_clean|deploy_steps() call) and before
        executing each step. If the version has changed between steps,
        the agent is unable to tell if an ordering change will cause an issue
        so it returns VERSION_MISMATCH. For automated cleaning, we
        restart the entire cleaning cycle. For manual cleaning or deploy,
        we don't.

        Additionally, if a step includes the reboot_requested property
        set to True, this method will coordinate the reboot once the step is
        completed.
        """
        _validate_step_type(step_type)

        node = task.node
        client = agent_client.get_client(task)
        agent_commands = client.get_commands_status(task.node)
        if _freshly_booted(agent_commands, step_type):
            if step_type == 'clean':
                field = async_steps.CLEANING_REBOOT
            elif step_type == 'service':
                field = async_steps.SERVICING_REBOOT
            else:
                # TODO(TheJulia): One day we should standardize the field
                # names here, but we also need to balance human ability
                # to understand what is going on so *shrug*.
                field = async_steps.DEPLOYMENT_REBOOT
            utils.pop_node_nested_field(node, 'driver_internal_info', field)
            node.save()
            return _continue_steps(task, step_type)
        current_step = getattr(node, '%s_step' % step_type)
        command = _get_completed_command(task, agent_commands, step_type)
        LOG.debug('%(type)s command status for node %(node)s on step %(step)s:'
                  ' %(command)s', {'node': node.uuid,
                                   'step': current_step,
                                   'command': command,
                                   'type': step_type})
        if not command:
            # Agent command in progress
            return
        if command.get('command_status') == 'FAILED':
            msg = (_('%(type)s step %(step)s failed on node %(node)s. '
                     '%(err)s') %
                   {'node': node.uuid,
                    'err': agent_client.get_command_error(command),
                    'step': conductor_steps.step_id(current_step),
                    'type': step_type.capitalize()})
            return _step_failure_handler(task, msg, step_type)
        # NOTE(dtantsur): VERSION_MISMATCH is a new alias for
        # CLEAN_VERSION_MISMATCH, remove the old one after IPA removes it.
        elif command.get('command_status') in ('CLEAN_VERSION_MISMATCH',
                                               'VERSION_MISMATCH'):
            self._process_version_mismatch(task, step_type)
        elif command.get('command_status') == 'SUCCEEDED':
            step_hook = _get_post_step_hook(node, step_type)
            if step_hook is not None:
                LOG.debug('For node %(node)s, executing post %(type)s step '
                          'hook %(method)s for %(type)s step %(step)s',
                          {'method': step_hook.__name__,
                           'node': node.uuid,
                           'step': current_step,
                           'type': step_type})
                try:
                    step_hook(task, command)
                except Exception as e:
                    msg = (_('For node %(node)s, post %(type)s step hook '
                             '%(method)s failed for %(type)s step %(step)s.'
                             '%(cls)s: %(error)s') %
                           {'method': step_hook.__name__,
                            'node': node.uuid,
                            'error': e,
                            'cls': e.__class__.__name__,
                            'step': current_step,
                            'type': step_type})
                    return _step_failure_handler(task, msg, step_type,
                                                 traceback=True)

            if current_step.get('reboot_requested'):
                _post_step_reboot(task, step_type)
                return

            LOG.info('Agent on node %(node)s returned %(type)s command '
                     'success, moving to next step',
                     {'node': node.uuid, 'type': step_type})
            _continue_steps(task, step_type)
        else:
            msg = (_('Agent returned unknown status for %(type)s step %(step)s'
                     ' on node %(node)s : %(err)s.') %
                   {'node': node.uuid,
                    'err': command.get('command_status'),
                    'step': current_step,
                    'type': step_type})
            return _step_failure_handler(task, msg, step_type)


class AgentOobStepsMixin(object):
    """Mixin with out-of-band deploy steps."""

    @METRICS.timer('AgentOobStepsMixin.switch_to_tenant_network')
    @base.deploy_step(priority=30)
    @task_manager.require_exclusive_lock
    def switch_to_tenant_network(self, task):
        """Deploy step to switch the node to the tenant network.

        :param task: a TaskManager object containing the node
        """
        try:
            with manager_utils.power_state_for_network_configuration(task):
                task.driver.network.remove_provisioning_network(task)
                task.driver.network.configure_tenant_networks(task)
        except Exception as e:
            msg = (_('Error changing node %(node)s to tenant networks after '
                     'deploy. %(cls)s: %(error)s') %
                   {'node': task.node.uuid, 'cls': e.__class__.__name__,
                    'error': e})
            # NOTE(mgoddard): Don't collect logs since the node has been
            # powered off.
            log_and_raise_deployment_error(task, msg, collect_logs=False,
                                           exc=e)

    @METRICS.timer('AgentOobStepsMixin.boot_instance')
    @base.deploy_step(priority=20)
    @task_manager.require_exclusive_lock
    def boot_instance(self, task):
        """Deploy step to boot the final instance.

        :param task: a TaskManager object containing the node
        """
        can_power_on = (states.POWER_ON in
                        task.driver.power.get_supported_power_states(task))
        try:
            if task.node.disable_power_off:
                # We haven't powered off the node yet - reset it now.
                manager_utils.node_power_action(task, states.REBOOT)
            elif can_power_on:
                manager_utils.node_power_action(task, states.POWER_ON)
            else:
                LOG.debug('Not trying to power on node %s that does not '
                          'support powering on, assuming already running',
                          task.node.uuid)
        except Exception as e:
            msg = (_('Error booting node %(node)s after deploy. '
                     '%(cls)s: %(error)s') %
                   {'node': task.node.uuid, 'cls': e.__class__.__name__,
                    'error': e})
            # NOTE(mgoddard): Don't collect logs since the node has been
            # powered off.
            log_and_raise_deployment_error(task, msg, collect_logs=False,
                                           exc=e)
