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
Ironic Cisco UCSM interfaces.
Provides Management interface operations of servers managed by Cisco UCSM using
PyUcs Sdk.
"""

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules.ucs import helper as ucs_helper

ucs_error = importutils.try_import('UcsSdk.utils.exception')
ucs_mgmt = importutils.try_import('UcsSdk.utils.management')


LOG = logging.getLogger(__name__)

UCS_TO_IRONIC_BOOT_DEVICE = {
    'storage': boot_devices.DISK,
    'disk': boot_devices.DISK,
    'pxe': boot_devices.PXE,
    'read-only-vm': boot_devices.CDROM,
    'cdrom': boot_devices.CDROM
}


class UcsManagement(base.ManagementInterface):

    def get_properties(self):
        return ucs_helper.COMMON_PROPERTIES

    def validate(self, task):
        """Check that 'driver_info' contains UCSM login credentials.

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required credentials information.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        """

        ucs_helper.parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
              in :mod:`ironic.common.boot_devices`.
        """

        return list(set(UCS_TO_IRONIC_BOOT_DEVICE.values()))

    @ucs_helper.requires_ucs_client
    def set_boot_device(self, task, device, persistent=False, helper=None):
        """Set the boot device for the task's node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of 'PXE, DISK or CDROM'.
        :param persistent: Boolean value. True if the boot device will
            persist to all future boots, False if not.
            Default: False. Ignored by this driver.
        :param helper: ucs helper instance.
        :raises: MissingParameterValue if required CiscoDriver parameters
            are missing.
        :raises: UcsOperationError on error from UCS client.
            setting the boot device.

        """

        try:
            mgmt_handle = ucs_mgmt.BootDeviceHelper(helper)
            mgmt_handle.set_boot_device(device, persistent)
        except ucs_error.UcsOperationError as ucs_exception:
            LOG.error("%(driver)s: client failed to set boot device "
                      "%(device)s for node %(uuid)s.",
                      {'driver': task.node.driver, 'device': device,
                          'uuid': task.node.uuid})
            operation = _('setting boot device')
            raise exception.UcsOperationError(operation=operation,
                                              error=ucs_exception,
                                              node=task.node.uuid)
        LOG.debug("Node %(uuid)s set to boot from %(device)s.",
                  {'uuid': task.node.uuid, 'device': device})

    @ucs_helper.requires_ucs_client
    def get_boot_device(self, task, helper=None):
        """Get the current boot device for the task's node.

        Provides the current boot device of the node.

        :param task: a task from TaskManager.
        :param helper: ucs helper instance.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` [PXE, DISK, CDROM] or
                None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.
        :raises: MissingParameterValue if a required UCS parameter is missing.
        :raises: UcsOperationError on error from UCS client, while setting the
            boot device.
        """

        try:
            mgmt_handle = ucs_mgmt.BootDeviceHelper(helper)
            boot_device = mgmt_handle.get_boot_device()
        except ucs_error.UcsOperationError as ucs_exception:
            LOG.error("%(driver)s: client failed to get boot device for "
                      "node %(uuid)s.",
                      {'driver': task.node.driver, 'uuid': task.node.uuid})
            operation = _('getting boot device')
            raise exception.UcsOperationError(operation=operation,
                                              error=ucs_exception,
                                              node=task.node.uuid)
        boot_device['boot_device'] = (
            UCS_TO_IRONIC_BOOT_DEVICE[boot_device['boot_device']])
        return boot_device

    def get_sensors_data(self, task):
        """Get sensors data.

        Not implemented by this driver.
        :param task: a TaskManager instance.
        """

        raise NotImplementedError()
