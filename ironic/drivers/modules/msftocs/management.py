# Copyright 2015 Cloudbase Solutions Srl
# All Rights Reserved.
#
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

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.msftocs import common as msftocs_common
from ironic.drivers.modules.msftocs import msftocsclient
from ironic.drivers import utils as drivers_utils

BOOT_TYPE_TO_DEVICE_MAP = {
    msftocsclient.BOOT_TYPE_FORCE_PXE: boot_devices.PXE,
    msftocsclient.BOOT_TYPE_FORCE_DEFAULT_HDD: boot_devices.DISK,
    msftocsclient.BOOT_TYPE_FORCE_INTO_BIOS_SETUP: boot_devices.BIOS,
}
DEVICE_TO_BOOT_TYPE_MAP = {v: k for k, v in BOOT_TYPE_TO_DEVICE_MAP.items()}

DEFAULT_BOOT_DEVICE = boot_devices.DISK


class MSFTOCSManagement(base.ManagementInterface):
    def get_properties(self):
        """Returns the driver's properties."""
        return msftocs_common.get_properties()

    def validate(self, task):
        """Validate the driver_info in the node.

        Check if the driver_info contains correct required fields.

        :param task: a TaskManager instance containing the target node.
        :raises: MissingParameterValue if any required parameters are missing.
        :raises: InvalidParameterValue if any parameters have invalid values.
        """
        msftocs_common.parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices.
        """
        return list(BOOT_TYPE_TO_DEVICE_MAP.values())

    def _check_valid_device(self, device, node):
        """Checks if the desired boot device is valid for this driver.

        :param device: a boot device.
        :param node: the target node.
        :raises: InvalidParameterValue if the boot device is not valid.
        """
        if device not in DEVICE_TO_BOOT_TYPE_MAP:
            raise exception.InvalidParameterValue(
                _("set_boot_device called with invalid device %(device)s for "
                  "node %(node_id)s.") %
                {'device': device, 'node_id': node.uuid})

    @task_manager.require_exclusive_lock
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for the task's node.

        Set the boot device to use on next boot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is specified.
        """
        self._check_valid_device(device, task.node)
        client, blade_id = msftocs_common.get_client_info(
            task.node.driver_info)

        boot_mode = drivers_utils.get_node_capability(task.node, 'boot_mode')
        uefi = (boot_mode == 'uefi')

        boot_type = DEVICE_TO_BOOT_TYPE_MAP[device]
        client.set_next_boot(blade_id, boot_type, persistent, uefi)

    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Returns the current boot device of the node.

        :param task: a task from TaskManager.
        :returns: a dictionary containing:

            :boot_device: the boot device
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        client, blade_id = msftocs_common.get_client_info(
            task.node.driver_info)
        device = BOOT_TYPE_TO_DEVICE_MAP.get(
            client.get_next_boot(blade_id), DEFAULT_BOOT_DEVICE)

        # Note(alexpilotti): Although the ChasssisManager REST API allows to
        # specify the persistent boot status in SetNextBoot, currently it does
        # not provide a way to retrieve the value with GetNextBoot.
        # This is being addressed in the ChassisManager API.
        return {'boot_device': device,
                'persistent': None}

    def get_sensors_data(self, task):
        raise NotImplementedError()
