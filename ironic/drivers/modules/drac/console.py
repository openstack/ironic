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
Console functionality
"""

import secrets
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import importutils

from ironic.common import exception
from ironic.drivers import base
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)

sushy = importutils.try_import('sushy')
sushy_oem_idrac = importutils.try_import('sushy_oem_idrac')

_ENABLED = "Enabled"
_DISABLED = "Disabled"
_VNC_ENABLE_ATTRIBUTE = "VNCServer.1.Enable"
_VNC_PORT_ATTRIBUTE = "VNCServer.1.Port"
_VNC_PASSWORD_ATTRIBUTE = "VNCServer.1.Password"


class DracRedFishVNCConsole(base.ConsoleInterface):
    def __init__(self):
        """Initialize the Drac Redfish VNC console interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(DracRedFishVNCConsole, self).__init__()
        if not sushy:
            raise exception.DriverLoadError(
                driver='drac',
                reason=_('Unable to import the sushy library'))


    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the redfish driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        redfish_utils.parse_driver_info(task.node)

    def start_console(self, task):
        """Start a remote console for the task's node.

        This method should not raise an exception if console already started.

        :param task: A TaskManager instance containing the node to act on.
        """
        attributes = self._get_idrac_attributes(task)
        password = secrets.token_hex(4)
        attributes.set_attributes({
            _VNC_ENABLE_ATTRIBUTE: _ENABLED,
            _VNC_PASSWORD_ATTRIBUTE: password,
        })
        node = task.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info["vnc_password"] = password
        node.driver_internal_info = driver_internal_info
        node.save()

    def stop_console(self, task):
        """Stop the remote console session for the task's node.

        :param task: A TaskManager instance containing the node to act on.
        """
        attributes = self._get_idrac_attributes(task)
        if attributes.attributes[_VNC_ENABLE_ATTRIBUTE] != _DISABLED:
            attributes.set_attributes({
                _VNC_ENABLE_ATTRIBUTE: _DISABLED
            })
        node = task.node
        driver_internal_info = node.driver_internal_info
        password = driver_internal_info.pop("vnc_password", None)
        if password:
            node.driver_internal_info = driver_internal_info
            node.save()

    def get_console(self, task):
        """Get connection information about the console.

        This method should return the necessary information for the
        client to access the console.

        :param task: A TaskManager instance containing the node to act on.
        :returns: the console connection information.
        """
        attributes = self._get_idrac_attributes(task)
        port = attributes.attributes[_VNC_PORT_ATTRIBUTE]

        driver_info = task.node.driver_info
        address = driver_info['redfish_address']
        parsed = urlparse.urlparse(address)

        node = task.node
        driver_internal_info = node.driver_internal_info
        password = driver_internal_info["vnc_password"]

        return {'type': 'vnc',
                'url': f"vnc://:{password}@{parsed.hostname}:{port}"}

    @staticmethod
    def _get_idrac_attributes(task):
        manager = redfish_utils.get_manager(task.node)
        oem_manager = manager.get_oem_extension('Dell')
        for attributes in oem_manager.attributes:
            if attributes.identity == "iDRACAttributes":
                return attributes
        return None



class DracRedFishKVMConsole(base.ConsoleInterface):
    def __init__(self):
        """Initialize the Drac Redfish KVM console interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(DracRedFishKVMConsole, self).__init__()
        if not sushy:
            raise exception.DriverLoadError(
                driver='drac',
                reason=_('Unable to import the sushy library'))


    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validates the driver information needed by the redfish driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        redfish_utils.parse_driver_info(task.node)

    def start_console(self, task):
        """Start a remote console for the task's node.

        This method should not raise an exception if console already started.

        :param task: A TaskManager instance containing the node to act on.
        """
        pass

    def stop_console(self, task):
        """Stop the remote console session for the task's node.

        :param task: A TaskManager instance containing the node to act on.
        """
        pass

    def get_console(self, task):
        """Get connection information about the console.

        This method should return the necessary information for the
        client to access the console.

        :param task: A TaskManager instance containing the node to act on.
        :returns: the console connection information.
        """
        driver_info= task.node.driver_info
        address = driver_info['redfish_address']
        username = driver_info['redfish_username']

        manager = redfish_utils.get_manager(task.node)
        oem_manager = manager.get_oem_extension('Dell')
        idrac = oem_manager.idrac_card_service


        result = idrac.get_kvm_session()
        q = urlparse.urlencode({
            "username": username,
            "tempUsername": result["TempUsername"],
            "tempPassword": result["TempPassword"]})

        return {'type': 'kvm',
                'url': f"{address}/console?{q}"}

