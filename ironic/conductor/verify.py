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
from ironic.conductor import notification_utils as notify_utils
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
    if error is None:
        # NOTE(janders) this can eventually move to driver-specific
        # verify steps, will leave this for a follow-up change.
        # Retrieve BIOS config settings for this node
        utils.node_cache_bios_settings(task, node)
        # Cache the vendor if possible
        utils.node_cache_vendor(task)
        # Cache also boot_mode and secure_boot states
        utils.node_cache_boot_mode(task)
        if power_state != node.power_state:
            old_power_state = node.power_state
            node.power_state = power_state
            task.process_event('done')
            notify_utils.emit_power_state_corrected_notification(
                task, old_power_state)

        else:
            task.process_event('done')
    else:
        node.last_error = error
        task.process_event('fail')
