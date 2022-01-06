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

from ironic.common import exception
from ironic.drivers.modules.redfish import firmware_utils
from ironic.tests import base


class FirmwareUtilsTestCase(base.TestCase):

    def test_validate_update_firmware_args(self):
        firmware_images = [
            {
                "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                "wait": 300
            },
            {
                "url": "https://192.0.2.10/NIC_19.0.12_A00.EXE"
            }
        ]
        firmware_utils.validate_update_firmware_args(firmware_images)

    def test_validate_update_firmware_args_not_list(self):
        firmware_images = {
            "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
            "wait": 300
        }
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "is not of type 'array'",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_unknown_key(self):
        firmware_images = [
            {
                "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                "wait": 300,
            },
            {
                "url": "https://192.0.2.10/NIC_19.0.12_A00.EXE",
                "something": "unknown"
            }
        ]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "'something' was unexpected",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_url_missing(self):
        firmware_images = [
            {
                "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                "wait": 300,
            },
            {
                "wait": 300
            }
        ]
        self.assertRaisesRegex(
            exception.InvalidParameterValue,
            "'url' is a required property",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_url_not_string(self):
        firmware_images = [{
            "url": 123,
            "wait": 300
        }]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "123 is not of type 'string'",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_wait_not_int(self):
        firmware_images = [{
            "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
            "wait": 'abc'
        }]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "'abc' is not of type 'integer'",
            firmware_utils.validate_update_firmware_args, firmware_images)
