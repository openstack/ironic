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

"""Functionality related to cleaning."""

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.conf import CONF
from ironic.drivers import utils as driver_utils
from ironic import objects

LOG = log.getLogger(__name__)


@task_manager.require_exclusive_lock
def do_node_clean(task, clean_steps=None, disable_ramdisk=False):
    """Internal RPC method to perform cleaning of a node.

    :param task: a TaskManager instance with an exclusive lock on its node
    :param clean_steps: For a manual clean, the list of clean steps to
                        perform. Is None For automated cleaning (default).
                        For more information, see the clean_steps parameter
                        of :func:`ConductorManager.do_node_clean`.
    :param disable_ramdisk: Whether to skip booting ramdisk for cleaning.
    """
    node = task.node
    manual_clean = clean_steps is not None
    clean_type = 'manual' if manual_clean else 'automated'
    LOG.debug('Starting %(type)s cleaning for node %(node)s',
              {'type': clean_type, 'node': node.uuid})

    if not manual_clean and utils.skip_automated_cleaning(node):
        # Skip cleaning, move to AVAILABLE.
        node.clean_step = None
        node.save()

        task.process_event('done')
        how = ('API' if node.automated_clean is False else 'configuration')
        LOG.info('Automated cleaning is disabled via %(how)s, node %(node)s '
                 'has been successfully moved to AVAILABLE state',
                 {'how': how, 'node': node})
        return

    # NOTE(dtantsur): this is only reachable during automated cleaning,
    # for manual cleaning we verify maintenance mode earlier on.
    if (not CONF.conductor.allow_provisioning_in_maintenance
            and node.maintenance):
        msg = _('Cleaning a node in maintenance mode is not allowed')
        return utils.cleaning_error_handler(task, msg,
                                            tear_down_cleaning=False)

    try:
        # NOTE(ghe): Valid power and network values are needed to perform
        # a cleaning.
        task.driver.power.validate(task)
        if not disable_ramdisk:
            task.driver.network.validate(task)
    except (exception.InvalidParameterValue, exception.NetworkError) as e:
        msg = (_('Validation of node %(node)s for cleaning failed: %(msg)s') %
               {'node': node.uuid, 'msg': e})
        return utils.cleaning_error_handler(task, msg)

    utils.wipe_cleaning_internal_info(task)
    if manual_clean:
        node.set_driver_internal_info('clean_steps', clean_steps)
        node.set_driver_internal_info('cleaning_disable_ramdisk',
                                      disable_ramdisk)
    task.node.save()

    utils.node_update_cache(task)

    # Allow the deploy driver to set up the ramdisk again (necessary for
    # IPA cleaning)
    try:
        if not disable_ramdisk:
            prepare_result = task.driver.deploy.prepare_cleaning(task)
        else:
            LOG.info('Skipping preparing for in-band cleaning since '
                     'out-of-band only cleaning has been requested for node '
                     '%s', node.uuid)
            prepare_result = None
    except Exception as e:
        msg = (_('Failed to prepare node %(node)s for cleaning: %(e)s')
               % {'node': node.uuid, 'e': e})
        return utils.cleaning_error_handler(task, msg, traceback=True)

    if prepare_result == states.CLEANWAIT:
        # Prepare is asynchronous, the deploy driver will need to
        # set node.driver_internal_info['clean_steps'] and
        # node.clean_step and then make an RPC call to
        # continue_node_clean to start cleaning.

        # For manual cleaning, the target provision state is MANAGEABLE,
        # whereas for automated cleaning, it is AVAILABLE (the default).
        target_state = states.MANAGEABLE if manual_clean else None
        task.process_event('wait', target_state=target_state)
        return

    try:
        conductor_steps.set_node_cleaning_steps(
            task, disable_ramdisk=disable_ramdisk)
    except Exception as e:
        # Catch all exceptions and follow the error handling
        # path so things are cleaned up properly.
        msg = (_('Cannot clean node %(node)s: %(msg)s')
               % {'node': node.uuid, 'msg': e})
        return utils.cleaning_error_handler(task, msg)

    steps = node.driver_internal_info.get('clean_steps', [])
    step_index = 0 if steps else None
    do_next_clean_step(task, step_index, disable_ramdisk=disable_ramdisk)


@utils.fail_on_error(utils.cleaning_error_handler,
                     _("Unexpected error when processing next clean step"),
                     traceback=True)
@task_manager.require_exclusive_lock
def do_next_clean_step(task, step_index, disable_ramdisk=None):
    """Do cleaning, starting from the specified clean step.

    :param task: a TaskManager instance with an exclusive lock
    :param step_index: The first clean step in the list to execute. This
        is the index (from 0) into the list of clean steps in the node's
        driver_internal_info['clean_steps']. Is None if there are no steps
        to execute.
    :param disable_ramdisk: Whether to skip booting ramdisk for cleaning.
    """
    node = task.node
    # For manual cleaning, the target provision state is MANAGEABLE,
    # whereas for automated cleaning, it is AVAILABLE.
    manual_clean = node.target_provision_state == states.MANAGEABLE
    if step_index is None:
        steps = []
    else:
        assert node.driver_internal_info.get('clean_steps') is not None, \
            f"BUG: No clean steps for {node.uuid}, step index is {step_index}"
        steps = node.driver_internal_info['clean_steps'][step_index:]

    if disable_ramdisk is None:
        disable_ramdisk = node.driver_internal_info.get(
            'cleaning_disable_ramdisk', False)

    LOG.info('Executing %(kind)s cleaning on node %(node)s, remaining steps: '
             '%(steps)s', {'node': node.uuid, 'steps': steps,
                           'kind': 'manual' if manual_clean else 'automated'})
    # Execute each step until we hit an async step or run out of steps
    for ind, step in enumerate(steps):
        # Save which step we're about to start so we can restart
        # if necessary
        node.clean_step = step
        node.set_driver_internal_info('clean_step_index', step_index + ind)
        node.save()
        eocn = step.get('execute_on_child_nodes', False)
        result = None
        try:
            if not eocn:
                LOG.info('Executing %(step)s on node %(node)s',
                         {'step': step, 'node': node.uuid})
                use_step_handler = conductor_steps.use_reserved_step_handler(
                    task, step)
                if use_step_handler:
                    if use_step_handler == conductor_steps.EXIT_STEPS:
                        # Exit the step, i.e. hold step
                        return
                    # if use_step_handler == conductor_steps.USED_HANDLER
                    # Then we have completed the needful in the handler,
                    # but since there is no other value to check now,
                    # we know we just need to skip execute_deploy_step
                else:
                    interface = getattr(task.driver, step.get('interface'))
                    result = interface.execute_clean_step(task, step)
            else:
                LOG.info('Executing %(step)s on child nodes for node '
                         '%(node)s.',
                         {'step': step, 'node': node.uuid})
                result = execute_step_on_child_nodes(task, step)

        except Exception as e:
            if isinstance(e, exception.AgentConnectionFailed):
                if task.node.driver_internal_info.get('cleaning_reboot'):
                    LOG.info('Agent is not yet running on node %(node)s '
                             'after cleaning reboot, waiting for agent to '
                             'come up to run next clean step %(step)s.',
                             {'node': node.uuid, 'step': step})
                    node.set_driver_internal_info('skip_current_clean_step',
                                                  False)
                    target_state = (states.MANAGEABLE if manual_clean
                                    else None)
                    task.process_event('wait', target_state=target_state)
                    return
            if isinstance(e, exception.AgentInProgress):
                LOG.info('Conductor attempted to process clean step for '
                         'node %(node)s. Agent indicated it is presently '
                         'executing a command. Error: %(error)s',
                         {'node': task.node.uuid,
                          'error': e})
                node.set_driver_internal_info('skip_current_clean_step', False)
                target_state = states.MANAGEABLE if manual_clean else None
                task.process_event('wait', target_state=target_state)
                return

            msg = (_('Node %(node)s failed step %(step)s: '
                     '%(exc)s') %
                   {'node': node.uuid, 'exc': e,
                    'step': node.clean_step})
            if not disable_ramdisk:
                driver_utils.collect_ramdisk_logs(task.node, label='cleaning')
            utils.cleaning_error_handler(task, msg, traceback=True)
            return

        # Check if the step is done or not. The step should return
        # states.CLEANWAIT if the step is still being executed, or
        # None if the step is done.
        if result == states.CLEANWAIT:
            # Kill this worker, the async step will make an RPC call to
            # continue_node_clean to continue cleaning
            LOG.info('Clean step %(step)s on node %(node)s being '
                     'executed asynchronously, waiting for driver.',
                     {'node': node.uuid, 'step': step})
            target_state = states.MANAGEABLE if manual_clean else None
            task.process_event('wait', target_state=target_state)
            return
        elif result is not None:
            # NOTE(TheJulia): If your here debugging a step which fails,
            # part of the constraint is that a value *cannot* be returned.
            # to the runner. The step has to either succeed and return
            # None, or raise an exception.
            msg = (_('While executing step %(step)s on node '
                     '%(node)s, step returned invalid value: %(val)s')
                   % {'step': step, 'node': node.uuid, 'val': result})
            return utils.cleaning_error_handler(task, msg)
        LOG.info('Node %(node)s finished clean step %(step)s',
                 {'node': node.uuid, 'step': step})
    if CONF.agent.deploy_logs_collect == 'always' and not disable_ramdisk:
        driver_utils.collect_ramdisk_logs(task.node, label='cleaning')

    # Clear clean_step
    node.clean_step = None
    utils.wipe_cleaning_internal_info(task)
    node.save()
    if not disable_ramdisk:
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
            msg = (_('Failed to tear down from cleaning for node %(node)s, '
                     'reason: %(err)s')
                   % {'node': node.uuid, 'err': e})
            return utils.cleaning_error_handler(task, msg,
                                                traceback=True,
                                                tear_down_cleaning=False)
    LOG.info('Node %s cleaning complete', node.uuid)
    event = 'manage' if manual_clean or node.retired else 'done'
    # NOTE(rloo): No need to specify target prov. state; we're done
    task.process_event(event)


def execute_step_on_child_nodes(task, step):
    """Execute a requested step against a child node.

    :param task: The TaskManager object for the parent node.
    :param step: The requested step to be executed.
    :returns: None on Success, the resulting error message if a
              failure has occured.
    """
    # NOTE(TheJulia): We could just use nodeinfo list calls against
    # dbapi.
    # NOTE(TheJulia): We validate the data in advance in the API
    # with the original request context.
    eocn = step.get('execute_on_child_nodes')
    child_nodes = step.get('limit_child_node_execution', [])
    filters = {'parent_node': task.node.uuid}
    if eocn and len(child_nodes) >= 1:
        filters['uuid_in'] = child_nodes
    child_nodes = objects.Node.list(
        task.context,
        filters=filters,
        fields=['uuid']
    )
    for child_node in child_nodes:
        result = None
        LOG.info('Executing step %(step)s on child node %(node)s for parent '
                 'node %(parent_node)s',
                 {'step': step,
                  'node': child_node.uuid,
                  'parent_node': task.node.uuid})
        with task_manager.acquire(task.context,
                                  child_node.uuid,
                                  purpose='execute step') as child_task:
            interface = getattr(child_task.driver, step.get('interface'))
            LOG.info('Executing %(step)s on node %(node)s',
                     {'step': step, 'node': child_task.node.uuid})
            if not conductor_steps.use_reserved_step_handler(child_task, step):
                result = interface.execute_clean_step(child_task, step)
            if result is not None:
                if (result == states.CLEANWAIT
                    and CONF.conductor.permit_child_node_step_async_result):
                    # Operator has chosen to permit this due to some reason
                    # NOTE(TheJulia): This is where we would likely wire agent
                    # error handling if we ever implicitly allowed child node
                    # deploys to take place with the agent from a parent node
                    # being deployed.
                    continue
                msg = (_('While executing step %(step)s on child node '
                         '%(node)s, step returned invalid value: %(val)s')
                       % {'step': step, 'node': child_task.node.uuid,
                          'val': result})
                LOG.error(msg)
                # Only None or states.CLEANWAIT are possible paths forward
                # in the parent step execution code, so returning the message
                # means it will be logged.
                return msg


def get_last_error(node):
    last_error = _('By request, the clean operation was aborted')
    if node.clean_step:
        last_error += (
            _(' during or after the completion of step "%s"')
            % conductor_steps.step_id(node.clean_step)
        )
    return last_error


@task_manager.require_exclusive_lock
def do_node_clean_abort(task):
    """Internal method to abort an ongoing operation.

    :param task: a TaskManager instance with an exclusive lock
    """
    node = task.node
    try:
        task.driver.deploy.tear_down_cleaning(task)
    except Exception as e:
        log_msg = (_('Failed to tear down cleaning for node %(node)s '
                     'after aborting the operation. Error: %(err)s') %
                   {'node': node.uuid, 'err': e})
        error_msg = _('Failed to tear down cleaning after aborting '
                      'the operation')
        utils.cleaning_error_handler(task, log_msg,
                                     errmsg=error_msg,
                                     traceback=True,
                                     tear_down_cleaning=False,
                                     set_fail_state=False)
        return

    last_error = get_last_error(node)
    info_message = _('Clean operation aborted for node %s') % node.uuid
    if node.clean_step:
        info_message += (
            _(' during or after the completion of step "%s"')
            % node.clean_step
        )

    node.last_error = last_error
    node.clean_step = None
    utils.wipe_cleaning_internal_info(task)
    node.save()
    LOG.info(info_message)


@utils.fail_on_error(utils.cleaning_error_handler,
                     _("Unexpected error when processing next clean step"),
                     traceback=True)
@task_manager.require_exclusive_lock
def continue_node_clean(task):
    """Continue cleaning after finishing an async clean step.

    This function calculates which step has to run next and passes control
    into do_next_clean_step.

    :param task: a TaskManager instance with an exclusive lock
    """
    node = task.node

    next_step_index = utils.update_next_step_index(task, 'clean')

    # If this isn't the final clean step in the cleaning operation
    # and it is flagged to abort after the clean step that just
    # finished, we abort the cleaning operation.
    if node.clean_step.get('abort_after'):
        step_name = node.clean_step['step']
        if next_step_index is not None:
            LOG.debug('The cleaning operation for node %(node)s was '
                      'marked to be aborted after step "%(step)s '
                      'completed. Aborting now that it has completed.',
                      {'node': task.node.uuid, 'step': step_name})

            if node.target_provision_state == states.MANAGEABLE:
                target_state = states.MANAGEABLE
            else:
                target_state = None

            task.process_event('fail', target_state=target_state)
            do_node_clean_abort(task)
            return

        LOG.debug('The cleaning operation for node %(node)s was '
                  'marked to be aborted after step "%(step)s" '
                  'completed. However, since there are no more '
                  'clean steps after this, the abort is not going '
                  'to be done.', {'node': node.uuid,
                                  'step': step_name})

    do_next_clean_step(task, next_step_index)
