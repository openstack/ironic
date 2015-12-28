# Copyright 2015, Cisco Systems.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from contextlib import contextmanager

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules import deploy_utils

REQUIRED_PROPERTIES = {
    'cimc_address': _('IP or Hostname of the CIMC. Required.'),
    'cimc_username': _('CIMC Manager admin username. Required.'),
    'cimc_password': _('CIMC Manager password. Required.'),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES

imcsdk = importutils.try_import('ImcSdk')


def parse_driver_info(node):
    """Parses and creates Cisco driver info.

    :param node: An Ironic node object.
    :returns: dictionary that contains node.driver_info parameter/values.
    :raises: MissingParameterValue if any required parameters are missing.
    """

    info = {}
    for param in REQUIRED_PROPERTIES:
        info[param] = node.driver_info.get(param)
    error_msg = (_("%s driver requires these parameters to be set in the "
                   "node's driver_info.") %
                 node.driver)
    deploy_utils.check_for_missing_params(info, error_msg)
    return info


def handle_login(task, handle, info):
    """Login to the CIMC handle.

    Run login on the CIMC handle, catching any ImcException and reraising
    it as an ironic CIMCException.

    :param handle: A CIMC handle.
    :param info: A list of driver info as produced by parse_driver_info.
    :raises: CIMCException if there error logging in.
    """
    try:
        handle.login(info['cimc_address'],
                     info['cimc_username'],
                     info['cimc_password'])
    except imcsdk.ImcException as e:
        raise exception.CIMCException(node=task.node.uuid, error=e)


@contextmanager
def cimc_handle(task):
    """Context manager for creating a CIMC handle and logging into it.

    :param task: The current task object.
    :raises: CIMCException if login fails
    :yields: A CIMC Handle for the node in the task.
    """
    info = parse_driver_info(task.node)
    handle = imcsdk.ImcHandle()

    handle_login(task, handle, info)
    try:
        yield handle
    finally:
        handle.logout()
