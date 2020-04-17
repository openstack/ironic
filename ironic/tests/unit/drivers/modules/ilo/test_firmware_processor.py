# Copyright 2016 Hewlett Packard Enterprise Development Company LP
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

"""Test class for Firmware Processor used by iLO management interface."""

import builtins
import io
from urllib import parse as urlparse

import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import firmware_processor as ilo_fw_processor
from ironic.tests import base

ilo_error = importutils.try_import('proliantutils.exception')


class FirmwareProcessorTestCase(base.TestCase):

    def setUp(self):
        super(FirmwareProcessorTestCase, self).setUp()
        self.any_url = 'http://netloc/path'
        self.fw_processor_fake = mock.MagicMock(
            parsed_url='set it as required')

    def test_verify_firmware_update_args_throws_for_invalid_update_mode(self):
        # | GIVEN |
        update_firmware_mock = mock.MagicMock()
        firmware_update_args = {'firmware_update_mode': 'invalid_mode',
                                'firmware_images': None}
        # Note(deray): Need to set __name__ attribute explicitly to keep
        # ``functools.wraps`` happy. Passing this to the `name` argument at
        # the time creation of Mock doesn't help.
        update_firmware_mock.__name__ = 'update_firmware_mock'
        wrapped_func = (ilo_fw_processor.
                        verify_firmware_update_args(update_firmware_mock))
        node_fake = mock.MagicMock(uuid='fake_node_uuid')
        task_fake = mock.MagicMock(node=node_fake)
        # | WHEN & THEN |
        self.assertRaises(exception.InvalidParameterValue,
                          wrapped_func,
                          mock.ANY,
                          task_fake,
                          **firmware_update_args)

    def test_verify_firmware_update_args_throws_for_no_firmware_url(self):
        # | GIVEN |
        update_firmware_mock = mock.MagicMock()
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': []}
        update_firmware_mock.__name__ = 'update_firmware_mock'
        wrapped_func = (ilo_fw_processor.
                        verify_firmware_update_args(update_firmware_mock))
        # | WHEN & THEN |
        self.assertRaises(exception.InvalidParameterValue,
                          wrapped_func,
                          mock.ANY,
                          mock.ANY,
                          **firmware_update_args)

    def test_get_and_validate_firmware_image_info(self):
        # | GIVEN |
        firmware_image_info = {
            'url': self.any_url,
            'checksum': 'b64c8f7799cfbb553d384d34dc43fafe336cc889',
            'component': 'BIOS'
        }
        # | WHEN |
        url, checksum, component = (
            ilo_fw_processor.get_and_validate_firmware_image_info(
                firmware_image_info, 'ilo'))
        # | THEN |
        self.assertEqual(self.any_url, url)
        self.assertEqual('b64c8f7799cfbb553d384d34dc43fafe336cc889', checksum)
        self.assertEqual('bios', component)

    def test_get_and_validate_firmware_image_info_fails_for_missing_parameter(
            self):
        # | GIVEN |
        invalid_firmware_image_info = {
            'url': self.any_url,
            'component': 'bios'
        }
        # | WHEN | & | THEN |
        self.assertRaisesRegex(
            exception.MissingParameterValue, 'checksum',
            ilo_fw_processor.get_and_validate_firmware_image_info,
            invalid_firmware_image_info, 'ilo')

    def test_get_and_validate_firmware_image_info_fails_for_empty_parameter(
            self):
        # | GIVEN |
        invalid_firmware_image_info = {
            'url': self.any_url,
            'checksum': 'valid_checksum',
            'component': ''
        }
        # | WHEN | & | THEN |
        self.assertRaisesRegex(
            exception.MissingParameterValue, 'component',
            ilo_fw_processor.get_and_validate_firmware_image_info,
            invalid_firmware_image_info, 'ilo')

    def test_get_and_validate_firmware_image_info_fails_for_invalid_component(
            self):
        # | GIVEN |
        invalid_firmware_image_info = {
            'url': self.any_url,
            'checksum': 'valid_checksum',
            'component': 'INVALID'
        }
        # | WHEN | & | THEN |
        self.assertRaises(
            exception.InvalidParameterValue,
            ilo_fw_processor.get_and_validate_firmware_image_info,
            invalid_firmware_image_info, 'ilo')

    def test_get_and_validate_firmware_image_info_sum(self):
        # | GIVEN |
        result = None
        firmware_image_info = {
            'url': self.any_url,
            'checksum': 'b64c8f7799cfbb553d384d34dc43fafe336cc889'
        }
        # | WHEN | & | THEN |
        ret_val = ilo_fw_processor.get_and_validate_firmware_image_info(
            firmware_image_info, 'sum')
        self.assertEqual(result, ret_val)

    def test_get_and_validate_firmware_image_info_sum_with_component(self):
        # | GIVEN |
        result = None
        firmware_image_info = {
            'url': self.any_url,
            'checksum': 'b64c8f7799cfbb553d384d34dc43fafe336cc889',
            'components': ['CP02345.exe']
        }
        # | WHEN | & | THEN |
        ret_val = ilo_fw_processor.get_and_validate_firmware_image_info(
            firmware_image_info, 'sum')
        self.assertEqual(result, ret_val)

    def test_get_and_validate_firmware_image_info_sum_invalid_component(
            self):
        # | GIVEN |
        invalid_firmware_image_info = {
            'url': 'any_url',
            'checksum': 'valid_checksum',
            'components': 'INVALID'
        }
        # | WHEN | & | THEN |
        self.assertRaises(
            exception.InvalidParameterValue,
            ilo_fw_processor.get_and_validate_firmware_image_info,
            invalid_firmware_image_info, 'sum')

    def test__validate_sum_components(self):
        result = None
        components = ['CP02345.scexe', 'CP02678.exe']

        ret_val = ilo_fw_processor._validate_sum_components(components)

        self.assertEqual(ret_val, result)

    @mock.patch.object(ilo_fw_processor, 'LOG')
    def test__validate_sum_components_fails(self, LOG_mock):
        components = ['INVALID']

        self.assertRaises(
            exception.InvalidParameterValue,
            ilo_fw_processor._validate_sum_components, components)

        self.assertTrue(LOG_mock.error.called)

    def test_fw_processor_ctor_sets_parsed_url_attrib_of_fw_processor(self):
        # | WHEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(self.any_url)
        # | THEN |
        self.assertEqual(self.any_url, fw_processor.parsed_url.geturl())

    @mock.patch.object(
        ilo_fw_processor, '_download_file_based_fw_to', autospec=True)
    def test__download_file_based_fw_to_gets_invoked_for_file_based_firmware(
            self, _download_file_based_fw_to_mock):
        # | GIVEN |
        some_file_url = 'file:///some_location/some_firmware_file'
        # | WHEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(some_file_url)
        fw_processor._download_fw_to('some_target_file')
        # | THEN |
        _download_file_based_fw_to_mock.assert_called_once_with(
            fw_processor, 'some_target_file')

    @mock.patch.object(
        ilo_fw_processor, '_download_http_based_fw_to', autospec=True)
    def test__download_http_based_fw_to_gets_invoked_for_http_based_firmware(
            self, _download_http_based_fw_to_mock):
        # | GIVEN |
        for some_http_url in ('http://netloc/path_to_firmware_file',
                              'https://netloc/path_to_firmware_file'):
            # | WHEN |
            fw_processor = ilo_fw_processor.FirmwareProcessor(some_http_url)
            fw_processor._download_fw_to('some_target_file')
            # | THEN |
            _download_http_based_fw_to_mock.assert_called_once_with(
                fw_processor, 'some_target_file')
            _download_http_based_fw_to_mock.reset_mock()

    @mock.patch.object(
        ilo_fw_processor, '_download_swift_based_fw_to', autospec=True)
    def test__download_swift_based_fw_to_gets_invoked_for_swift_based_firmware(
            self, _download_swift_based_fw_to_mock):
        # | GIVEN |
        some_swift_url = 'swift://containername/objectname'
        # | WHEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(some_swift_url)
        fw_processor._download_fw_to('some_target_file')
        # | THEN |
        _download_swift_based_fw_to_mock.assert_called_once_with(
            fw_processor, 'some_target_file')

    def test_fw_processor_ctor_throws_exception_with_invalid_firmware_url(
            self):
        # | GIVEN |
        any_invalid_firmware_url = 'any_invalid_url'
        # | WHEN | & | THEN |
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_fw_processor.FirmwareProcessor,
                          any_invalid_firmware_url)

    @mock.patch.object(ilo_fw_processor, 'tempfile', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'os', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'shutil', autospec=True)
    @mock.patch.object(ilo_common, 'verify_image_checksum',
                       spec_set=True, autospec=True)
    @mock.patch.object(
        ilo_fw_processor, '_extract_fw_from_file', autospec=True)
    def test_process_fw_on_calls__download_fw_to(
            self, _extract_fw_from_file_mock, verify_checksum_mock,
            shutil_mock, os_mock, tempfile_mock):
        # | GIVEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(self.any_url)
        # Now mock the __download_fw_to method of fw_processor instance
        _download_fw_to_mock = mock.MagicMock()
        fw_processor._download_fw_to = _download_fw_to_mock

        expected_return_location = (ilo_fw_processor.FirmwareImageLocation(
            'some_location/file', 'file'))
        _extract_fw_from_file_mock.return_value = (expected_return_location,
                                                   True)
        node_mock = mock.ANY
        checksum_fake = mock.ANY
        # | WHEN |
        actual_return_location = fw_processor.process_fw_on(node_mock,
                                                            checksum_fake)
        # | THEN |
        _download_fw_to_mock.assert_called_once_with(
            os_mock.path.join.return_value)
        self.assertEqual(expected_return_location.fw_image_location,
                         actual_return_location.fw_image_location)
        self.assertEqual(expected_return_location.fw_image_filename,
                         actual_return_location.fw_image_filename)

    @mock.patch.object(ilo_fw_processor, 'tempfile', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'os', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'shutil', autospec=True)
    @mock.patch.object(ilo_common, 'verify_image_checksum',
                       spec_set=True, autospec=True)
    @mock.patch.object(
        ilo_fw_processor, '_extract_fw_from_file', autospec=True)
    def test_process_fw_on_verifies_checksum_of_downloaded_fw_file(
            self, _extract_fw_from_file_mock, verify_checksum_mock,
            shutil_mock, os_mock, tempfile_mock):
        # | GIVEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(self.any_url)
        # Now mock the __download_fw_to method of fw_processor instance
        _download_fw_to_mock = mock.MagicMock()
        fw_processor._download_fw_to = _download_fw_to_mock

        expected_return_location = (ilo_fw_processor.FirmwareImageLocation(
            'some_location/file', 'file'))
        _extract_fw_from_file_mock.return_value = (expected_return_location,
                                                   True)
        node_mock = mock.ANY
        checksum_fake = mock.ANY
        # | WHEN |
        actual_return_location = fw_processor.process_fw_on(node_mock,
                                                            checksum_fake)
        # | THEN |
        _download_fw_to_mock.assert_called_once_with(
            os_mock.path.join.return_value)
        verify_checksum_mock.assert_called_once_with(
            os_mock.path.join.return_value, checksum_fake)
        self.assertEqual(expected_return_location.fw_image_location,
                         actual_return_location.fw_image_location)
        self.assertEqual(expected_return_location.fw_image_filename,
                         actual_return_location.fw_image_filename)

    @mock.patch.object(ilo_fw_processor, 'tempfile', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'os', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'shutil', autospec=True)
    @mock.patch.object(ilo_common, 'verify_image_checksum',
                       spec_set=True, autospec=True)
    def test_process_fw_on_throws_error_if_checksum_validation_fails(
            self, verify_checksum_mock, shutil_mock, os_mock, tempfile_mock):
        # | GIVEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(self.any_url)
        # Now mock the __download_fw_to method of fw_processor instance
        _download_fw_to_mock = mock.MagicMock()
        fw_processor._download_fw_to = _download_fw_to_mock

        verify_checksum_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='some image',
            reason='checksum verification failed')
        node_mock = mock.ANY
        checksum_fake = mock.ANY
        # | WHEN | & | THEN |
        self.assertRaises(exception.ImageRefValidationFailed,
                          fw_processor.process_fw_on,
                          node_mock,
                          checksum_fake)
        shutil_mock.rmtree.assert_called_once_with(
            tempfile_mock.mkdtemp(), ignore_errors=True)

    @mock.patch.object(ilo_fw_processor, 'tempfile', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'os', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'shutil', autospec=True)
    @mock.patch.object(ilo_common, 'verify_image_checksum',
                       spec_set=True, autospec=True)
    @mock.patch.object(
        ilo_fw_processor, '_extract_fw_from_file', autospec=True)
    def test_process_fw_on_calls__extract_fw_from_file(
            self, _extract_fw_from_file_mock, verify_checksum_mock,
            shutil_mock, os_mock, tempfile_mock):
        # | GIVEN |
        fw_processor = ilo_fw_processor.FirmwareProcessor(self.any_url)
        # Now mock the __download_fw_to method of fw_processor instance
        _download_fw_to_mock = mock.MagicMock()
        fw_processor._download_fw_to = _download_fw_to_mock

        expected_return_location = (ilo_fw_processor.FirmwareImageLocation(
            'some_location/file', 'file'))
        _extract_fw_from_file_mock.return_value = (expected_return_location,
                                                   True)
        node_mock = mock.ANY
        checksum_fake = mock.ANY
        # | WHEN |
        actual_return_location = fw_processor.process_fw_on(node_mock,
                                                            checksum_fake)
        # | THEN |
        _extract_fw_from_file_mock.assert_called_once_with(
            node_mock, os_mock.path.join.return_value)
        self.assertEqual(expected_return_location.fw_image_location,
                         actual_return_location.fw_image_location)
        self.assertEqual(expected_return_location.fw_image_filename,
                         actual_return_location.fw_image_filename)
        shutil_mock.rmtree.assert_called_once_with(
            tempfile_mock.mkdtemp(), ignore_errors=True)

    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(
        ilo_fw_processor.image_service, 'FileImageService', autospec=True)
    def test__download_file_based_fw_to_copies_file_to_target(
            self, file_image_service_mock, open_mock):
        # | GIVEN |
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        fd_mock.__enter__.return_value = fd_mock
        any_file_based_firmware_file = 'file:///tmp/any_file_path'
        firmware_file_path = '/tmp/any_file_path'
        self.fw_processor_fake.parsed_url = urlparse.urlparse(
            any_file_based_firmware_file)
        # | WHEN |
        ilo_fw_processor._download_file_based_fw_to(self.fw_processor_fake,
                                                    'target_file')
        # | THEN |
        file_image_service_mock.return_value.download.assert_called_once_with(
            firmware_file_path, fd_mock)

    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'image_service', autospec=True)
    def test__download_http_based_fw_to_downloads_the_fw_file(
            self, image_service_mock, open_mock):
        # | GIVEN |
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        fd_mock.__enter__.return_value = fd_mock
        any_http_based_firmware_file = 'http://netloc/path_to_firmware_file'
        any_target_file = 'any_target_file'
        self.fw_processor_fake.parsed_url = urlparse.urlparse(
            any_http_based_firmware_file)
        # | WHEN |
        ilo_fw_processor._download_http_based_fw_to(self.fw_processor_fake,
                                                    any_target_file)
        # | THEN |
        image_service_mock.HttpImageService().download.assert_called_once_with(
            any_http_based_firmware_file, fd_mock)

    @mock.patch.object(ilo_fw_processor, 'urlparse', autospec=True)
    @mock.patch.object(
        ilo_fw_processor, '_download_http_based_fw_to', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'swift', autospec=True)
    def test__download_swift_based_fw_to_creates_temp_url(
            self, swift_mock, _download_http_based_fw_to_mock, urlparse_mock):
        # | GIVEN |
        swift_based_firmware_files = [
            'swift://containername/objectname',
            'swift://containername/pseudo-folder/objectname'
        ]
        for swift_firmware_file in swift_based_firmware_files:
            # | WHEN |
            self.fw_processor_fake.parsed_url = (urlparse.
                                                 urlparse(swift_firmware_file))
            ilo_fw_processor._download_swift_based_fw_to(
                self.fw_processor_fake, 'any_target_file')
        # | THEN |
        expected_temp_url_call_args_list = [
            mock.call('containername', 'objectname', mock.ANY),
            mock.call('containername', 'pseudo-folder/objectname', mock.ANY)
        ]
        actual_temp_url_call_args_list = (
            swift_mock.SwiftAPI().get_temp_url.call_args_list)
        self.assertEqual(expected_temp_url_call_args_list,
                         actual_temp_url_call_args_list)

    @mock.patch.object(urlparse, 'urlparse', autospec=True)
    @mock.patch.object(
        ilo_fw_processor, '_download_http_based_fw_to', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'swift', autospec=True)
    def test__download_swift_based_fw_to_calls__download_http_based_fw_to(
            self, swift_mock, _download_http_based_fw_to_mock, urlparse_mock):
        """_download_swift_based_fw_to invokes _download_http_based_fw_to

        _download_swift_based_fw_to makes a call to _download_http_based_fw_to
        in turn with temp url set as the url attribute of fw_processor instance
        """
        # | GIVEN |
        any_swift_based_firmware_file = 'swift://containername/objectname'
        any_target_file = 'any_target_file'
        self.fw_processor_fake.parsed_url = urlparse.urlparse(
            any_swift_based_firmware_file)
        urlparse_mock.reset_mock()
        # | WHEN |
        ilo_fw_processor._download_swift_based_fw_to(self.fw_processor_fake,
                                                     any_target_file)
        # | THEN |
        _download_http_based_fw_to_mock.assert_called_once_with(
            self.fw_processor_fake, any_target_file)
        urlparse_mock.assert_called_once_with(
            swift_mock.SwiftAPI().get_temp_url.return_value)
        self.assertEqual(
            urlparse_mock.return_value, self.fw_processor_fake.parsed_url)

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    def test__extract_fw_from_file_calls_process_firmware_image(
            self, utils_mock, ilo_common_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        ilo_object_mock = ilo_common_mock.get_ilo_object.return_value
        utils_mock.process_firmware_image.return_value = ('some_location',
                                                          True, True)
        # | WHEN |
        ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file)
        # | THEN |
        utils_mock.process_firmware_image.assert_called_once_with(
            any_target_file, ilo_object_mock)

    @mock.patch.object(deploy_utils, 'copy_image_to_web_server',
                       autospec=True)
    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    def test__extract_fw_from_file_doesnt_upload_firmware(
            self, utils_mock, ilo_common_mock, copy_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        utils_mock.process_firmware_image.return_value = (
            'some_location/some_fw_file', False, True)
        # | WHEN |
        ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file)
        # | THEN |
        copy_mock.assert_not_called()

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    @mock.patch.object(ilo_fw_processor, '_remove_file_based_me',
                       autospec=True)
    def test__extract_fw_from_file_sets_loc_obj_remove_to_file_if_no_upload(
            self, _remove_mock, utils_mock, ilo_common_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        utils_mock.process_firmware_image.return_value = (
            'some_location/some_fw_file', False, True)
        # | WHEN |
        location_obj, is_different_file = (
            ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file))
        location_obj.remove()
        # | THEN |
        _remove_mock.assert_called_once_with(location_obj)

    @mock.patch.object(deploy_utils, 'copy_image_to_web_server',
                       autospec=True)
    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    def test__extract_fw_from_file_uploads_firmware_to_webserver(
            self, utils_mock, ilo_common_mock, copy_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        utils_mock.process_firmware_image.return_value = (
            'some_location/some_fw_file', True, True)
        self.config(use_web_server_for_images=True, group='ilo')
        # | WHEN |
        ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file)
        # | THEN |
        copy_mock.assert_called_once_with(
            'some_location/some_fw_file', 'some_fw_file')

    @mock.patch.object(deploy_utils, 'copy_image_to_web_server',
                       autospec=True)
    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    @mock.patch.object(ilo_fw_processor, '_remove_webserver_based_me',
                       autospec=True)
    def test__extract_fw_from_file_sets_loc_obj_remove_to_webserver(
            self, _remove_mock, utils_mock, ilo_common_mock, copy_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        utils_mock.process_firmware_image.return_value = (
            'some_location/some_fw_file', True, True)
        self.config(use_web_server_for_images=True, group='ilo')
        # | WHEN |
        location_obj, is_different_file = (
            ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file))
        location_obj.remove()
        # | THEN |
        _remove_mock.assert_called_once_with(location_obj)

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    def test__extract_fw_from_file_uploads_firmware_to_swift(
            self, utils_mock, ilo_common_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        utils_mock.process_firmware_image.return_value = (
            'some_location/some_fw_file', True, True)
        self.config(use_web_server_for_images=False, group='ilo')
        # | WHEN |
        ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file)
        # | THEN |
        ilo_common_mock.copy_image_to_swift.assert_called_once_with(
            'some_location/some_fw_file', 'some_fw_file')

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    @mock.patch.object(ilo_fw_processor, 'proliantutils_utils', autospec=True)
    @mock.patch.object(ilo_fw_processor, '_remove_swift_based_me',
                       autospec=True)
    def test__extract_fw_from_file_sets_loc_obj_remove_to_swift(
            self, _remove_mock, utils_mock, ilo_common_mock):
        # | GIVEN |
        node_mock = mock.MagicMock(uuid='fake_node_uuid')
        any_target_file = 'any_target_file'
        utils_mock.process_firmware_image.return_value = (
            'some_location/some_fw_file', True, True)
        self.config(use_web_server_for_images=False, group='ilo')
        # | WHEN |
        location_obj, is_different_file = (
            ilo_fw_processor._extract_fw_from_file(node_mock, any_target_file))
        location_obj.remove()
        # | THEN |
        _remove_mock.assert_called_once_with(location_obj)

    def test_fw_img_loc_sets_these_attributes(self):
        # | GIVEN |
        any_loc = 'some_location/some_fw_file'
        any_s_filename = 'some_fw_file'
        # | WHEN |
        location_obj = ilo_fw_processor.FirmwareImageLocation(
            any_loc, any_s_filename)
        # | THEN |
        self.assertEqual(any_loc, location_obj.fw_image_location)
        self.assertEqual(any_s_filename, location_obj.fw_image_filename)

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    def test__remove_file_based_me(
            self, ilo_common_mock):
        # | GIVEN |
        fw_img_location_obj_fake = mock.MagicMock()
        # | WHEN |
        ilo_fw_processor._remove_file_based_me(fw_img_location_obj_fake)
        # | THEN |
        (ilo_common_mock.remove_single_or_list_of_files.
         assert_called_with(fw_img_location_obj_fake.fw_image_location))

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    def test__remove_swift_based_me(self, ilo_common_mock):
        # | GIVEN |
        fw_img_location_obj_fake = mock.MagicMock()
        # | WHEN |
        ilo_fw_processor._remove_swift_based_me(fw_img_location_obj_fake)
        # | THEN |
        (ilo_common_mock.remove_image_from_swift.assert_called_with(
            fw_img_location_obj_fake.fw_image_filename, "firmware update"))

    @mock.patch.object(ilo_fw_processor, 'ilo_common', autospec=True)
    def test__remove_webserver_based_me(self, ilo_common_mock):
        # | GIVEN |
        fw_img_location_obj_fake = mock.MagicMock()
        # | WHEN |
        ilo_fw_processor._remove_webserver_based_me(fw_img_location_obj_fake)
        # | THEN |
        (ilo_common_mock.remove_image_from_web_server.assert_called_with(
            fw_img_location_obj_fake.fw_image_filename))
