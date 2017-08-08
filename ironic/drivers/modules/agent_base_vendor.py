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
from ironic.common import states
from ironic.conductor import rpcapi
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic.drivers import utils as driver_utils

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

# This contains a nested dictionary containing the post clean step
# hooks registered for each clean step of every interface.
# Every key of POST_CLEAN_STEP_HOOKS is an interface and its value
# is a dictionary. For this inner dictionary, the key is the name of
# the clean-step method in the interface, and the value is the post
# clean-step hook -- the function that is to be called after successful
# completion of the clean step.
#
# For example:
# POST_CLEAN_STEP_HOOKS =
#    {
#     'raid': {'create_configuration': <post-create function>,
#              'delete_configuration': <post-delete function>}
#    }
#
# It means that method '<post-create function>' is to be called after
# successfully completing the clean step 'create_configuration' of
# raid interface. '<post-delete function>' is to be called after
# completing 'delete_configuration' of raid interface.
POST_CLEAN_STEP_HOOKS = {}

VENDOR_PROPERTIES = {
    'deploy_forces_oob_reboot': _(
        'Whether Ironic should force a reboot of the Node via the out-of-band '
        'channel after deployment is complete. Provides compatibility with '
        'older deploy ramdisks. Defaults to False. Optional.')
}


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
        POST_CLEAN_STEP_HOOKS.setdefault(interface, {})[step] = func
        return func

    return decorator


def _get_post_clean_step_hook(node):
    """Get post clean step hook for the currently executing clean step.

    This method reads node.clean_step and returns the post clean
    step hook for the currently executing clean step.

    :param node: a node object
    :returns: a method if there is a post clean step hook for this clean
        step; None otherwise
    """
    interface = node.clean_step.get('interface')
    step = node.clean_step.get('step')
    try:
        return POST_CLEAN_STEP_HOOKS[interface][step]
    except KeyError:
        pass


def _cleaning_reboot(task):
    """Reboots a node out of band after a clean step that requires it.

    If an agent clean step has 'reboot_requested': True, reboots the
    node when the step is completed. Will put the node in CLEANFAIL
    if the node cannot be rebooted.

    :param task: a TaskManager instance
    """
    try:
        # NOTE(fellypefca): Call prepare_ramdisk on ensure that the
        # baremetal node boots back into the ramdisk after reboot.
        deploy_opts = deploy_utils.build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, deploy_opts)
        manager_utils.node_power_action(task, states.REBOOT)
    except Exception as e:
        msg = (_('Reboot requested by clean step %(step)s failed for '
                 'node %(node)s: %(err)s') %
               {'step': task.node.clean_step,
                'node': task.node.uuid,
                'err': e})
        LOG.error(msg)
        # do not set cleaning_reboot if we didn't reboot
        manager_utils.cleaning_error_handler(task, msg)
        return

    # Signify that we've rebooted
    driver_internal_info = task.node.driver_internal_info
    driver_internal_info['cleaning_reboot'] = True
    task.node.driver_internal_info = driver_internal_info
    task.node.save()


def _notify_conductor_resume_clean(task):
    LOG.debug('Sending RPC to conductor to resume cleaning for node %s',
              task.node.uuid)
    uuid = task.node.uuid
    rpc = rpcapi.ConductorAPI()
    topic = rpc.get_topic_for(task.node)
    # Need to release the lock to let the conductor take it
    task.release_resources()
    rpc.continue_node_clean(task.context, uuid, topic=topic)


def _get_completed_cleaning_command(task, commands):
    """Returns None or a completed cleaning command from the agent.

    :param task: a TaskManager instance to act on.
    :param commands: a set of command results from the agent, typically
                     fetched with agent_client.get_commands_status().
    """
    if not commands:
        return

    last_command = commands[-1]

    if last_command['command_name'] != 'execute_clean_step':
        # catches race condition where execute_clean_step is still
        # processing so the command hasn't started yet
        LOG.debug('Expected agent last command to be "execute_clean_step" '
                  'for node %(node)s, instead got "%(command)s". Waiting '
                  'for next heartbeat.',
                  {'node': task.node.uuid,
                   'command': last_command['command_name']})
        return

    last_result = last_command.get('command_result') or {}
    last_step = last_result.get('clean_step')
    if last_command['command_status'] == 'RUNNING':
        LOG.debug('Clean step still running for node %(node)s: %(step)s',
                  {'step': last_step, 'node': task.node.uuid})
        return
    elif (last_command['command_status'] == 'SUCCEEDED' and
          last_step != task.node.clean_step):
        # A previous clean_step was running, the new command has not yet
        # started.
        LOG.debug('Clean step not yet started for node %(node)s: %(step)s',
                  {'step': last_step, 'node': task.node.uuid})
        return
    else:
        return last_command


@METRICS.timer('log_and_raise_deployment_error')
def log_and_raise_deployment_error(task, msg):
    """Helper method to log the error and raise exception."""
    LOG.error(msg)
    deploy_utils.set_failed_state(task, msg)
    raise exception.InstanceDeployFailure(msg)


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

    def reboot_to_instance(self, task):
        """Method invoked after the deployment is completed.

        :param task: a TaskManager instance

        """

    def refresh_clean_steps(self, task):
        """Refresh the node's cached clean steps

        :param task: a TaskManager instance

        """

    def continue_cleaning(self, task):
        """Start the next cleaning step if the previous one is complete.

        :param task: a TaskManager instance

        """

    @property
    def heartbeat_allowed_states(self):
        """Define node states where heartbeating is allowed"""
        return (states.DEPLOYWAIT, states.CLEANWAIT)

    @METRICS.timer('HeartbeatMixin.heartbeat')
    def heartbeat(self, task, callback_url):
        """Process a heartbeat.

        :param task: task to work with.
        :param callback_url: agent HTTP API URL.
        """
        # NOTE(pas-ha) immediately skip the rest if nothing to do
        if task.node.provision_state not in self.heartbeat_allowed_states:
            LOG.debug('Heartbeat from node %(node)s in unsupported '
                      'provision state %(state)s, not taking any action.',
                      {'node': task.node.uuid,
                       'state': task.node.provision_state})
            return

        task.upgrade_lock()

        node = task.node
        LOG.debug('Heartbeat from node %s', node.uuid)

        driver_internal_info = node.driver_internal_info
        driver_internal_info['agent_url'] = callback_url
        node.driver_internal_info = driver_internal_info
        node.save()

        # Async call backs don't set error state on their own
        # TODO(jimrollenhagen) improve error messages here
        msg = _('Failed checking if deploy is done.')
        try:
            if node.maintenance:
                # this shouldn't happen often, but skip the rest if it does.
                LOG.debug('Heartbeat from node %(node)s in maintenance mode; '
                          'not taking any action.', {'node': node.uuid})
                return
            elif (node.provision_state == states.DEPLOYWAIT and
                  not self.deploy_has_started(task)):
                msg = _('Node failed to deploy.')
                self.continue_deploy(task)
            elif (node.provision_state == states.DEPLOYWAIT and
                  self.deploy_is_done(task)):
                msg = _('Node failed to move to active state.')
                self.reboot_to_instance(task)
            elif (node.provision_state == states.DEPLOYWAIT and
                  self.deploy_has_started(task)):
                node.touch_provisioning()
            elif node.provision_state == states.CLEANWAIT:
                node.touch_provisioning()
                if not node.clean_step:
                    LOG.debug('Node %s just booted to start cleaning.',
                              node.uuid)
                    msg = _('Node failed to start the first cleaning step.')
                    # First, cache the clean steps
                    self.refresh_clean_steps(task)
                    # Then set/verify node clean steps and start cleaning
                    manager_utils.set_node_cleaning_steps(task)
                    # The exceptions from RPC are not possible as we using cast
                    # here
                    _notify_conductor_resume_clean(task)
                else:
                    msg = _('Node failed to check cleaning progress.')
                    self.continue_cleaning(task)

        except Exception as e:
            err_info = {'node': node.uuid, 'msg': msg, 'e': e}
            last_error = _('Asynchronous exception for node %(node)s: '
                           '%(msg)s Exception: %(e)s') % err_info
            LOG.exception(last_error)
            if node.provision_state in (states.CLEANING, states.CLEANWAIT):
                manager_utils.cleaning_error_handler(task, last_error)
            elif node.provision_state in (states.DEPLOYING, states.DEPLOYWAIT):
                deploy_utils.set_failed_state(
                    task, last_error, collect_logs=bool(self._client))


class AgentDeployMixin(HeartbeatMixin):
    """Mixin with deploy methods."""

    @METRICS.timer('AgentDeployMixin.refresh_clean_steps')
    def refresh_clean_steps(self, task):
        """Refresh the node's cached clean steps from the booted agent.

        Gets the node's clean steps from the booted agent and caches them.
        The steps are cached to make get_clean_steps() calls synchronous, and
        should be refreshed as soon as the agent boots to start cleaning or
        if cleaning is restarted because of a cleaning version mismatch.

        :param task: a TaskManager instance
        :raises: NodeCleaningFailure if the agent returns invalid results
        """
        node = task.node
        previous_steps = node.driver_internal_info.get(
            'agent_cached_clean_steps')
        LOG.debug('Refreshing agent clean step cache for node %(node)s. '
                  'Previously cached steps: %(steps)s',
                  {'node': node.uuid, 'steps': previous_steps})

        agent_result = self._client.get_clean_steps(node, task.ports).get(
            'command_result', {})
        missing = set(['clean_steps', 'hardware_manager_version']).difference(
            agent_result)
        if missing:
            raise exception.NodeCleaningFailure(_(
                'agent get_clean_steps for node %(node)s returned an invalid '
                'result. Keys: %(keys)s are missing from result: %(result)s.')
                % ({'node': node.uuid, 'keys': missing,
                    'result': agent_result}))

        # agent_result['clean_steps'] looks like
        # {'HardwareManager': [{step1},{steps2}...], ...}
        steps = collections.defaultdict(list)
        for step_list in agent_result['clean_steps'].values():
            for step in step_list:
                missing = set(['interface', 'step', 'priority']).difference(
                    step)
                if missing:
                    raise exception.NodeCleaningFailure(_(
                        'agent get_clean_steps for node %(node)s returned an '
                        'invalid clean step. Keys: %(keys)s are missing from '
                        'step: %(step)s.') % ({'node': node.uuid,
                                               'keys': missing, 'step': step}))

                steps[step['interface']].append(step)

        # Save hardware manager version, steps, and date
        info = node.driver_internal_info
        info['hardware_manager_version'] = agent_result[
            'hardware_manager_version']
        info['agent_cached_clean_steps'] = dict(steps)
        info['agent_cached_clean_steps_refreshed'] = str(timeutils.utcnow())
        node.driver_internal_info = info
        node.save()
        LOG.debug('Refreshed agent clean step cache for node %(node)s: '
                  '%(steps)s', {'node': node.uuid, 'steps': steps})

    @METRICS.timer('AgentDeployMixin.continue_cleaning')
    def continue_cleaning(self, task, **kwargs):
        """Start the next cleaning step if the previous one is complete.

        In order to avoid errors and make agent upgrades painless, the agent
        compares the version of all hardware managers at the start of the
        cleaning (the agent's get_clean_steps() call) and before executing
        each clean step. If the version has changed between steps, the agent is
        unable to tell if an ordering change will cause a cleaning issue so
        it returns CLEAN_VERSION_MISMATCH. For automated cleaning, we restart
        the entire cleaning cycle. For manual cleaning, we don't.

        Additionally, if a clean_step includes the reboot_requested property
        set to True, this method will coordinate the reboot once the step is
        completed.
        """
        node = task.node
        # For manual clean, the target provision state is MANAGEABLE, whereas
        # for automated cleaning, it is (the default) AVAILABLE.
        manual_clean = node.target_provision_state == states.MANAGEABLE
        agent_commands = self._client.get_commands_status(task.node)

        if not agent_commands:
            if task.node.driver_internal_info.get('cleaning_reboot'):
                # Node finished a cleaning step that requested a reboot, and
                # this is the first heartbeat after booting. Continue cleaning.
                info = task.node.driver_internal_info
                info.pop('cleaning_reboot', None)
                task.node.driver_internal_info = info
                _notify_conductor_resume_clean(task)
                return
            else:
                # Agent has no commands whatsoever
                return

        command = _get_completed_cleaning_command(task, agent_commands)
        LOG.debug('Cleaning command status for node %(node)s on step %(step)s:'
                  ' %(command)s', {'node': node.uuid,
                                   'step': node.clean_step,
                                   'command': command})

        if not command:
            # Agent command in progress
            return

        if command.get('command_status') == 'FAILED':
            msg = (_('Agent returned error for clean step %(step)s on node '
                     '%(node)s : %(err)s.') %
                   {'node': node.uuid,
                    'err': command.get('command_error'),
                    'step': node.clean_step})
            LOG.error(msg)
            return manager_utils.cleaning_error_handler(task, msg)
        elif command.get('command_status') == 'CLEAN_VERSION_MISMATCH':
            # Cache the new clean steps (and 'hardware_manager_version')
            try:
                self.refresh_clean_steps(task)
            except exception.NodeCleaningFailure as e:
                msg = (_('Could not continue cleaning on node '
                         '%(node)s: %(err)s.') %
                       {'node': node.uuid, 'err': e})
                LOG.exception(msg)
                return manager_utils.cleaning_error_handler(task, msg)

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
                # Restart cleaning, agent must have rebooted to new version
                LOG.info('During automated cleaning, node %s detected a '
                         'clean version mismatch. Resetting clean steps '
                         'and rebooting the node.', node.uuid)
                try:
                    manager_utils.set_node_cleaning_steps(task)
                except exception.NodeCleaningFailure:
                    msg = (_('Could not restart automated cleaning on node '
                             '%(node)s: %(err)s.') %
                           {'node': node.uuid,
                            'err': command.get('command_error'),
                            'step': node.clean_step})
                    LOG.exception(msg)
                    return manager_utils.cleaning_error_handler(task, msg)

            _notify_conductor_resume_clean(task)

        elif command.get('command_status') == 'SUCCEEDED':
            clean_step_hook = _get_post_clean_step_hook(node)
            if clean_step_hook is not None:
                LOG.debug('For node %(node)s, executing post clean step '
                          'hook %(method)s for clean step %(step)s',
                          {'method': clean_step_hook.__name__,
                           'node': node.uuid,
                           'step': node.clean_step})
                try:
                    clean_step_hook(task, command)
                except Exception as e:
                    msg = (_('For node %(node)s, post clean step hook '
                             '%(method)s failed for clean step %(step)s.'
                             'Error: %(error)s') %
                           {'method': clean_step_hook.__name__,
                            'node': node.uuid,
                            'error': e,
                            'step': node.clean_step})
                    LOG.exception(msg)
                    return manager_utils.cleaning_error_handler(task, msg)

            if task.node.clean_step.get('reboot_requested'):
                _cleaning_reboot(task)
                return

            LOG.info('Agent on node %s returned cleaning command success, '
                     'moving to next clean step', node.uuid)
            _notify_conductor_resume_clean(task)
        else:
            msg = (_('Agent returned unknown status for clean step %(step)s '
                     'on node %(node)s : %(err)s.') %
                   {'node': node.uuid,
                    'err': command.get('command_status'),
                    'step': node.clean_step})
            LOG.error(msg)
            return manager_utils.cleaning_error_handler(task, msg)

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
                                'Error: %(error)s',
                                {'node_uuid': node.uuid,
                                 'timeout': (wait * (attempts - 1)) / 1000,
                                 'error': e})
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

            task.driver.network.remove_provisioning_network(task)
            task.driver.network.configure_tenant_networks(task)

            manager_utils.node_power_action(task, states.POWER_ON)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     'Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            log_and_raise_deployment_error(task, msg)

        task.process_event('done')
        LOG.info('Deployment to node %s done', task.node.uuid)

    @METRICS.timer('AgentDeployMixin.prepare_instance_to_boot')
    def prepare_instance_to_boot(self, task, root_uuid, efi_sys_uuid):
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
                efi_system_part_uuid=efi_sys_uuid)
        try:
            task.driver.boot.prepare_instance(task)
        except Exception as e:
            LOG.error('Deploy failed for instance %(instance)s. '
                      'Error: %(error)s',
                      {'instance': node.instance_uuid, 'error': e})
            msg = _('Failed to continue agent deployment.')
            log_and_raise_deployment_error(task, msg)

    @METRICS.timer('AgentDeployMixin.configure_local_boot')
    def configure_local_boot(self, task, root_uuid=None,
                             efi_system_part_uuid=None):
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
        :raises: InstanceDeployFailure if bootloader installation failed or
            on encountering error while setting the boot device on the node.
        """
        node = task.node
        LOG.debug('Configuring local boot for node %s', node.uuid)
        if not node.driver_internal_info.get(
                'is_whole_disk_image') and root_uuid:
            LOG.debug('Installing the bootloader for node %(node)s on '
                      'partition %(part)s, EFI system partition %(efi)s',
                      {'node': node.uuid, 'part': root_uuid,
                       'efi': efi_system_part_uuid})
            result = self._client.install_bootloader(
                node, root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid)
            if result['command_status'] == 'FAILED':
                msg = (_("Failed to install a bootloader when "
                         "deploying node %(node)s. Error: %(error)s") %
                       {'node': node.uuid,
                        'error': result['command_error']})
                log_and_raise_deployment_error(task, msg)

        try:
            deploy_utils.try_set_boot_device(task, boot_devices.DISK)
        except Exception as e:
            msg = (_("Failed to change the boot device to %(boot_dev)s "
                     "when deploying node %(node)s. Error: %(error)s") %
                   {'boot_dev': boot_devices.DISK, 'node': node.uuid,
                    'error': e})
            log_and_raise_deployment_error(task, msg)

        LOG.info('Local boot successfully configured for node %s', node.uuid)
