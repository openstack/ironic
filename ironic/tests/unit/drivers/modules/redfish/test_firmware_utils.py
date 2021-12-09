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

import os
import shutil
import tempfile
from unittest import mock
from urllib.parse import urlparse

from oslo_utils import fileutils

from ironic.common import exception
from ironic.common import image_service
from ironic.common import swift
from ironic.conf import CONF
from ironic.drivers.modules.redfish import firmware_utils
from ironic.tests import base


class FirmwareUtilsTestCase(base.TestCase):

    def test_validate_update_firmware_args(self):
        firmware_images = [
            {
                "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
                "wait": 300
            },
            {
                "url": "https://192.0.2.10/NIC_19.0.12_A00.EXE",
                "checksum": "9f6227549221920e312fed2cfc6586ee832cc546"
            }
        ]
        firmware_utils.validate_update_firmware_args(firmware_images)

    def test_validate_update_firmware_args_not_list(self):
        firmware_images = {
            "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
            "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
            "wait": 300
        }
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "is not of type 'array'",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_unknown_key(self):
        firmware_images = [
            {
                "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
                "wait": 300,
            },
            {
                "url": "https://192.0.2.10/NIC_19.0.12_A00.EXE",
                "checksum": "9f6227549221920e312fed2cfc6586ee832cc546",
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
                "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
                "wait": 300,
            },
            {
                "checksum": "9f6227549221920e312fed2cfc6586ee832cc546",
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
            "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
            "wait": 300
        }]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "123 is not of type 'string'",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_checksum_missing(self):
        firmware_images = [
            {
                "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
                "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
                "wait": 300,
            },
            {
                "url": "https://192.0.2.10/NIC_19.0.12_A00.EXE",
                "wait": 300
            }
        ]
        self.assertRaisesRegex(
            exception.InvalidParameterValue,
            "'checksum' is a required property",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_checksum_not_string(self):
        firmware_images = [{
            "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
            "checksum": 123,
            "wait": 300
        }]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "123 is not of type 'string'",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_wait_not_int(self):
        firmware_images = [{
            "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
            "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
            "wait": 'abc'
        }]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "'abc' is not of type 'integer'",
            firmware_utils.validate_update_firmware_args, firmware_images)

    def test_validate_update_firmware_args_source_not_known(self):
        firmware_images = [{
            "url": "http://192.0.2.10/BMC_4_22_00_00.EXE",
            "checksum": "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d",
            "source": "abc"
        }]
        self.assertRaisesRegex(
            exception.InvalidParameterValue, "'abc' is not one of",
            firmware_utils.validate_update_firmware_args, firmware_images)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_get_swift_temp_url(self, mock_swift_api):
        mock_swift_api.return_value.get_temp_url.return_value = 'http://temp'
        parsed_url = urlparse("swift://firmware/sub/bios.exe")

        result = firmware_utils.get_swift_temp_url(parsed_url)

        self.assertEqual(result, 'http://temp')
        mock_swift_api.return_value.get_temp_url.assert_called_with(
            'firmware', 'sub/bios.exe',
            CONF.redfish.swift_object_expiry_timeout)

    @mock.patch.object(tempfile, 'gettempdir', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(image_service, 'HttpImageService', autospec=True)
    def test_download_to_temp_http(
            self, mock_http_image_service, mock_makedirs, mock_gettempdir):
        node = mock.Mock(uuid='9f0f6795-f74e-4b5a-850e-72f586a92435')
        mock_gettempdir.return_value = '/tmp'
        http_url = 'http://example.com/bios.exe'

        with mock.patch.object(firmware_utils, 'open', mock.mock_open(),
                               create=True) as mock_open:
            result = firmware_utils.download_to_temp(node, http_url)

            exp_result = '/tmp/9f0f6795-f74e-4b5a-850e-72f586a92435/bios.exe'
            exp_temp_dir = '/tmp/9f0f6795-f74e-4b5a-850e-72f586a92435'
            mock_makedirs.assert_called_with(exp_temp_dir, exist_ok=True)
            self.assertEqual(result, exp_result)
            mock_http_image_service.return_value.download.assert_called_with(
                http_url, mock_open.return_value)
            mock_open.assert_has_calls([mock.call(exp_result, 'wb')])

    @mock.patch.object(tempfile, 'gettempdir', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(image_service, 'HttpImageService', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_download_to_temp_swift(
            self, mock_swift_api, mock_http_image_service, mock_makedirs,
            mock_gettempdir):
        node = mock.Mock(uuid='9f0f6795-f74e-4b5a-850e-72f586a92435')
        mock_gettempdir.return_value = '/tmp'
        swift_url = 'swift://firmware/sub/bios.exe'
        temp_swift_url = 'http://swift_temp'
        mock_swift_api.return_value.get_temp_url.return_value = temp_swift_url

        with mock.patch.object(firmware_utils, 'open', mock.mock_open(),
                               create=True) as mock_open:
            result = firmware_utils.download_to_temp(node, swift_url)

            exp_result = '/tmp/9f0f6795-f74e-4b5a-850e-72f586a92435/bios.exe'
            exp_temp_dir = '/tmp/9f0f6795-f74e-4b5a-850e-72f586a92435'
            mock_makedirs.assert_called_with(exp_temp_dir, exist_ok=True)
            self.assertEqual(result, exp_result)
            mock_http_image_service.return_value.download.assert_called_with(
                temp_swift_url, mock_open.return_value)
            mock_open.assert_has_calls([mock.call(exp_result, 'wb')])

    @mock.patch.object(tempfile, 'gettempdir', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(image_service, 'FileImageService', autospec=True)
    def test_download_to_temp_file(
            self, mock_file_image_service, mock_makedirs,
            mock_gettempdir):
        node = mock.Mock(uuid='9f0f6795-f74e-4b5a-850e-72f586a92435')
        mock_gettempdir.return_value = '/tmp'
        file_url = 'file:///firmware/bios.exe'

        with mock.patch.object(firmware_utils, 'open', mock.mock_open(),
                               create=True) as mock_open:
            result = firmware_utils.download_to_temp(node, file_url)

            exp_result = '/tmp/9f0f6795-f74e-4b5a-850e-72f586a92435/bios.exe'
            exp_temp_dir = '/tmp/9f0f6795-f74e-4b5a-850e-72f586a92435'
            mock_makedirs.assert_called_with(exp_temp_dir, exist_ok=True)
            self.assertEqual(result, exp_result)
            mock_file_image_service.return_value.download.assert_called_with(
                '/firmware/bios.exe', mock_open.return_value)
            mock_open.assert_has_calls([mock.call(exp_result, 'wb')])

    def test_download_to_temp_invalid(self):
        node = mock.Mock(uuid='9f0f6795-f74e-4b5a-850e-72f586a92435')
        self.assertRaises(
            exception.InvalidParameterValue,
            firmware_utils.download_to_temp, node, 'ftp://firmware/bios.exe')

    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    def test_verify_checksum(self, mock_compute_file_checksum):
        checksum = 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d'
        file_path = '/tmp/bios.exe'
        mock_compute_file_checksum.return_value = checksum
        node = mock.Mock(uuid='9f0f6795-f74e-4b5a-850e-72f586a92435')

        firmware_utils.verify_checksum(node, checksum, file_path)

        mock_compute_file_checksum.assert_called_with(
            file_path, algorithm='sha1')

    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    def test_verify_checksum_mismatch(self, mock_compute_file_checksum):
        checksum1 = 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d'
        checksum2 = '9f6227549221920e312fed2cfc6586ee832cc546'
        file_path = '/tmp/bios.exe'
        mock_compute_file_checksum.return_value = checksum1
        node = mock.Mock(uuid='9f0f6795-f74e-4b5a-850e-72f586a92435')

        self.assertRaises(
            exception.RedfishError, firmware_utils.verify_checksum, node,
            checksum2, file_path)
        mock_compute_file_checksum.assert_called_with(
            file_path, algorithm='sha1')

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    def test_stage_http(self, mock_chmod, mock_link, mock_copyfile,
                        mock_makedirs):
        CONF.deploy.http_url = 'http://10.0.0.2'
        CONF.deploy.external_http_url = None
        CONF.deploy.http_root = '/httproot'
        node = mock.Mock(uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3')

        staged_url, need_cleanup = firmware_utils.stage(
            node, 'http', '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')

        self.assertEqual(staged_url,
                         'http://10.0.0.2/firmware/'
                         '55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        self.assertEqual(need_cleanup, 'http')
        mock_makedirs.assert_called_with(
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            exist_ok=True)
        mock_link.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        mock_chmod.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            CONF.redfish.file_permission)
        mock_copyfile.assert_not_called()

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    def test_stage_http_copyfile(self, mock_chmod, mock_link, mock_copyfile,
                                 mock_makedirs):
        CONF.deploy.http_url = 'http://10.0.0.2'
        CONF.deploy.external_http_url = None
        CONF.deploy.http_root = '/httproot'
        node = mock.Mock(uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3')
        mock_link.side_effect = OSError

        staged_url, need_cleanup = firmware_utils.stage(
            node, 'http', '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')

        self.assertEqual(staged_url,
                         'http://10.0.0.2/firmware/'
                         '55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        self.assertEqual(need_cleanup, 'http')
        mock_makedirs.assert_called_with(
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            exist_ok=True)
        mock_link.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        mock_copyfile.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        mock_chmod.assert_called_with(
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            CONF.redfish.file_permission)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    def test_stage_http_copyfile_fails(self, mock_chmod, mock_link,
                                       mock_copyfile, mock_makedirs):
        CONF.deploy.http_url = 'http://10.0.0.2'
        CONF.deploy.external_http_url = None
        CONF.deploy.http_root = '/httproot'
        node = mock.Mock(uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3')
        mock_link.side_effect = OSError
        mock_copyfile.side_effect = IOError

        self.assertRaises(exception.RedfishError, firmware_utils.stage,
                          node, 'http',
                          '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')

        mock_makedirs.assert_called_with(
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            exist_ok=True)
        mock_link.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        mock_copyfile.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        mock_chmod.assert_not_called()

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    def test_stage_local_external(self, mock_chmod, mock_link, mock_rmtree,
                                  mock_copyfile, mock_makedirs):
        CONF.deploy.http_url = 'http://10.0.0.2'
        CONF.deploy.external_http_url = 'http://90.0.0.9'
        CONF.deploy.http_root = '/httproot'
        node = mock.Mock(uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3')

        staged_url, need_cleanup = firmware_utils.stage(
            node, 'local',
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')

        self.assertEqual(staged_url,
                         'http://90.0.0.9/firmware/'
                         '55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        self.assertEqual(need_cleanup, 'http')
        mock_makedirs.assert_called_with(
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            exist_ok=True)
        mock_link.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe')
        mock_chmod.assert_called_with(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe',
            CONF.redfish.file_permission)
        mock_copyfile.assert_not_called()

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_stage_swift(self, mock_swift_api):
        node = mock.Mock(uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3')
        mock_swift_api.return_value.get_temp_url.return_value = 'http://temp'
        temp_file = '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe'

        staged_url, need_cleanup = firmware_utils.stage(
            node, 'swift', temp_file)

        self.assertEqual(staged_url, 'http://temp')
        self.assertEqual(need_cleanup, 'swift')
        exp_object_name = '55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe'
        mock_swift_api.return_value.create_object.assert_called_with(
            CONF.redfish.swift_container,
            exp_object_name, temp_file,
            object_headers={'X-Delete-After':
                            str(CONF.redfish.swift_object_expiry_timeout)})
        mock_swift_api.return_value.get_temp_url.assert_called_with(
            CONF.redfish.swift_container, exp_object_name,
            CONF.redfish.swift_object_expiry_timeout)

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'gettempdir', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_cleanup(self, mock_swift_api, mock_gettempdir, mock_rmtree):
        mock_gettempdir.return_value = '/tmp'
        CONF.deploy.http_root = '/httproot'
        node = mock.Mock(
            uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3',
            driver_internal_info={'firmware_cleanup': ['http', 'swift']})
        object_name = '55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe'
        get_container = mock_swift_api.return_value.connection.get_container
        get_container.return_value = (mock.Mock(), [{'name': object_name}])

        firmware_utils.cleanup(node)

        mock_rmtree.assert_any_call(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            ignore_errors=True)
        mock_rmtree.assert_any_call(
            '/httproot/firmware/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            ignore_errors=True)
        mock_swift_api.return_value.delete_object.assert_called_with(
            CONF.redfish.swift_container, object_name)

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'gettempdir', autospec=True)
    def test_cleanup_notstaged(self, mock_gettempdir, mock_rmtree):
        mock_gettempdir.return_value = '/tmp'
        node = mock.Mock(
            uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3',
            driver_internal_info={'something': 'else'})

        firmware_utils.cleanup(node)

        mock_rmtree.assert_any_call(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            ignore_errors=True)

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'gettempdir', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    @mock.patch.object(firmware_utils.LOG, 'warning', autospec=True)
    def test_cleanup_swift_fails(self, mock_warning, mock_swift_api,
                                 mock_gettempdir, mock_rmtree):
        mock_gettempdir.return_value = '/tmp'
        node = mock.Mock(
            uuid='55cdaba0-1123-4622-8b37-bb52dd6285d3',
            driver_internal_info={'firmware_cleanup': ['swift']})
        object_name = '55cdaba0-1123-4622-8b37-bb52dd6285d3/file.exe'
        get_container = mock_swift_api.return_value.connection.get_container
        get_container.return_value = (mock.Mock(), [{'name': object_name}])
        mock_swift_api.return_value.delete_object.side_effect =\
            exception.SwiftOperationError

        firmware_utils.cleanup(node)

        mock_rmtree.assert_any_call(
            '/tmp/55cdaba0-1123-4622-8b37-bb52dd6285d3',
            ignore_errors=True)
        mock_swift_api.return_value.delete_object.assert_called_with(
            CONF.redfish.swift_container, object_name)
        mock_warning.assert_called_once()
