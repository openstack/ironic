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
DRAC Lifecycle job specific methods
"""

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules.drac import common as drac_common

drac_exceptions = importutils.try_import('dracclient.exceptions')

LOG = logging.getLogger(__name__)


def validate_job_queue(node, name_prefix=None):
    """Validates the job queue on the node.

    It raises an exception if an unfinished configuration job exists.

    :param node: an ironic node object.
    :param name_prefix: A name prefix for jobs to validate.
    :raises: DracOperationError on an error from python-dracclient.
    """

    unfinished_jobs = list_unfinished_jobs(node)
    if name_prefix is not None:
        # Filter out jobs that don't match the name prefix.
        unfinished_jobs = [job for job in unfinished_jobs
                           if job.name.startswith(name_prefix)]
    if not unfinished_jobs:
        return
    msg = _('Unfinished config jobs found: %(jobs)r. Make sure they are '
            'completed before retrying.') % {'jobs': unfinished_jobs}
    raise exception.DracOperationError(error=msg)


def get_job(node, job_id):
    """Get the details of a Lifecycle job of the node.

    :param node: an ironic node object.
    :param job_id: ID of the Lifecycle job.
    :returns: a Job object from dracclient.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.get_job(job_id)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the job %(job_id)s '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def list_unfinished_jobs(node):
    """List unfinished config jobs of the node.

    :param node: an ironic node object.
    :returns: a list of Job objects from dracclient.
    :raises: DracOperationError on an error from python-dracclient.
    """
    client = drac_common.get_drac_client(node)

    try:
        return client.list_jobs(only_unfinished=True)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the list of unfinished jobs '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)
