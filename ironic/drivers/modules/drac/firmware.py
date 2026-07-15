#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Dell iDRAC firmware update utilities.

Provides Dell-specific helpers used by the generic Redfish firmware
interface when running on iDRAC hardware.
"""

from oslo_log import log as logging

from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = logging.getLogger(__name__)


def check_scheduled_idrac_job(task, current_update):
    """Check Dell iDRAC for a scheduled Lifecycle Controller job.

    Queries the Dell OEM job collection to check whether a scheduled
    (unfinished) LC job matching the task monitor JID exists.  This
    distinguishes a successfully staged firmware update from a failed
    download where no job was created.

    :param task: a TaskManager instance
    :param current_update: the current firmware update being processed
    :returns: True if a matching scheduled job was found, False if no
        matching job exists, None if the Dell OEM extension is not
        available
    """
    node = task.node
    task_monitor_uri = current_update.get('task_monitor', '')
    jid = (task_monitor_uri.rsplit('/', 1)[-1]
           if task_monitor_uri else '')

    if not jid:
        return None

    try:
        system = redfish_utils.get_system(node)
    except Exception as e:
        LOG.warning('Cannot get system for Dell OEM job check on '
                    'node %(node)s: %(error)s. Falling back to '
                    'assuming firmware staging succeeded.',
                    {'node': node.uuid, 'error': e})
        return None

    if not system.managers:
        return None

    for manager in system.managers:
        try:
            manager_oem = manager.get_oem_extension('Dell')
        except Exception as e:
            LOG.warning('Dell OEM extension not found on iDRAC node '
                        '%(node)s: %(error)s. Falling back to '
                        'assuming firmware staging succeeded.',
                        {'node': node.uuid, 'error': e})
            return None

        try:
            unfinished = (
                manager_oem.job_collection.get_unfinished_jobs())
            if jid in unfinished:
                LOG.info(
                    'Dell iDRAC: found scheduled LC job %(jid)s '
                    'for node %(node)s, firmware staging succeeded.',
                    {'jid': jid, 'node': node.uuid})
                return True
            LOG.warning(
                'Dell iDRAC: LC job %(jid)s not found among '
                'unfinished jobs for node %(node)s. The firmware '
                'download or staging likely failed.',
                {'jid': jid, 'node': node.uuid})
            return False
        except Exception as e:
            LOG.warning(
                'Failed to query Dell iDRAC job collection for '
                'node %(node)s: %(error)s. Falling back to '
                'assuming firmware staging succeeded.',
                {'node': node.uuid, 'error': e})
            return None

    return None
