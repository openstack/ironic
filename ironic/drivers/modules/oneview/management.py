#
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.oneview import common

LOG = logging.getLogger(__name__)

BOOT_DEVICE_MAPPING_TO_OV = {
    boot_devices.DISK: 'HardDisk',
    boot_devices.PXE: 'PXE',
    boot_devices.CDROM: 'CD',
}

BOOT_DEVICE_OV_TO_GENERIC = {
    v: k
    for k, v in BOOT_DEVICE_MAPPING_TO_OV.items()
}

oneview_exceptions = importutils.try_import('oneview_client.exceptions')


class OneViewManagement(base.ManagementInterface):

    def get_properties(self):
        return common.COMMON_PROPERTIES

    def validate(self, task):
        """Checks required info on 'driver_info' and validates node with OneView

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required info such as server_hardware_uri,
        server_hardware_type, server_profile_template_uri and
        enclosure_group_uri. Also, checks if the server profile of the node is
        applied, if NICs are valid for the server profile of the node, and if
        the server hardware attributes (ram, memory, vcpus count) are
        consistent with OneView.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if parameters set are inconsistent with
                 resources in OneView
        """

        common.verify_node_info(task.node)

        try:
            common.validate_oneview_resources_compatibility(task)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)

    def get_supported_boot_devices(self, task):
        """Gets a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """

        return sorted(BOOT_DEVICE_MAPPING_TO_OV.keys())

    @task_manager.require_exclusive_lock
    @common.node_has_server_profile
    def set_boot_device(self, task, device, persistent=False):
        """Sets the boot device for a node.

        Sets the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of the supported devices
                       listed in :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: OperationNotPermitted if the server has no server profile or
                 if the server is already powered on.
        :raises: OneViewError if the communication with OneView fails
        """
        oneview_info = common.get_oneview_info(task.node)

        if device not in self.get_supported_boot_devices(task):
            raise exception.InvalidParameterValue(
                _("Invalid boot device %s specified.") % device)

        LOG.debug("Setting boot device to %(device)s for node %(node)s",
                  {"device": device, "node": task.node.uuid})
        try:
            oneview_client = common.get_oneview_client()
            device_to_oneview = BOOT_DEVICE_MAPPING_TO_OV.get(device)
            oneview_client.set_boot_device(oneview_info, device_to_oneview)
        except oneview_exceptions.OneViewException as oneview_exc:
            msg = (_(
                "Error setting boot device on OneView. Error: %s")
                % oneview_exc
            )
            raise exception.OneViewError(error=msg)

    @common.node_has_server_profile
    def get_boot_device(self, task):
        """Get the current boot device for the task's node.

        Provides the current boot device of the node.

        :param task: a task from TaskManager.
        :returns: a dictionary containing:
            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` [PXE, DISK, CDROM]
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.
        :raises: OperationNotPermitted if no Server Profile is associated with
        the node
        :raises: InvalidParameterValue if the boot device is unknown
        :raises: OneViewError if the communication with OneView fails
        """
        oneview_info = common.get_oneview_info(task.node)

        try:
            oneview_client = common.get_oneview_client()
            boot_order = oneview_client.get_boot_order(oneview_info)
        except oneview_exceptions.OneViewException as oneview_exc:
            msg = (_(
                "Error getting boot device from OneView. Error: %s")
                % oneview_exc
            )
            raise exception.OneViewError(msg)

        primary_device = boot_order[0]
        if primary_device not in BOOT_DEVICE_OV_TO_GENERIC:
            raise exception.InvalidParameterValue(
                _("Unsupported boot Device %(device)s for Node: %(node)s")
                % {"device": primary_device, "node": task.node.uuid}
            )

        boot_device = {
            'boot_device': BOOT_DEVICE_OV_TO_GENERIC.get(primary_device),
            'persistent': True,
        }

        return boot_device

    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented by this driver.
        :param task: a TaskManager instance.
        """
        raise NotImplementedError()
