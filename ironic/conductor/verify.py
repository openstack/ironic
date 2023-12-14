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

"""Functionality related to verify steps."""

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import notification_utils as notify_utils
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils

LOG = log.getLogger(__name__)


@task_manager.require_exclusive_lock
def do_node_verify(task):
    """Internal method to perform power credentials verification."""
    node = task.node
    LOG.debug('Starting power credentials verification for node %s',
              node.uuid)

    error = None
    try:
        task.driver.power.validate(task)
    except Exception as e:
        error = (_('Failed to validate power driver interface for node '
                   '%(node)s. Error: %(msg)s') %
                 {'node': node.uuid, 'msg': e})
        log_traceback = not isinstance(e, exception.IronicException)
        LOG.error(error, exc_info=log_traceback)
    else:
        try:
            power_state = task.driver.power.get_power_state(task)
        except Exception as e:
            error = (_('Failed to get power state for node '
                       '%(node)s. Error: %(msg)s') %
                     {'node': node.uuid, 'msg': e})
            log_traceback = not isinstance(e, exception.IronicException)
            LOG.error(error, exc_info=log_traceback)

    verify_steps = conductor_steps._get_verify_steps(task,
                                                     enabled=True,
                                                     sort=True)
    for step in verify_steps:
        interface = getattr(task.driver, step.get('interface'))
        LOG.info('Executing %(step)s on node %(node)s',
                 {'step': step, 'node': node.uuid})
        try:
            interface.execute_verify_step(task, step)
        except Exception as e:
            error = ('Node %(node)s failed verify step %(step)s '
                     'with unexpected error: %(err)s' %
                     {'node': node.uuid, 'step': step['step'],
                      'err': e})
            utils.verifying_error_handler(
                task, error,
                _("Failed to verify: %s") % e,
                traceback=True)

    if error is None:
        # NOTE(janders) this can eventually move to driver-specific
        # verify steps, will leave this for a follow-up change.
        utils.node_update_cache(task)

        if power_state != node.power_state:
            old_power_state = node.power_state
            node.power_state = power_state
            task.process_event('done')
            notify_utils.emit_power_state_corrected_notification(
                task, old_power_state)

        else:
            task.process_event('done')

        LOG.info('Successfully verified node %(node)s',
                 {'node': node.uuid})

    else:
        utils.node_history_record(task.node, event=error,
                                  event_type=states.VERIFY,
                                  error=True,
                                  user=task.context.user_id)
        task.process_event('fail')
