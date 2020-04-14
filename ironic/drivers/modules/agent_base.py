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

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import timeutils
import retrying

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import states
from ironic.conductor import steps as conductor_steps
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import boot_mode_utils
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
        'older deploy ramdisks. Defaults to False. Optional.')
}

__HEARTBEAT_RECORD_ONLY = (states.ENROLL, states.MANAGEABLE, states.AVAILABLE,
                           states.CLEANING, states.DEPLOYING, states.RESCUING)
_HEARTBEAT_RECORD_ONLY = frozenset(__HEARTBEAT_RECORD_ONLY)

_HEARTBEAT_ALLOWED = (states.DEPLOYWAIT, states.CLEANWAIT, states.RESCUEWAIT,
                      # These are allowed but don't cause any actions since
                      # they're also in HEARTBEAT_RECORD_ONLY.
                      states.DEPLOYING, states.CLEANING, states.RESCUING)
HEARTBEAT_ALLOWED = frozenset(_HEARTBEAT_ALLOWED)

_FASTTRACK_HEARTBEAT_ALLOWED = (states.DEPLOYWAIT, states.CLEANWAIT,
                                states.RESCUEWAIT, states.ENROLL,
                                states.MANAGEABLE, states.AVAILABLE,
                                states.DEPLOYING)
FASTTRACK_HEARTBEAT_ALLOWED = frozenset(_FASTTRACK_HEARTBEAT_ALLOWED)


def _get_client():
    client = agent_client.AgentClient()
    return client


@METRICS.timer('post_clean_step_hook')
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


@METRICS.timer('post_deploy_step_hook')
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
    :param step_type: 'clean' or 'deploy'
    :returns: a method if there is a post clean step hook for this clean
        step; None otherwise
    """
    step_obj = node.clean_step if step_type == 'clean' else node.deploy_step
    interface = step_obj.get('interface')
    step = step_obj.get('step')
    try:
        return _POST_STEP_HOOKS[step_type][interface][step]
    except KeyError:
        pass


def _post_step_reboot(task, step_type):
    """Reboots a node out of band after a clean/deploy step that requires it.

    If an agent step has 'reboot_requested': True, reboots the node when
    the step is completed. Will put the node in CLEANFAIL/DEPLOYFAIL if
    the node cannot be rebooted.

    :param task: a TaskManager instance
    :param step_type: 'clean' or 'deploy'
    """
    current_step = (task.node.clean_step if step_type == 'clean'
                    else task.node.deploy_step)
    try:
        # NOTE(fellypefca): Call prepare_ramdisk on ensure that the
        # baremetal node boots back into the ramdisk after reboot.
        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        manager_utils.node_power_action(task, states.REBOOT)
    except Exception as e:
        msg = (_('Reboot requested by %(type)s step %(step)s failed for '
                 'node %(node)s: %(err)s') %
               {'step': current_step,
                'node': task.node.uuid,
                'err': e,
                'type': step_type})
        LOG.error(msg, exc_info=not isinstance(e, exception.IronicException))
        # do not set cleaning_reboot if we didn't reboot
        if step_type == 'clean':
            manager_utils.cleaning_error_handler(task, msg)
        else:
            manager_utils.deploying_error_handler(task, msg)
        return

    # Signify that we've rebooted
    driver_internal_info = task.node.driver_internal_info
    field = ('cleaning_reboot' if step_type == 'clean'
             else 'deployment_reboot')
    driver_internal_info[field] = True
    if not driver_internal_info.get('agent_secret_token_pregenerated', False):
        # Wipes out the existing recorded token because the machine will
        # need to re-establish the token.
        driver_internal_info.pop('agent_secret_token', None)
    task.node.driver_internal_info = driver_internal_info
    task.node.save()


def _get_completed_command(task, commands, step_type):
    """Returns None or a completed clean/deploy command from the agent.

    :param task: a TaskManager instance to act on.
    :param commands: a set of command results from the agent, typically
                     fetched with agent_client.get_commands_status().
    """
    if not commands:
        return

    last_command = commands[-1]

    if last_command['command_name'] != 'execute_%s_step' % step_type:
        # catches race condition where execute_step is still
        # processing so the command hasn't started yet
        LOG.debug('Expected agent last command to be "execute_%(type)s_step" '
                  'for node %(node)s, instead got "%(command)s". Waiting '
                  'for next heartbeat.',
                  {'node': task.node.uuid,
                   'command': last_command['command_name'],
                   'type': step_type})
        return

    last_result = last_command.get('command_result') or {}
    last_step = last_result.get('%s_step' % step_type)
    current_step = (task.node.clean_step if step_type == 'clean'
                    else task.node.deploy_step)
    if last_command['command_status'] == 'RUNNING':
        LOG.debug('%(type)s step still running for node %(node)s: %(step)s',
                  {'step': last_step, 'node': task.node.uuid,
                   'type': step_type.capitalize()})
        return
    elif (last_command['command_status'] == 'SUCCEEDED'
          and last_step != current_step):
        # A previous step was running, the new command has not yet started.
        LOG.debug('%(type)s step not yet started for node %(node)s: %(step)s',
                  {'step': last_step, 'node': task.node.uuid,
                   'type': step_type.capitalize()})
        return
    else:
        return last_command


@METRICS.timer('log_and_raise_deployment_error')
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


def _raise(step_type, msg):
    assert step_type in ('clean', 'deploy')
    exc = (exception.NodeCleaningFailure if step_type == 'clean'
           else exception.InstanceDeployFailure)
    raise exc(msg)


def execute_step(task, step, step_type):
    """Execute a clean or deploy step asynchronously on the agent.

    :param task: a TaskManager object containing the node
    :param step: a step dictionary to execute
    :param step_type: 'clean' or 'deploy'
    :raises: NodeCleaningFailure (clean step) or InstanceDeployFailure (deploy
        step) if the agent does not return a command status.
    :returns: states.CLEANWAIT/DEPLOYWAIT to signify the step will be
        completed async
    """
    client = _get_client()
    ports = objects.Port.list_by_node_id(
        task.context, task.node.id)
    call = getattr(client, 'execute_%s_step' % step_type)
    result = call(step, task.node, ports)
    if not result.get('command_status'):
        _raise(step_type, _(
            'Agent on node %(node)s returned bad command result: '
            '%(result)s') % {'node': task.node.uuid,
                             'result': result.get('command_error')})
    return states.CLEANWAIT if step_type == 'clean' else states.DEPLOYWAIT


def execute_clean_step(task, step):
    # NOTE(dtantsur): left for compatibility with agent-based hardware types.
    return execute_step(task, step, 'clean')


class HeartbeatMixin(object):
    """Mixin class implementing heartbeat processing."""

    def __init__(self):
        self._client = _get_client()

    def continue_deploy(self, task):
        """Continues the deployment of baremetal node.

        This method continues the deployment of the baremetal node after
        the ramdisk have been booted.

        :param task: a TaskManager instance
        """

    def deploy_has_started(self, task):
        """Check if the deployment has started already.

        :returns: True if the deploy has started, False otherwise.
        """

    def deploy_is_done(self, task):
        """Check if the deployment is already completed.

        :returns: True if the deployment is completed. False otherwise
        """

    def in_core_deploy_step(self, task):
        """Check if we are in the deploy.deploy deploy step.

        Assumes that we are in the DEPLOYWAIT state.

        :param task: a TaskManager instance
        :returns: True if the current deploy step is deploy.deploy.
        """
        step = task.node.deploy_step
        return (step
                and step['interface'] == 'deploy'
                and step['step'] == 'deploy')

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

    def process_next_step(self, task, step_type):
        """Start the next clean/deploy step if the previous one is complete.

        :param task: a TaskManager instance
        :param step_type: "clean" or "deploy"
        """

    def continue_cleaning(self, task):
        """Start the next cleaning step if the previous one is complete.

        :param task: a TaskManager instance
        """
        return self.process_next_step(task, 'clean')

    @property
    def heartbeat_allowed_states(self):
        """Define node states where heartbeating is allowed"""
        if CONF.deploy.fast_track:
            return FASTTRACK_HEARTBEAT_ALLOWED
        return HEARTBEAT_ALLOWED

    def _heartbeat_in_maintenance(self, task):
        node = task.node
        if (node.provision_state in (states.CLEANING, states.CLEANWAIT)
                and not CONF.conductor.allow_provisioning_in_maintenance):
            LOG.error('Aborting cleaning for node %s, as it is in maintenance '
                      'mode', node.uuid)
            last_error = _('Cleaning aborted as node is in maintenance mode')
            manager_utils.cleaning_error_handler(task, last_error)
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
        else:
            LOG.warning('Heartbeat from node %(node)s in '
                        'maintenance mode; not taking any action.',
                        {'node': node.uuid})

    def _heartbeat_deploy_wait(self, task):
        msg = _('Failed checking if deploy is done')
        node = task.node
        try:
            # NOTE(mgoddard): Only handle heartbeats during DEPLOYWAIT if we
            # are currently in the core deploy.deploy step. Other deploy steps
            # may cause the agent to boot, but we should not trigger deployment
            # at that point if the driver is polling for completion of a step.
            if self.in_core_deploy_step(task):
                if not self.deploy_has_started(task):
                    msg = _('Node failed to deploy')
                    self.continue_deploy(task)
                elif self.deploy_is_done(task):
                    msg = _('Node failed to move to active state')
                    self.reboot_to_instance(task)
                else:
                    node.touch_provisioning()
            else:
                # The exceptions from RPC are not possible as we using cast
                # here
                # Check if the driver is polling for completion of a step,
                # via the 'deployment_polling' flag.
                polling = node.driver_internal_info.get(
                    'deployment_polling', False)
                if not polling:
                    manager_utils.notify_conductor_resume_deploy(task)
                node.touch_provisioning()
        except Exception as e:
            last_error = _('%(msg)s. Error: %(exc)s') % {'msg': msg, 'exc': e}
            LOG.exception('Asynchronous exception for node %(node)s: %(err)s',
                          {'node': task.node.uuid, 'err': last_error})
            # Do not call the error handler is the node is already DEPLOYFAIL
            if node.provision_state in (states.DEPLOYING, states.DEPLOYWAIT):
                deploy_utils.set_failed_state(
                    task, last_error, collect_logs=bool(self._client))

    def _heartbeat_clean_wait(self, task):
        node = task.node
        msg = _('Failed checking if cleaning is done')
        try:
            node.touch_provisioning()
            if not node.clean_step:
                LOG.debug('Node %s just booted to start cleaning.',
                          node.uuid)
                msg = _('Node failed to start the first cleaning step')
                # First, cache the clean steps
                self.refresh_clean_steps(task)
                # Then set/verify node clean steps and start cleaning
                conductor_steps.set_node_cleaning_steps(task)
                # The exceptions from RPC are not possible as we using cast
                # here
                manager_utils.notify_conductor_resume_clean(task)
            else:
                msg = _('Node failed to check cleaning progress')
                # Check if the driver is polling for completion of a step,
                # via the 'cleaning_polling' flag.
                polling = node.driver_internal_info.get(
                    'cleaning_polling', False)
                if not polling:
                    self.continue_cleaning(task)
        except Exception as e:
            last_error = _('%(msg)s. Error: %(exc)s') % {'msg': msg, 'exc': e}
            LOG.exception('Asynchronous exception for node %(node)s: %(err)s',
                          {'node': task.node.uuid, 'err': last_error})
            if node.provision_state in (states.CLEANING, states.CLEANWAIT):
                manager_utils.cleaning_error_handler(task, last_error)

    def _heartbeat_rescue_wait(self, task):
        msg = _('Node failed to perform rescue operation')
        try:
            self._finalize_rescue(task)
        except Exception as e:
            last_error = _('%(msg)s. Error: %(exc)s') % {'msg': msg, 'exc': e}
            LOG.exception('Asynchronous exception for node %(node)s: %(err)s',
                          {'node': task.node.uuid, 'err': last_error})
            if task.node.provision_state in (states.RESCUING,
                                             states.RESCUEWAIT):
                manager_utils.rescuing_error_handler(task, last_error)

    @METRICS.timer('HeartbeatMixin.heartbeat')
    def heartbeat(self, task, callback_url, agent_version):
        """Process a heartbeat.

        :param task: task to work with.
        :param callback_url: agent HTTP API URL.
        :param agent_version: The version of the agent that is heartbeating
        """
        # NOTE(pas-ha) immediately skip the rest if nothing to do
        if (task.node.provision_state not in self.heartbeat_allowed_states
            and not manager_utils.fast_track_able(task)):
            LOG.error('Heartbeat from node %(node)s in unsupported '
                      'provision state %(state)s, not taking any action.',
                      {'node': task.node.uuid,
                       'state': task.node.provision_state})
            return

        try:
            task.upgrade_lock()
        except exception.NodeLocked:
            LOG.warning('Node %s is currently locked, skipping heartbeat '
                        'processing (will retry on the next heartbeat)',
                        task.node.uuid)
            return

        node = task.node
        LOG.debug('Heartbeat from node %s', node.uuid)
        driver_internal_info = node.driver_internal_info
        driver_internal_info['agent_url'] = callback_url
        driver_internal_info['agent_version'] = agent_version
        # Record the last heartbeat event time in UTC, so we can make
        # decisions about it later. Can be decoded to datetime object with:
        # datetime.datetime.strptime(var, "%Y-%m-%d %H:%M:%S.%f")
        driver_internal_info['agent_last_heartbeat'] = str(
            timeutils.utcnow().isoformat())
        node.driver_internal_info = driver_internal_info
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

    def _finalize_rescue(self, task):
        """Call ramdisk to prepare rescue mode and verify result.

        :param task: A TaskManager instance
        :raises: InstanceRescueFailure, if rescuing failed
        """
        node = task.node
        try:
            result = self._client.finalize_rescue(node)
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
                           {'result': result.get('command_error')})
            raise exception.InstanceRescueFailure(node=node.uuid,
                                                  instance=node.instance_uuid,
                                                  reason=fail_reason)
        task.process_event('resume')
        task.driver.rescue.clean_up(task)
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.configure_tenant_networks(task)
        task.process_event('done')


class AgentDeployMixin(HeartbeatMixin):
    """Mixin with deploy methods."""

    @METRICS.timer('AgentDeployMixin.get_clean_steps')
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

    @METRICS.timer('AgentDeployMixin.refresh_steps')
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

        call = getattr(self._client, 'get_%s_steps' % step_type)
        agent_result = call(node, task.ports).get('command_result', {})
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
                        'an invalid %(type)s step. Keys: %(keys)s are missing'
                        'from step: %(step)s.') % ({'node': node.uuid,
                                                    'keys': missing,
                                                    'step': step,
                                                    'type': step_type}))

                steps[step['interface']].append(step)

        # Save hardware manager version, steps, and date
        info = node.driver_internal_info
        info['hardware_manager_version'] = agent_result[
            'hardware_manager_version']
        info['agent_cached_%s_steps' % step_type] = dict(steps)
        info['agent_cached_%s_steps_refreshed' % step_type] = str(
            timeutils.utcnow())
        node.driver_internal_info = info
        node.save()
        LOG.debug('Refreshed agent %(type)s step cache for node %(node)s: '
                  '%(steps)s', {'node': node.uuid, 'steps': steps,
                                'type': step_type})

    @METRICS.timer('AgentDeployMixin.execute_clean_step')
    def execute_clean_step(self, task, step):
        """Execute a clean step asynchronously on the agent.

        :param task: a TaskManager object containing the node
        :param step: a clean step dictionary to execute
        :raises: NodeCleaningFailure if the agent does not return a command
            status
        :returns: states.CLEANWAIT to signify the step will be completed async
        """
        return execute_step(task, step, 'clean')

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
            LOG.exception(msg)
            return manager_utils.cleaning_error_handler(task, msg)
        except exception.InstanceDeployFailure as e:
            msg = (_('Could not continue deployment on node '
                     '%(node)s: %(err)s.') %
                   {'node': node.uuid, 'err': e})
            LOG.exception(msg)
            return manager_utils.deploying_error_handler(task, msg)

        if manual_clean:
            # Don't restart manual cleaning if agent reboots to a new
            # version. Both are operator actions, unlike automated
            # cleaning. Manual clean steps are not necessarily idempotent
            # like automated clean steps and can be even longer running.
            LOG.info('During manual cleaning, node %(node)s detected '
                     'a clean version mismatch. Re-executing and '
                     'continuing from current step %(step)s.',
                     {'node': node.uuid, 'step': node.clean_step})

            driver_internal_info = node.driver_internal_info
            driver_internal_info['skip_current_clean_step'] = False
            node.driver_internal_info = driver_internal_info
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
                LOG.exception(msg)
                return manager_utils.cleaning_error_handler(task, msg)
            except exception.InstanceDeployFailure as e:
                msg = (_('Could not restart deployment on node '
                         '%(node)s after step %(step)s: %(err)s.') %
                       {'node': node.uuid, 'err': e,
                        'step': node.deploy_step})
                LOG.exception(msg)
                return manager_utils.deploying_error_handler(task, msg)

        manager_utils.notify_conductor_resume_operation(task, step_type)

    @METRICS.timer('AgentDeployMixin.process_next_step')
    def process_next_step(self, task, step_type, **kwargs):
        """Start the next clean/deploy step if the previous one is complete.

        In order to avoid errors and make agent upgrades painless, the agent
        compares the version of all hardware managers at the start of the
        process (the agent's get_clean|deploy_steps() call) and before
        executing each step. If the version has changed between steps,
        the agent is unable to tell if an ordering change will cause an issue
        so it returns CLEAN_VERSION_MISMATCH. For automated cleaning, we
        restart the entire cleaning cycle. For manual cleaning or deploy,
        we don't.

        Additionally, if a step includes the reboot_requested property
        set to True, this method will coordinate the reboot once the step is
        completed.
        """
        assert step_type in ('clean', 'deploy')

        node = task.node
        agent_commands = self._client.get_commands_status(task.node)

        if not agent_commands:
            field = ('cleaning_reboot' if step_type == 'clean'
                     else 'deployment_reboot')
            if task.node.driver_internal_info.get(field):
                # Node finished a cleaning step that requested a reboot, and
                # this is the first heartbeat after booting. Continue cleaning.
                info = task.node.driver_internal_info
                info.pop(field, None)
                task.node.driver_internal_info = info
                task.node.save()
                manager_utils.notify_conductor_resume_operation(task,
                                                                step_type)
                return
            else:
                # Agent has no commands whatsoever
                return

        current_step = (node.clean_step if step_type == 'clean'
                        else node.deploy_step)
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
            msg = (_('Agent returned error for %(type)s step %(step)s on node '
                     '%(node)s : %(err)s.') %
                   {'node': node.uuid,
                    'err': command.get('command_error'),
                    'step': current_step,
                    'type': step_type})
            LOG.error(msg)
            return manager_utils.cleaning_error_handler(task, msg)
        elif command.get('command_status') in ('CLEAN_VERSION_MISMATCH',
                                               'DEPLOY_VERSION_MISMATCH'):
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
                    LOG.exception(msg)
                    if step_type == 'clean':
                        return manager_utils.cleaning_error_handler(task, msg)
                    else:
                        return manager_utils.deploying_error_handler(task, msg)

            if current_step.get('reboot_requested'):
                _post_step_reboot(task, step_type)
                return

            LOG.info('Agent on node %(node)s returned %(type)s command '
                     'success, moving to next step',
                     {'node': node.uuid, 'type': step_type})
            manager_utils.notify_conductor_resume_operation(task, step_type)
        else:
            msg = (_('Agent returned unknown status for %(type)s step %(step)s'
                     ' on node %(node)s : %(err)s.') %
                   {'node': node.uuid,
                    'err': command.get('command_status'),
                    'step': current_step,
                    'type': step_type})
            LOG.error(msg)
            if step_type == 'clean':
                return manager_utils.cleaning_error_handler(task, msg)
            else:
                return manager_utils.deploying_error_handler(task, msg)

    @METRICS.timer('AgentDeployMixin.reboot_and_finish_deploy')
    def reboot_and_finish_deploy(self, task):
        """Helper method to trigger reboot on the node and finish deploy.

        This method initiates a reboot on the node. On success, it
        marks the deploy as complete. On failure, it logs the error
        and marks deploy as failure.

        :param task: a TaskManager object containing the node
        :raises: InstanceDeployFailure, if node reboot failed.
        """
        wait = CONF.agent.post_deploy_get_power_state_retry_interval * 1000
        attempts = CONF.agent.post_deploy_get_power_state_retries + 1

        @retrying.retry(
            stop_max_attempt_number=attempts,
            retry_on_result=lambda state: state != states.POWER_OFF,
            wait_fixed=wait
        )
        def _wait_until_powered_off(task):
            return task.driver.power.get_power_state(task)

        node = task.node

        if CONF.agent.deploy_logs_collect == 'always':
            driver_utils.collect_ramdisk_logs(node)

        # Whether ironic should power off the node via out-of-band or
        # in-band methods
        oob_power_off = strutils.bool_from_string(
            node.driver_info.get('deploy_forces_oob_reboot', False))

        try:
            if not oob_power_off:
                try:
                    self._client.power_off(node)
                    _wait_until_powered_off(task)
                except Exception as e:
                    LOG.warning('Failed to soft power off node %(node_uuid)s '
                                'in at least %(timeout)d seconds. '
                                '%(cls)s: %(error)s',
                                {'node_uuid': node.uuid,
                                 'timeout': (wait * (attempts - 1)) / 1000,
                                 'cls': e.__class__.__name__, 'error': e},
                                exc_info=not isinstance(
                                    e, exception.IronicException))
                    manager_utils.node_power_action(task, states.POWER_OFF)
            else:
                # Flush the file system prior to hard rebooting the node
                result = self._client.sync(node)
                error = result.get('faultstring')
                if error:
                    if 'Unknown command' in error:
                        error = _('The version of the IPA ramdisk used in '
                                  'the deployment do not support the '
                                  'command "sync"')
                    LOG.warning(
                        'Failed to flush the file system prior to hard '
                        'rebooting the node %(node)s. Error: %(error)s',
                        {'node': node.uuid, 'error': error})

                manager_utils.node_power_action(task, states.POWER_OFF)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     '%(cls)s: %(error)s') %
                   {'node': node.uuid, 'cls': e.__class__.__name__,
                    'error': e})
            log_and_raise_deployment_error(task, msg, exc=e)

        try:
            with manager_utils.power_state_for_network_configuration(task):
                task.driver.network.remove_provisioning_network(task)
                task.driver.network.configure_tenant_networks(task)
            manager_utils.node_power_action(task, states.POWER_ON)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     '%(cls)s: %(error)s') %
                   {'node': node.uuid, 'cls': e.__class__.__name__,
                    'error': e})
            # NOTE(mgoddard): Don't collect logs since the node has been
            # powered off.
            log_and_raise_deployment_error(task, msg, collect_logs=False,
                                           exc=e)

        # TODO(dtantsur): remove these two calls when this function becomes a
        # real deploy step.
        task.process_event('wait')
        manager_utils.notify_conductor_resume_deploy(task)

    @METRICS.timer('AgentDeployMixin.prepare_instance_to_boot')
    def prepare_instance_to_boot(self, task, root_uuid, efi_sys_uuid,
                                 prep_boot_part_uuid=None):
        """Prepares instance to boot.

        :param task: a TaskManager object containing the node
        :param root_uuid: the UUID for root partition
        :param efi_sys_uuid: the UUID for the efi partition
        :raises: InvalidState if fails to prepare instance
        """

        node = task.node
        if deploy_utils.get_boot_option(node) == "local":
            # Install the boot loader
            self.configure_local_boot(
                task, root_uuid=root_uuid,
                efi_system_part_uuid=efi_sys_uuid,
                prep_boot_part_uuid=prep_boot_part_uuid)
        try:
            task.driver.boot.prepare_instance(task)
        except Exception as e:
            LOG.error('Preparing instance for booting failed for instance '
                      '%(instance)s. %(cls)s: %(error)s',
                      {'instance': node.instance_uuid,
                       'cls': e.__class__.__name__, 'error': e})
            msg = _('Failed to prepare instance for booting')
            log_and_raise_deployment_error(task, msg, exc=e)

    @METRICS.timer('AgentDeployMixin.configure_local_boot')
    def configure_local_boot(self, task, root_uuid=None,
                             efi_system_part_uuid=None,
                             prep_boot_part_uuid=None):
        """Helper method to configure local boot on the node.

        This method triggers bootloader installation on the node.
        On successful installation of bootloader, this method sets the
        node to boot from disk.

        :param task: a TaskManager object containing the node
        :param root_uuid: The UUID of the root partition. This is used
            for identifying the partition which contains the image deployed
            or None in case of whole disk images which we expect to already
            have a bootloader installed.
        :param efi_system_part_uuid: The UUID of the efi system partition.
            This is used only in uefi boot mode.
        :param prep_boot_part_uuid: The UUID of the PReP Boot partition.
            This is used only for booting ppc64* hardware.
        :raises: InstanceDeployFailure if bootloader installation failed or
            on encountering error while setting the boot device on the node.
        """
        node = task.node
        LOG.debug('Configuring local boot for node %s', node.uuid)

        # If the target RAID configuration is set to 'software' for the
        # 'controller', we need to trigger the installation of grub on
        # the holder disks of the desired Software RAID.
        internal_info = node.driver_internal_info
        raid_config = node.target_raid_config
        logical_disks = raid_config.get('logical_disks', [])
        software_raid = False
        for logical_disk in logical_disks:
            if logical_disk.get('controller') == 'software':
                LOG.debug('Node %s has a Software RAID configuration',
                          node.uuid)
                software_raid = True
                break

        # For software RAID try to get the UUID of the root fs from the
        # image's metadata (via Glance). Fall back to the driver internal
        # info in case it is not available (e.g. not set or there's no Glance).
        if software_raid:
            image_source = node.instance_info.get('image_source')
            try:
                context = task.context
                context.is_admin = True
                glance = image_service.GlanceImageService(
                    context=context)
                image_info = glance.show(image_source)
                image_properties = image_info.get('properties')
                root_uuid = image_properties['rootfs_uuid']
                LOG.debug('Got rootfs_uuid from Glance: %s '
                          '(node %s)', root_uuid, node.uuid)
            except Exception as e:
                LOG.warning('Could not get \'rootfs_uuid\' property for '
                            'image %(image)s from Glance for node %(node)s. '
                            '%(cls)s: %(error)s.',
                            {'image': image_source, 'node': node.uuid,
                             'cls': e.__class__.__name__, 'error': e})
                root_uuid = internal_info.get('root_uuid_or_disk_id')
                LOG.debug('Got rootfs_uuid from driver internal info: '
                          '%s (node %s)', root_uuid, node.uuid)

        # For whole disk images it is not necessary that the root_uuid
        # be provided since the bootloaders on the disk will be used
        whole_disk_image = internal_info.get('is_whole_disk_image')
        if (software_raid or (root_uuid and not whole_disk_image)
                or (whole_disk_image
                    and boot_mode_utils.get_boot_mode(node) == 'uefi')):
            LOG.debug('Installing the bootloader for node %(node)s on '
                      'partition %(part)s, EFI system partition %(efi)s',
                      {'node': node.uuid, 'part': root_uuid,
                       'efi': efi_system_part_uuid})
            result = self._client.install_bootloader(
                node, root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid,
                prep_boot_part_uuid=prep_boot_part_uuid)
            if result['command_status'] == 'FAILED':
                if not whole_disk_image:
                    msg = (_("Failed to install a bootloader when "
                             "deploying node %(node)s. Error: %(error)s") %
                           {'node': node.uuid,
                            'error': result['command_error']})
                    log_and_raise_deployment_error(task, msg)
                else:
                    # Its possible the install will fail if the IPA image
                    # has not been updated, log this and continue
                    LOG.info('Could not install bootloader for whole disk '
                             'image for node %(node)s, Error: %(error)s"',
                             {'node': node.uuid,
                              'error': result['command_error']})
                    return

        try:
            persistent = True
            if node.driver_info.get('force_persistent_boot_device',
                                    'Default') == 'Never':
                persistent = False
            deploy_utils.try_set_boot_device(task, boot_devices.DISK,
                                             persistent=persistent)
        except Exception as e:
            msg = (_("Failed to change the boot device to %(boot_dev)s "
                     "when deploying node %(node)s. Error: %(error)s") %
                   {'boot_dev': boot_devices.DISK, 'node': node.uuid,
                    'error': e})
            log_and_raise_deployment_error(task, msg, exc=e)

        LOG.info('Local boot successfully configured for node %s', node.uuid)
