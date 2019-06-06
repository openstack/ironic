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
DRAC BIOS configuration specific methods
"""

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job

drac_exceptions = importutils.try_import('dracclient.exceptions')

LOG = logging.getLogger(__name__)


def get_config(node):
    """Get the BIOS configuration.

    The BIOS settings look like::

        {'EnumAttrib': {'name': 'EnumAttrib',
                        'current_value': 'Value',
                        'pending_value': 'New Value', # could also be None
                        'read_only': False,
                        'possible_values': ['Value', 'New Value', 'None']},
         'StringAttrib': {'name': 'StringAttrib',
                          'current_value': 'Information',
                          'pending_value': None,
                          'read_only': False,
                          'min_length': 0,
                          'max_length': 255,
                          'pcre_regex': '^[0-9A-Za-z]{0,255}$'},
         'IntegerAttrib': {'name': 'IntegerAttrib',
                           'current_value': 0,
                           'pending_value': None,
                           'read_only': True,
                           'lower_bound': 0,
                           'upper_bound': 65535}}

    :param node: an ironic node object.
    :raises: DracOperationError on an error from python-dracclient.
    :returns: a dictionary containing BIOS settings

    The above values are only examples, of course.  BIOS attributes exposed via
    this API will always be either an enumerated attribute, a string attribute,
    or an integer attribute.  All attributes have the following parameters:

    :param name: is the name of the BIOS attribute.
    :param current_value: is the current value of the attribute.
                          It will always be either an integer or a string.
    :param pending_value: is the new value that we want the attribute to have.
                          None means that there is no pending value.
    :param read_only: indicates whether this attribute can be changed.
                      Trying to change a read-only value will result in
                      an error. The read-only flag can change depending
                      on other attributes.
                      A future version of this call may expose the
                      dependencies that indicate when that may happen.

    Enumerable attributes also have the following parameters:

    :param possible_values: is an array of values it is permissible to set
                            the attribute to.

    String attributes also have the following parameters:

    :param min_length: is the minimum length of the string.
    :param max_length: is the maximum length of the string.
    :param pcre_regex: is a PCRE compatible regular expression that the string
                       must match.  It may be None if the string is read only
                       or if the string does not have to match any particular
                       regular expression.

    Integer attributes also have the following parameters:

    :param lower_bound: is the minimum value the attribute can have.
    :param upper_bound: is the maximum value the attribute can have.
    """

    client = drac_common.get_drac_client(node)

    try:
        return client.list_bios_settings()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to get the BIOS settings for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def set_config(task, **kwargs):
    """Sets the pending_value parameter for each of the values passed in.

    :param task: a TaskManager instance containing the node to act on.
    :param kwargs: a dictionary of {'AttributeName': 'NewValue'}
    :raises: DracOperationError on an error from python-dracclient.
    :returns: A dictionary containing the 'is_commit_required' key with a
              boolean value indicating whether commit_config() needs to be
              called to make the changes, and the 'is_reboot_required' key
              which has a value of 'true' or 'false'.  This key is used to
              indicate to the commit_config() call if a reboot should be
              performed.
    """
    node = task.node
    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)
    if 'http_method' in kwargs:
        del kwargs['http_method']

    try:
        return client.set_bios_settings(kwargs)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to set the BIOS settings for node '
                  '%(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def commit_config(task, reboot=False):
    """Commits pending changes added by set_config

    :param task: a TaskManager instance containing the node to act on.
    :param reboot: indicates whether a reboot job should be automatically
                   created with the config job.
    :raises: DracOperationError on an error from python-dracclient.
    :returns: the job_id key with the id of the newly created config job.
    """
    node = task.node
    drac_job.validate_job_queue(node)

    client = drac_common.get_drac_client(node)

    try:
        return client.commit_pending_bios_changes(reboot)
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to commit the pending BIOS changes '
                  'for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)


def abandon_config(task):
    """Abandons uncommitted changes added by set_config

    :param task: a TaskManager instance containing the node to act on.
    :raises: DracOperationError on an error from python-dracclient.
    """
    node = task.node
    client = drac_common.get_drac_client(node)

    try:
        client.abandon_pending_bios_changes()
    except drac_exceptions.BaseClientException as exc:
        LOG.error('DRAC driver failed to delete the pending BIOS '
                  'settings for node %(node_uuid)s. Reason: %(error)s.',
                  {'node_uuid': node.uuid,
                   'error': exc})
        raise exception.DracOperationError(error=exc)
