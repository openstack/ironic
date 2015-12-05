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

import mock

from oslo_utils import importutils
from six.moves import http_client

from ironic.common import boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.cimc import common
from ironic.tests.unit.drivers.modules.cimc import test_common

imcsdk = importutils.try_import('ImcSdk')


@mock.patch.object(common, 'cimc_handle', autospec=True)
class CIMCManagementTestCase(test_common.CIMCBaseTestCase):

    def test_get_properties(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertEqual(common.COMMON_PROPERTIES,
                             task.driver.management.get_properties())

    @mock.patch.object(common, "parse_driver_info", autospec=True)
    def test_validate(self, mock_driver_info, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.validate(task)
            mock_driver_info.assert_called_once_with(task.node)

    def test_get_supported_boot_devices(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM]
            result = task.driver.management.get_supported_boot_devices(task)
            self.assertEqual(sorted(expected), sorted(result))

    def test_get_boot_device(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.xml_query.return_value.error_code = None
                mock_dev = mock.MagicMock()
                mock_dev.Order = 1
                mock_dev.Rn = 'storage-read-write'
                handle.xml_query().OutConfigs.child[0].child = [mock_dev]

                device = task.driver.management.get_boot_device(task)
                self.assertEqual(
                    {'boot_device': boot_devices.DISK, 'persistent': True},
                    device)

    def test_get_boot_device_fail(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.xml_query.return_value.error_code = None
                mock_dev = mock.MagicMock()
                mock_dev.Order = 1
                mock_dev.Rn = 'storage-read-write'
                handle.xml_query().OutConfigs.child[0].child = [mock_dev]

                device = task.driver.management.get_boot_device(task)

                self.assertEqual(
                    {'boot_device': boot_devices.DISK, 'persistent': True},
                    device)

    def test_set_boot_device(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.xml_query.return_value.error_code = None
                task.driver.management.set_boot_device(task, boot_devices.DISK)
                method = imcsdk.ImcCore.ExternalMethod("ConfigConfMo")
                method.Cookie = handle.cookie
                method.Dn = "sys/rack-unit-1/boot-policy"
                method.InHierarchical = "true"

                config = imcsdk.Imc.ConfigConfig()

                bootMode = imcsdk.ImcCore.ManagedObject('lsbootStorage')
                bootMode.set_attr("access", 'read-write')
                bootMode.set_attr("type", 'storage')
                bootMode.set_attr("Rn", 'storage-read-write')
                bootMode.set_attr("order", "1")

                config.add_child(bootMode)
                method.InConfig = config

                handle.xml_query.assert_called_once_with(
                    method, imcsdk.WriteXmlOption.DIRTY)

    def test_set_boot_device_fail(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                method = imcsdk.ImcCore.ExternalMethod("ConfigConfMo")
                handle.xml_query.return_value.error_code = (
                    str(http_client.NOT_FOUND))

                self.assertRaises(exception.CIMCException,
                                  task.driver.management.set_boot_device,
                                  task, boot_devices.DISK)

                handle.xml_query.assert_called_once_with(
                    method, imcsdk.WriteXmlOption.DIRTY)

    def test_get_sensors_data(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(NotImplementedError,
                              task.driver.management.get_sensors_data, task)
