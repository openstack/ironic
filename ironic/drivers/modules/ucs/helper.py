#    Copyright 2015, Cisco Systems.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Ironic Cisco UCSM helper functions
"""

from oslo_log import log as logging
from oslo_utils import importutils
import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules import deploy_utils

ucs_helper = importutils.try_import('UcsSdk.utils.helper')
ucs_error = importutils.try_import('UcsSdk.utils.exception')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'ucs_address': _('IP or Hostname of the UCS Manager. Required.'),
    'ucs_username': _('UCS Manager admin/server-profile username. Required.'),
    'ucs_password': _('UCS Manager password. Required.'),
    'ucs_service_profile': _('UCS Manager service-profile name. Required.')
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES


def requires_ucs_client(func):
    """Creates handle to connect to UCS Manager.

    This method is being used as a decorator method. It establishes connection
    with UCS Manager. And creates a session. Any method that has to perform
    operation on UCS Manager, requries this session, which can use this method
    as decorator method. Use this method as decorator method requires having
    helper keyword argument in the definition.

    :param func: function using this as a decorator.
    :returns: a wrapper function that performs the required tasks
        mentioned above before and after calling the actual function.
    """

    @six.wraps(func)
    def wrapper(self, task, *args, **kwargs):
        if kwargs.get('helper') is None:
            kwargs['helper'] = CiscoUcsHelper(task)
        try:
            kwargs['helper'].connect_ucsm()
            return func(self, task, *args, **kwargs)
        finally:
            kwargs['helper'].logout()
    return wrapper


def parse_driver_info(node):
    """Parses and creates Cisco driver info

    :param node: An Ironic node object.
    :returns: dictonary that contains node.driver_info parameter/values.
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


class CiscoUcsHelper(object):
    """Cisco UCS helper. Performs session managemnt."""

    def __init__(self, task):
        """Initialize with UCS Manager details.

        :param task: instance of `ironic.manager.task_manager.TaskManager`.
        """

        info = parse_driver_info(task.node)
        self.address = info['ucs_address']
        self.username = info['ucs_username']
        self.password = info['ucs_password']
        # service_profile is used by the utilities functions in UcsSdk.utils.*.
        self.service_profile = info['ucs_service_profile']
        self.handle = None
        self.uuid = task.node.uuid

    def connect_ucsm(self):
        """Creates the UcsHandle

        :raises: UcsConnectionError, if ucs helper fails to establish session
            with UCS Manager.
        """

        try:
            success, self.handle = ucs_helper.generate_ucsm_handle(
                self.address,
                self.username,
                self.password)
        except ucs_error.UcsConnectionError as ucs_exception:
            LOG.error("Cisco client: service unavailable for node "
                      "%(uuid)s.", {'uuid': self.uuid})
            raise exception.UcsConnectionError(error=ucs_exception,
                                               node=self.uuid)

    def logout(self):
        """Logouts the current active session."""

        if self.handle:
            self.handle.Logout()
