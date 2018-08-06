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

import mock

from ironic.common import boot_devices
from ironic.common import exception
from ironic.drivers.modules import noop_mgmt
from ironic.tests import base


class TestNoopManagement(base.TestCase):
    iface = noop_mgmt.NoopManagement()

    def test_dummy_methods(self):
        self.assertEqual({}, self.iface.get_properties())
        self.assertIsNone(self.iface.validate("task"))
        self.assertEqual([boot_devices.PXE, boot_devices.DISK],
                         self.iface.get_supported_boot_devices("task"))
        self.assertEqual({'boot_device': boot_devices.PXE,
                          'persistent': True},
                         self.iface.get_boot_device("task"))

    def test_set_boot_device(self):
        self.iface.set_boot_device(mock.Mock(), boot_devices.DISK)
        self.assertRaises(exception.InvalidParameterValue,
                          self.iface.set_boot_device, mock.Mock(),
                          boot_devices.CDROM)
