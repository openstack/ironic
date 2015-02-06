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
AMT Management Driver
"""
import copy

from oslo_utils import excutils
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.amt import common as amt_common
from ironic.drivers.modules.amt import resource_uris
from ironic.openstack.common import log as logging

pywsman = importutils.try_import('pywsman')

LOG = logging.getLogger(__name__)


def _set_boot_device_order(node, boot_device):
    """Set boot device order configuration of AMT Client.

    :param node: a node object
    :param boot_device: the boot device
    :raises: AMTFailure
    :raises: AMTConnectFailure
    """
    client = amt_common.get_wsman_client(node)
    source = pywsman.EndPointReference(resource_uris.CIM_BootSourceSetting,
                                       None)
    device = amt_common.BOOT_DEVICES_MAPPING[boot_device]
    source.add_selector('InstanceID', device)

    method = 'ChangeBootOrder'

    options = pywsman.ClientOptions()
    options.add_selector('InstanceID', 'Intel(r) AMT: Boot Configuration 0')

    options.add_property('Source', source)
    try:
        client.wsman_invoke(options, resource_uris.CIM_BootConfigSetting,
                            method)
    except (exception.AMTFailure, exception.AMTConnectFailure) as e:
        with excutils.save_and_reraise_exception():
            LOG.exception(_LE("Failed to set boot device %(boot_device)s for "
                              "node %(node_id)s with error: %(error)s."),
                          {'boot_device': boot_device, 'node_id': node.uuid,
                           'error': e})
    else:
        LOG.info(_LI("Successfully set boot device %(boot_device)s for "
                     "node %(node_id)s"),
                 {'boot_device': boot_device, 'node_id': node.uuid})


def _enable_boot_config(node):
    """Enable boot configuration of AMT Client.

    :param node: a node object
    :raises: AMTFailure
    :raises: AMTConnectFailure
    """
    client = amt_common.get_wsman_client(node)
    config = pywsman.EndPointReference(resource_uris.CIM_BootConfigSetting,
                                       None)
    config.add_selector('InstanceID', 'Intel(r) AMT: Boot Configuration 0')

    method = 'SetBootConfigRole'

    options = pywsman.ClientOptions()
    options.add_selector('Name', 'Intel(r) AMT Boot Service')

    options.add_property('Role', '1')
    options.add_property('BootConfigSetting', config)
    try:
        client.wsman_invoke(options, resource_uris.CIM_BootService, method)
    except (exception.AMTFailure, exception.AMTConnectFailure) as e:
        with excutils.save_and_reraise_exception():
            LOG.exception(_LE("Failed to enable boot config for node "
                              "%(node_id)s with error: %(error)s."),
                          {'node_id': node.uuid, 'error': e})
    else:
        LOG.info(_LI("Successfully enabled boot config for node %(node_id)s."),
                 {'node_id': node.uuid})


class AMTManagement(base.ManagementInterface):

    def get_properties(self):
        return copy.deepcopy(amt_common.COMMON_PROPERTIES)

    def validate(self, task):
        """Validate the driver_info in the node

        Check if the driver_info contains correct required fields

        :param task: a TaskManager instance contains the target node
        :raises: MissingParameterValue if any required parameters are missing.
        :raises: InvalidParameterValue if any parameters have invalid values.
        """
        # FIXME(lintan): validate hangs if unable to reach AMT, so dont
        # connect to the node until bug 1314961 is resolved.
        amt_common.parse_driver_info(task.node)

    def get_supported_boot_devices(self):
        """Get a list of the supported boot devices.

        :returns: A list with the supported boot devices.
        """
        return list(amt_common.BOOT_DEVICES_MAPPING)

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for the task's node.

        Set the boot device to use on next boot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified.
        """
        node = task.node

        if device not in amt_common.BOOT_DEVICES_MAPPING:
            raise exception.InvalidParameterValue(_("set_boot_device called "
                    "with invalid device %(device)s for node %(node_id)s.") %
                    {'device': device, 'node_id': node.uuid})

        # AMT/vPro doesnt support set boot_device persistent, so we have to
        # save amt_boot_device/amt_boot_persistent in driver_internal_info.
        driver_internal_info = node.driver_internal_info
        driver_internal_info['amt_boot_device'] = device
        driver_internal_info['amt_boot_persistent'] = persistent
        node.driver_internal_info = driver_internal_info
        node.save()

    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :returns: a dictionary containing:
            :boot_device: the boot device
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.
        """
        driver_internal_info = task.node.driver_internal_info
        device = driver_internal_info.get('amt_boot_device')
        persistent = driver_internal_info.get('amt_boot_persistent')
        if not device:
            device = amt_common.DEFAULT_BOOT_DEVICE
            persistent = True
        return {'boot_device': device,
                'persistent': persistent}

    def ensure_next_boot_device(self, node, boot_device):
        """Set next boot device (one time only) of AMT Client.

        :param node: a node object
        :param boot_device: the boot device
        :raises: AMTFailure
        :raises: AMTConnectFailure
        """
        driver_internal_info = node.driver_internal_info
        if not driver_internal_info.get('amt_boot_persistent'):
            driver_internal_info['amt_boot_device'] = (
                                amt_common.DEFAULT_BOOT_DEVICE)
            driver_internal_info['amt_boot_persistent'] = True
            node.driver_internal_info = driver_internal_info
            node.save()

        _set_boot_device_order(node, boot_device)
        _enable_boot_config(node)

    def get_sensors_data(self, task):
        raise NotImplementedError()
