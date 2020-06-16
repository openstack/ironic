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

LOG = log.getLogger(__name__)


@task_manager.require_exclusive_lock
def do_node_clean(task, clean_steps=None):
    """Internal RPC method to perform cleaning of a node.

    :param task: a TaskManager instance with an exclusive lock on its node
    :param clean_steps: For a manual clean, the list of clean steps to
                        perform. Is None For automated cleaning (default).
                        For more information, see the clean_steps parameter
                        of :func:`ConductorManager.do_node_clean`.
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
        LOG.info('Automated cleaning is disabled, node %s has been '
                 'successfully moved to AVAILABLE state.', node.uuid)
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
        task.driver.network.validate(task)
    except exception.InvalidParameterValue as e:
        msg = (_('Validation failed. Cannot clean node %(node)s. '
                 'Error: %(msg)s') %
               {'node': node.uuid, 'msg': e})
        return utils.cleaning_error_handler(task, msg)

    if manual_clean:
        info = node.driver_internal_info
        info['clean_steps'] = clean_steps
        node.driver_internal_info = info
        node.save()

    # Do caching of bios settings if supported by driver,
    # this will be called for both manual and automated cleaning.
    try:
        task.driver.bios.cache_bios_settings(task)
    except exception.UnsupportedDriverExtension:
        LOG.warning('BIOS settings are not supported for node %s, '
                    'skipping', task.node.uuid)
    # TODO(zshi) remove this check when classic drivers are removed
    except Exception:
        msg = (_('Caching of bios settings failed on node %(node)s. '
                 'Continuing with node cleaning.')
               % {'node': node.uuid})
        LOG.exception(msg)

    # Allow the deploy driver to set up the ramdisk again (necessary for
    # IPA cleaning)
    try:
        prepare_result = task.driver.deploy.prepare_cleaning(task)
    except Exception as e:
        msg = (_('Failed to prepare node %(node)s for cleaning: %(e)s')
               % {'node': node.uuid, 'e': e})
        LOG.exception(msg)
        return utils.cleaning_error_handler(task, msg)

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
        conductor_steps.set_node_cleaning_steps(task)
    except (exception.InvalidParameterValue,
            exception.NodeCleaningFailure) as e:
        msg = (_('Cannot clean node %(node)s. Error: %(msg)s')
               % {'node': node.uuid, 'msg': e})
        return utils.cleaning_error_handler(task, msg)

    steps = node.driver_internal_info.get('clean_steps', [])
    step_index = 0 if steps else None
    do_next_clean_step(task, step_index)


@task_manager.require_exclusive_lock
def do_next_clean_step(task, step_index):
    """Do cleaning, starting from the specified clean step.

    :param task: a TaskManager instance with an exclusive lock
    :param step_index: The first clean step in the list to execute. This
        is the index (from 0) into the list of clean steps in the node's
        driver_internal_info['clean_steps']. Is None if there are no steps
        to execute.
    """
    node = task.node
    # For manual cleaning, the target provision state is MANAGEABLE,
    # whereas for automated cleaning, it is AVAILABLE.
    manual_clean = node.target_provision_state == states.MANAGEABLE

    if step_index is None:
        steps = []
    else:
        steps = node.driver_internal_info['clean_steps'][step_index:]

    LOG.info('Executing %(state)s on node %(node)s, remaining steps: '
             '%(steps)s', {'node': node.uuid, 'steps': steps,
                           'state': node.provision_state})

    # Execute each step until we hit an async step or run out of steps
    for ind, step in enumerate(steps):
        # Save which step we're about to start so we can restart
        # if necessary
        node.clean_step = step
        driver_internal_info = node.driver_internal_info
        driver_internal_info['clean_step_index'] = step_index + ind
        node.driver_internal_info = driver_internal_info
        node.save()
        interface = getattr(task.driver, step.get('interface'))
        LOG.info('Executing %(step)s on node %(node)s',
                 {'step': step, 'node': node.uuid})
        try:
            result = interface.execute_clean_step(task, step)
        except Exception as e:
            if isinstance(e, exception.AgentConnectionFailed):
                if task.node.driver_internal_info.get('cleaning_reboot'):
                    LOG.info('Agent is not yet running on node %(node)s '
                             'after cleaning reboot, waiting for agent to '
                             'come up to run next clean step %(step)s.',
                             {'node': node.uuid, 'step': step})
                    driver_internal_info['skip_current_clean_step'] = False
                    node.driver_internal_info = driver_internal_info
                    target_state = (states.MANAGEABLE if manual_clean
                                    else None)
                    task.process_event('wait', target_state=target_state)
                    return

            msg = (_('Node %(node)s failed step %(step)s: '
                     '%(exc)s') %
                   {'node': node.uuid, 'exc': e,
                    'step': node.clean_step})
            LOG.exception(msg)
            driver_utils.collect_ramdisk_logs(task.node, label='cleaning')
            utils.cleaning_error_handler(task, msg)
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
            msg = (_('While executing step %(step)s on node '
                     '%(node)s, step returned invalid value: %(val)s')
                   % {'step': step, 'node': node.uuid, 'val': result})
            LOG.error(msg)
            return utils.cleaning_error_handler(task, msg)
        LOG.info('Node %(node)s finished clean step %(step)s',
                 {'node': node.uuid, 'step': step})

    if CONF.agent.deploy_logs_collect == 'always':
        driver_utils.collect_ramdisk_logs(task.node, label='cleaning')

    # Clear clean_step
    node.clean_step = None
    utils.wipe_cleaning_internal_info(task)
    node.save()
    try:
        task.driver.deploy.tear_down_cleaning(task)
    except Exception as e:
        msg = (_('Failed to tear down from cleaning for node %(node)s, '
                 'reason: %(err)s')
               % {'node': node.uuid, 'err': e})
        LOG.exception(msg)
        return utils.cleaning_error_handler(task, msg,
                                            tear_down_cleaning=False)

    LOG.info('Node %s cleaning complete', node.uuid)
    event = 'manage' if manual_clean or node.retired else 'done'
    # NOTE(rloo): No need to specify target prov. state; we're done
    task.process_event(event)


@task_manager.require_exclusive_lock
def do_node_clean_abort(task, step_name=None):
    """Internal method to abort an ongoing operation.

    :param task: a TaskManager instance with an exclusive lock
    :param step_name: The name of the clean step.
    """
    node = task.node
    try:
        task.driver.deploy.tear_down_cleaning(task)
    except Exception as e:
        LOG.exception('Failed to tear down cleaning for node %(node)s '
                      'after aborting the operation. Error: %(err)s',
                      {'node': node.uuid, 'err': e})
        error_msg = _('Failed to tear down cleaning after aborting '
                      'the operation')
        utils.cleaning_error_handler(task, error_msg,
                                     tear_down_cleaning=False,
                                     set_fail_state=False)
        return

    info_message = _('Clean operation aborted for node %s') % node.uuid
    last_error = _('By request, the clean operation was aborted')
    if step_name:
        msg = _(' after the completion of step "%s"') % step_name
        last_error += msg
        info_message += msg

    node.last_error = last_error
    node.clean_step = None
    utils.wipe_cleaning_internal_info(task)
    node.save()
    LOG.info(info_message)
