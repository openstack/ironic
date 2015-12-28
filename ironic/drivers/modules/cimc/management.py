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

from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.drivers import base
from ironic.drivers.modules.cimc import common

imcsdk = importutils.try_import('ImcSdk')


CIMC_TO_IRONIC_BOOT_DEVICE = {
    'storage-read-write': boot_devices.DISK,
    'lan-read-only': boot_devices.PXE,
    'vm-read-only': boot_devices.CDROM
}

IRONIC_TO_CIMC_BOOT_DEVICE = {
    boot_devices.DISK: ('lsbootStorage', 'storage-read-write',
                        'storage', 'read-write'),
    boot_devices.PXE: ('lsbootLan', 'lan-read-only',
                       'lan', 'read-only'),
    boot_devices.CDROM: ('lsbootVirtualMedia', 'vm-read-only',
                         'virtual-media', 'read-only')
}


class CIMCManagement(base.ManagementInterface):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return common.COMMON_PROPERTIES

    def validate(self, task):
        """Check if node.driver_info contains the required CIMC credentials.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue if required CIMC credentials are
                 missing.
        """
        common.parse_driver_info(task.node)

    def get_supported_boot_devices(self, task):
        """Get a list of the supported boot devices.

        :param task: a task from TaskManager.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """
        return list(CIMC_TO_IRONIC_BOOT_DEVICE.values())

    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Provides the current boot device of the node. Be aware that not
        all drivers support this.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: CIMCException if there is an error from CIMC
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of :mod:`ironic.common.boot_devices` or
                None if it is unknown.
            :persistent:
                Whether the boot device will persist to all future boots or
                not, None if it is unknown.
        """

        with common.cimc_handle(task) as handle:
            method = imcsdk.ImcCore.ExternalMethod("ConfigResolveClass")
            method.Cookie = handle.cookie
            method.InDn = "sys/rack-unit-1"
            method.InHierarchical = "true"
            method.ClassId = "lsbootDef"

            try:
                resp = handle.xml_query(method, imcsdk.WriteXmlOption.DIRTY)
            except imcsdk.ImcException as e:
                raise exception.CIMCException(node=task.node.uuid, error=e)
            error = getattr(resp, 'error_code', None)
            if error:
                raise exception.CIMCException(node=task.node.uuid, error=error)

            bootDevs = resp.OutConfigs.child[0].child

            first_device = None
            for dev in bootDevs:
                try:
                    if int(dev.Order) == 1:
                        first_device = dev
                        break
                except (ValueError, AttributeError):
                    pass

            boot_device = (CIMC_TO_IRONIC_BOOT_DEVICE.get(
                first_device.Rn) if first_device else None)

            # Every boot device in CIMC is persistent right now
            persistent = True if boot_device else None
            return {'boot_device': boot_device, 'persistent': persistent}

    def set_boot_device(self, task, device, persistent=True):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Every boot device in CIMC is persistent right now,
                           so this value is ignored.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: CIMCException if there is an error from CIMC
        """

        with common.cimc_handle(task) as handle:
            dev = IRONIC_TO_CIMC_BOOT_DEVICE[device]

            method = imcsdk.ImcCore.ExternalMethod("ConfigConfMo")
            method.Cookie = handle.cookie
            method.Dn = "sys/rack-unit-1/boot-policy"
            method.InHierarchical = "true"

            config = imcsdk.Imc.ConfigConfig()

            bootMode = imcsdk.ImcCore.ManagedObject(dev[0])
            bootMode.set_attr("access", dev[3])
            bootMode.set_attr("type", dev[2])
            bootMode.set_attr("Rn", dev[1])
            bootMode.set_attr("order", "1")

            config.add_child(bootMode)
            method.InConfig = config

            try:
                resp = handle.xml_query(method, imcsdk.WriteXmlOption.DIRTY)
            except imcsdk.ImcException as e:
                raise exception.CIMCException(node=task.node.uuid, error=e)
            error = getattr(resp, 'error_code')
            if error:
                raise exception.CIMCException(node=task.node.uuid, error=error)

    def get_sensors_data(self, task):
        raise NotImplementedError()
