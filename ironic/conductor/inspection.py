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

"""Inspection implementation for the conductor."""

from oslo_log import log
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils

LOG = log.getLogger(__name__)


@task_manager.require_exclusive_lock
def inspect_hardware(task):
    """Initiates inspection.

    :param task: a TaskManager instance with an exclusive lock
                 on its node.
    :raises: HardwareInspectionFailure if driver doesn't
             return the state as states.MANAGEABLE, states.INSPECTWAIT.

    """
    node = task.node

    def handle_failure(e, log_func=LOG.error):
        utils.node_history_record(task.node, event=e,
                                  event_type=states.INTROSPECTION,
                                  error=True, user=task.context.user_id)
        task.process_event('fail')
        log_func("Failed to inspect node %(node)s: %(err)s",
                 {'node': node.uuid, 'err': e})

    # Inspection cannot start in fast-track mode, wipe token and URL.
    utils.wipe_token_and_url(task)

    try:
        new_state = task.driver.inspect.inspect_hardware(task)
    except exception.IronicException as e:
        with excutils.save_and_reraise_exception():
            error = str(e)
            handle_failure(error)
    except Exception as e:
        error = (_('Unexpected exception of type %(type)s: %(msg)s') %
                 {'type': type(e).__name__, 'msg': e})
        handle_failure(error, log_func=LOG.exception)
        raise exception.HardwareInspectionFailure(error=error)

    if new_state == states.MANAGEABLE:
        task.process_event('done')
        LOG.info('Successfully inspected node %(node)s',
                 {'node': node.uuid})
    elif new_state == states.INSPECTWAIT:
        task.process_event('wait')
        LOG.info('Successfully started introspection on node %(node)s',
                 {'node': node.uuid})
    else:
        error = (_("During inspection, driver returned unexpected "
                   "state %(state)s") % {'state': new_state})
        handle_failure(error)
        raise exception.HardwareInspectionFailure(error=error)


@task_manager.require_exclusive_lock
def abort_inspection(task):
    """Abort inspection for the node."""
    node = task.node

    try:
        task.driver.inspect.abort(task)
    except exception.UnsupportedDriverExtension:
        with excutils.save_and_reraise_exception():
            LOG.error('Inspect interface "%(intf)s" does not support abort '
                      'operation for node %(node)s',
                      {'intf': node.inspect_interface, 'node': node.uuid})
    except Exception as e:
        with excutils.save_and_reraise_exception():
            LOG.exception('Error when aborting inspection of node %(node)s',
                          {'node': node.uuid})
            error = _('Failed to abort inspection: %s') % e
            utils.node_history_record(task.node, event=error,
                                      event_type=states.INTROSPECTION,
                                      error=True,
                                      user=task.context.user_id)
            node.save()

    error = _('Inspection was aborted by request.')
    utils.node_history_record(task.node, event=error,
                              event_type=states.INTROSPECTION,
                              error=True,
                              user=task.context.user_id)
    utils.wipe_token_and_url(task)
    task.process_event('abort')
    LOG.info('Successfully aborted inspection of node %(node)s',
             {'node': node.uuid})
