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

import enum

from oslo_log import log as logging
import sushy

from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = logging.getLogger(__name__)

# Prefix of a Lifecycle Controller job identity (JID).
_JID_PREFIX = 'JID_'


class LCJobStatus(enum.Enum):
    """Combined status of a set of Lifecycle Controller jobs."""

    DONE = 'done'
    """Every job finished successfully."""

    RUNNING = 'running'
    """At least one job has not finished yet."""

    ERROR = 'error'
    """Every job finished, and at least one failed or cannot be found."""

    UNAVAILABLE = 'unavailable'
    """The node offers no Dell OEM job collection to check."""


def jid_from_task_monitor(task_monitor_uri):
    """Get the Lifecycle Controller job ID from a task monitor URI.

    iDRAC names a firmware update task monitor after the job that
    performs the update: ``/redfish/v1/TaskService/TaskMonitors/JID_...``

    :param task_monitor_uri: a task monitor URI, or None.
    :returns: the JID, or None if the URI does not end in one.
    """
    if not task_monitor_uri:
        return None
    jid = task_monitor_uri.rstrip('/').rsplit('/', 1)[-1]
    return jid if jid.startswith(_JID_PREFIX) else None


def _get_dell_job_collection(task):
    """Get the Dell OEM Lifecycle Controller job collection for a node.

    :param task: a TaskManager instance
    :returns: a sushy DellJobCollection instance, or None if no manager
        of the node offers the Dell OEM extension with a job collection.
    :raises: RedfishError or RedfishConnectionError if the system cannot
        be read.
    :raises: sushy.exceptions.SushyError if the managers cannot be read,
        including MissingAttributeError when the system does not link
        its managers.
    """
    node = task.node
    system = redfish_utils.get_system(node)
    for manager in system.managers:
        try:
            manager_oem = manager.get_oem_extension('Dell')
        except (sushy.exceptions.OEMExtensionNotFoundError,
                sushy.exceptions.ExtensionError) as e:
            LOG.warning('Dell OEM extension is not available for '
                        'manager %(manager)s of node %(node)s: %(error)s',
                        {'manager': manager.identity, 'node': node.uuid,
                         'error': e})
            continue
        try:
            return manager_oem.job_collection
        except sushy.exceptions.MissingAttributeError as e:
            LOG.warning('Manager %(manager)s of node %(node)s does not link '
                        'a Dell job collection: %(error)s',
                        {'manager': manager.identity, 'node': node.uuid,
                         'error': e})

    return None


def check_scheduled_idrac_job(task, current_update):
    """Check Dell iDRAC for a scheduled Lifecycle Controller job.

    Used when the Redfish task of a firmware update disappears before
    Ironic sees it finish. If the job is still scheduled or running, the
    firmware is staged and the next reboot applies it. If the job has
    finished or does not exist, nothing is left to apply.

    :param task: a TaskManager instance
    :param current_update: the current firmware update being processed
    :returns: True if the job is still scheduled or running, False if it
        has finished (successfully or not) or does not exist, None if
        the task monitor does not name a job or the Dell OEM job
        collection is not available
    :raises: RedfishError, RedfishConnectionError or
        sushy.exceptions.SushyError if the job collection cannot be read;
        the job may still exist, so the caller should check again later.
    """
    node = task.node
    jid = jid_from_task_monitor(current_update.get('task_monitor'))
    if not jid:
        LOG.warning('Task monitor %(uri)s of node %(node)s does not refer '
                    'to a Lifecycle Controller job, so the job cannot be '
                    'checked.',
                    {'uri': current_update.get('task_monitor'),
                     'node': node.uuid})
        return None

    status, detail = check_lc_jobs(task, [jid])
    if status == LCJobStatus.UNAVAILABLE:
        return None
    if status == LCJobStatus.RUNNING:
        LOG.debug('Found scheduled LC job %(jid)s for node %(node)s, '
                  'firmware staging succeeded.',
                  {'jid': jid, 'node': node.uuid})
        return True
    if status == LCJobStatus.ERROR:
        LOG.warning('LC job %(jid)s for node %(node)s did not leave '
                    'firmware to apply: %(detail)s',
                    {'jid': jid, 'node': node.uuid, 'detail': detail})
    else:
        LOG.debug('LC job %(jid)s for node %(node)s has already '
                  'finished.', {'jid': jid, 'node': node.uuid})
    return False


def _classify_dell_jobs(jids, jobs):
    """Classify DellJob objects into failed/running/done for `jids`.

    The outcome of a job is taken from sushy's DellJob.is_failed and
    DellJob.is_finished, so the set of terminal and failed Lifecycle
    Controller job states is maintained in sushy alone. A job missing
    from the collection has no outcome to report, so it counts as
    failed: it never counts as done.

    :param jids: a list of JIDs to check
    :param jobs: a list of sushy DellJob objects, as returned by
        DellJobCollection.get_jobs()
    :returns: a tuple (status, detail), status is one of
        LCJobStatus.DONE, LCJobStatus.RUNNING, LCJobStatus.ERROR
    """
    jobs_by_id = {job.identity: job for job in jobs}

    failed = []
    running = []
    for jid in jids:
        job = jobs_by_id.get(jid)
        if job is None:
            failed.append('%s: not found in the job queue' % jid)
        elif job.is_failed:
            failed.append('%s: %s - %s' % (
                jid, job.job_state, job.message or 'unknown error'))
        elif not job.is_finished:
            running.append(jid)

    # Report an error only once every job has stopped, so that nothing is
    # still being applied when the caller acts on the failure.
    if running:
        return LCJobStatus.RUNNING, ', '.join(running)

    if failed:
        return LCJobStatus.ERROR, '; '.join(failed)

    return LCJobStatus.DONE, None


def check_lc_jobs(task, jids):
    """Check the status of one or more Dell Lifecycle Controller jobs.

    :param task: a TaskManager instance
    :param jids: an iterable of Dell LC job IDs (JIDs) to check
    :returns: a tuple (status, detail) with an LCJobStatus. detail is
        a comma-separated list of still-running JIDs for RUNNING, a
        description of the failed or missing job(s) for ERROR, and None
        for DONE and UNAVAILABLE
    :raises: RedfishError, RedfishConnectionError or
        sushy.exceptions.SushyError if the jobs cannot be read. A read
        failure says nothing about the jobs, so callers should check
        again later rather than treat it as any status.
    """
    node = task.node
    jids = list(jids)
    if not jids:
        return LCJobStatus.DONE, None

    job_collection = _get_dell_job_collection(task)
    if job_collection is None:
        LOG.warning('Cannot check LC jobs %(jids)s for node %(node)s: OEM '
                    'job collection unavailable.',
                    {'jids': jids, 'node': node.uuid})
        return LCJobStatus.UNAVAILABLE, None

    return _classify_dell_jobs(jids, job_collection.get_jobs(job_ids=jids))
