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

import mock
import requests
import sendfile
import six.moves.builtins as __builtin__

from ironic.common import exception
from ironic.common.glance_service.v1 import image_service as glance_v1_service
from ironic.common import image_service
from ironic.tests import base


class HttpImageServiceTestCase(base.TestCase):
    def setUp(self):
        super(HttpImageServiceTestCase, self).setUp()
        self.service = image_service.HttpImageService()
        self.href = 'http://127.0.0.1:12345/fedora.qcow2'

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href(self, head_mock):
        response = head_mock.return_value
        response.status_code = 200
        self.service.validate_href(self.href)
        head_mock.assert_called_once_with(self.href)
        response.status_code = 204
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = 400
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_error_code(self, head_mock):
        head_mock.return_value.status_code = 400
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_error(self, head_mock):
        head_mock.side_effect = requests.ConnectionError()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_show(self, head_mock):
        head_mock.return_value.status_code = 200
        result = self.service.show(self.href)
        head_mock.assert_called_with(self.href)
        self.assertEqual({'size': 1, 'properties': {}}, result)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_show_no_content_length(self, head_mock):
        head_mock.return_value.status_code = 200
        head_mock.return_value.headers = {}
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.show, self.href)
        head_mock.assert_called_with(self.href)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success(self, req_get_mock, shutil_mock):
        response_mock = req_get_mock.return_value
        response_mock.status_code = 200
        response_mock.raw = mock.MagicMock(spec=file)
        file_mock = mock.Mock(spec=file)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True)

    @mock.patch.object(requests, 'get', autospec=True,
                       side_effect=requests.ConnectionError())
    def test_download_fail_connerror(self, req_get_mock):
        file_mock = mock.Mock(spec=file)
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_fail_ioerror(self, req_get_mock, shutil_mock):
        response_mock = req_get_mock.return_value
        response_mock.status_code = 200
        response_mock.raw = mock.MagicMock(spec=file)
        file_mock = mock.Mock(spec=file)
        shutil_mock.side_effect = IOError
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        req_get_mock.assert_called_once_with(self.href, stream=True)


class FileImageServiceTestCase(base.TestCase):
    def setUp(self):
        super(FileImageServiceTestCase, self).setUp()
        self.service = image_service.FileImageService()
        self.href = 'file:///home/user/image.qcow2'
        self.href_path = '/home/user/image.qcow2'

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    def test_validate_href(self, path_exists_mock):
        self.service.validate_href(self.href)
        path_exists_mock.assert_called_once_with(self.href_path)

    @mock.patch.object(os.path, 'isfile', return_value=False, autospec=True)
    def test_validate_href_path_not_found_or_not_file(self, path_exists_mock):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        path_exists_mock.assert_called_once_with(self.href_path)

    @mock.patch.object(os.path, 'getsize', return_value=42, autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_show(self, _validate_mock, getsize_mock):
        _validate_mock.return_value = self.href_path
        result = self.service.show(self.href)
        getsize_mock.assert_called_once_with(self.href_path)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        self.assertEqual({'size': 42, 'properties': {}}, result)

    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(os, 'access', return_value=True, autospec=True)
    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_hard_link(self, _validate_mock, stat_mock, access_mock,
                                remove_mock, link_mock):
        _validate_mock.return_value = self.href_path
        stat_mock.return_value.st_dev = 'dev1'
        file_mock = mock.Mock(spec=file)
        file_mock.name = 'file'
        self.service.download(self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        self.assertEqual(2, stat_mock.call_count)
        access_mock.assert_called_once_with(self.href_path, os.R_OK | os.W_OK)
        remove_mock.assert_called_once_with('file')
        link_mock.assert_called_once_with(self.href_path, 'file')

    @mock.patch.object(sendfile, 'sendfile', autospec=True)
    @mock.patch.object(os.path, 'getsize', return_value=42, autospec=True)
    @mock.patch.object(__builtin__, 'open', autospec=True)
    @mock.patch.object(os, 'access', return_value=False, autospec=True)
    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_copy(self, _validate_mock, stat_mock, access_mock,
                           open_mock, size_mock, copy_mock):
        _validate_mock.return_value = self.href_path
        stat_mock.return_value.st_dev = 'dev1'
        file_mock = mock.MagicMock(spec=file)
        input_mock = mock.MagicMock(spec=file)
        open_mock.return_value = input_mock
        self.service.download(self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        self.assertEqual(2, stat_mock.call_count)
        access_mock.assert_called_once_with(self.href_path, os.R_OK | os.W_OK)
        copy_mock.assert_called_once_with(file_mock.fileno(),
                                          input_mock.__enter__().fileno(),
                                          0, 42)
        size_mock.assert_called_once_with(self.href_path)

    @mock.patch.object(os, 'remove', side_effect=OSError, autospec=True)
    @mock.patch.object(os, 'access', return_value=True, autospec=True)
    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_hard_link_fail(self, _validate_mock, stat_mock,
                                     access_mock, remove_mock):
        _validate_mock.return_value = self.href_path
        stat_mock.return_value.st_dev = 'dev1'
        file_mock = mock.MagicMock(spec=file)
        file_mock.name = 'file'
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        self.assertEqual(2, stat_mock.call_count)
        access_mock.assert_called_once_with(self.href_path, os.R_OK | os.W_OK)

    @mock.patch.object(sendfile, 'sendfile', side_effect=OSError,
                       autospec=True)
    @mock.patch.object(os.path, 'getsize', return_value=42, autospec=True)
    @mock.patch.object(__builtin__, 'open', autospec=True)
    @mock.patch.object(os, 'access', return_value=False, autospec=True)
    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_copy_fail(self, _validate_mock, stat_mock, access_mock,
                                open_mock, size_mock, copy_mock):
        _validate_mock.return_value = self.href_path
        stat_mock.return_value.st_dev = 'dev1'
        file_mock = mock.MagicMock(spec=file)
        input_mock = mock.MagicMock(spec=file)
        open_mock.return_value = input_mock
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        self.assertEqual(2, stat_mock.call_count)
        access_mock.assert_called_once_with(self.href_path, os.R_OK | os.W_OK)
        size_mock.assert_called_once_with(self.href_path)


class ServiceGetterTestCase(base.TestCase):

    @mock.patch.object(glance_v1_service.GlanceImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_glance_image_service(self, glance_service_mock):
        image_href = 'image-uuid'
        image_service.get_image_service(image_href, context=self.context)
        glance_service_mock.assert_called_once_with(mock.ANY, None, 1,
                                                    self.context)

    @mock.patch.object(glance_v1_service.GlanceImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_glance_image_service_url(self, glance_service_mock):
        image_href = 'glance://image-uuid'
        image_service.get_image_service(image_href, context=self.context)
        glance_service_mock.assert_called_once_with(mock.ANY, None, 1,
                                                    self.context)

    @mock.patch.object(image_service.HttpImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_http_image_service(self, http_service_mock):
        image_href = 'http://127.0.0.1/image.qcow2'
        image_service.get_image_service(image_href)
        http_service_mock.assert_called_once_with()

    @mock.patch.object(image_service.HttpImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_https_image_service(self, http_service_mock):
        image_href = 'https://127.0.0.1/image.qcow2'
        image_service.get_image_service(image_href)
        http_service_mock.assert_called_once_with()

    @mock.patch.object(image_service.FileImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_file_image_service(self, local_service_mock):
        image_href = 'file:///home/user/image.qcow2'
        image_service.get_image_service(image_href)
        local_service_mock.assert_called_once_with()

    def test_get_image_service_unknown_protocol(self):
        image_href = 'usenet://alt.binaries.dvd/image.qcow2'
        self.assertRaises(exception.ImageRefValidationFailed,
                          image_service.get_image_service, image_href)
