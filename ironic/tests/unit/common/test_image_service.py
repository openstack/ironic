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

import datetime
from http import client as http_client
import io
import os
import shutil
from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils
import requests

from ironic.common import exception
from ironic.common.glance_service import image_service as glance_v2_service
from ironic.common import image_service
from ironic.common.oci_registry import OciClient as ociclient
from ironic.common.oci_registry import RegistrySessionHelper as rs_helper
from ironic.tests import base


class HttpImageServiceTestCase(base.TestCase):
    def setUp(self):
        super(HttpImageServiceTestCase, self).setUp()
        self.service = image_service.HttpImageService()
        self.href = 'https://127.0.0.1:12345/fedora.qcow2'

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_http_scheme(self, head_mock, path_mock):
        self.href = 'http://127.0.0.1:12345/fedora.qcow2'
        response = head_mock.return_value
        response.status_code = http_client.OK
        self.service.validate_href(self.href)
        path_mock.assert_not_called()
        head_mock.assert_called_once_with(self.href, verify=True,
                                          timeout=60, auth=None)
        response.status_code = http_client.NO_CONTENT
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = http_client.BAD_REQUEST
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_false(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'False')

        response = head_mock.return_value
        response.status_code = http_client.OK
        self.service.validate_href(self.href)
        head_mock.assert_called_once_with(self.href, verify=False,
                                          timeout=60, auth=None)
        response.status_code = http_client.NO_CONTENT
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = http_client.BAD_REQUEST
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_false_error(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'False')
        head_mock.side_effect = requests.ConnectionError()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href, verify=False,
                                          timeout=60, auth=None)
        head_mock.side_effect = requests.RequestException()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_true(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'True')

        response = head_mock.return_value
        response.status_code = http_client.OK
        self.service.validate_href(self.href)
        head_mock.assert_called_once_with(self.href, verify=True,
                                          timeout=60, auth=None)
        response.status_code = http_client.NO_CONTENT
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = http_client.BAD_REQUEST
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_true_error(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'True')

        head_mock.side_effect = requests.ConnectionError()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href, verify=True,
                                          timeout=60, auth=None)
        head_mock.side_effect = requests.RequestException()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_valid_path(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')

        response = head_mock.return_value
        response.status_code = http_client.OK

        self.service.validate_href(self.href)
        head_mock.assert_called_once_with(self.href, verify='/some/path',
                                          timeout=60, auth=None)
        response.status_code = http_client.NO_CONTENT
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = http_client.BAD_REQUEST
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_valid_path_valid_basic_auth(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        cfg.CONF.set_override('image_server_auth_strategy',
                              'http_basic',
                              'deploy')
        cfg.CONF.set_override('image_server_user', 'test', 'deploy')
        cfg.CONF.set_override('image_server_password', 'test', 'deploy')
        user = cfg.CONF.deploy.image_server_user
        password = cfg.CONF.deploy.image_server_password
        auth_creds = requests.auth.HTTPBasicAuth(user, password)
        response = head_mock.return_value
        response.status_code = http_client.OK

        self.service.validate_href(self.href)
        head_mock.assert_called_once_with(self.href, verify='/some/path',
                                          timeout=60, auth=auth_creds)
        response.status_code = http_client.NO_CONTENT
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = http_client.BAD_REQUEST
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_valid_path_invalid_basic_auth(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        cfg.CONF.set_override('image_server_auth_strategy',
                              'http_basic',
                              'deploy')

        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_custom_timeout(self, head_mock):
        cfg.CONF.set_override('webserver_connection_timeout', 15)

        response = head_mock.return_value
        response.status_code = http_client.OK
        self.service.validate_href(self.href)
        head_mock.assert_called_once_with(self.href, verify=True,
                                          timeout=15, auth=None)
        response.status_code = http_client.NO_CONTENT
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)
        response.status_code = http_client.BAD_REQUEST
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href,
                          self.href)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_connect_error(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        response = mock.Mock()
        response.status_code = http_client.OK
        head_mock.side_effect = requests.ConnectionError()

        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href, verify='/some/path',
                                          timeout=60, auth=None)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_error(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        head_mock.side_effect = requests.RequestException()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href, verify='/some/path',
                                          timeout=60, auth=None)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_verify_os_error(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        head_mock.side_effect = OSError()
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        head_mock.assert_called_once_with(self.href, verify='/some/path',
                                          timeout=60, auth=None)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_error_with_secret_parameter(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'False')
        head_mock.return_value.status_code = 204
        e = self.assertRaises(exception.ImageRefValidationFailed,
                              self.service.validate_href,
                              self.href,
                              True)
        self.assertIn('secreturl', str(e))
        self.assertNotIn(self.href, str(e))
        head_mock.assert_called_once_with(self.href, verify=False,
                                          timeout=60, auth=None)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_path_forbidden(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'True')

        response = head_mock.return_value
        response.status_code = http_client.FORBIDDEN
        url = self.href + '/'
        resp = self.service.validate_href(url)
        head_mock.assert_called_once_with(url, verify=True,
                                          timeout=60, auth=None)
        self.assertEqual(http_client.FORBIDDEN, resp.status_code)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_validate_href_path_redirected(self, head_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'True')

        response = head_mock.return_value
        response.status_code = http_client.MOVED_PERMANENTLY
        url = self.href + '/'
        new_url = 'http://new-url'
        response.headers = {'location': new_url}
        exc = self.assertRaises(exception.ImageRefIsARedirect,
                                self.service.validate_href,
                                url)
        self.assertEqual(new_url, exc.redirect_url)
        head_mock.assert_called_once_with(url, verify=True,
                                          timeout=60, auth=None)

    def test_verify_basic_auth_cred_format(self):
        self.assertIsNone(self
                          .service
                          .verify_basic_auth_cred_format(self.href,
                                                         "SpongeBob",
                                                         "SquarePants"))

    def test_verify_basic_auth_cred_format_empty_user(self):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.verify_basic_auth_cred_format,
                          self.href,
                          "",
                          "SquarePants")

    def test_verify_basic_auth_cred_format_empty_password(self):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.verify_basic_auth_cred_format,
                          self.href,
                          "SpongeBob",
                          "")

    def test_verify_basic_auth_cred_format_none_user(self):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.verify_basic_auth_cred_format,
                          self.href,
                          None,
                          "SquarePants")

    def test_verify_basic_auth_cred_format_none_password(self):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.verify_basic_auth_cred_format,
                          self.href,
                          "SpongeBob",
                          None)

    def test_gen_auth_from_conf_user_pass_success(self):
        cfg.CONF.set_override('image_server_auth_strategy',
                              'http_basic',
                              'deploy')
        cfg.CONF.set_override('image_server_password', 'SpongeBob', 'deploy')
        cfg.CONF.set_override('image_server_user', 'SquarePants', 'deploy')
        correct_auth = \
            requests.auth.HTTPBasicAuth('SquarePants',
                                        'SpongeBob')
        return_auth = \
            self.service.gen_auth_from_conf_user_pass(self.href)
        self.assertEqual(correct_auth, return_auth)

    def test_gen_auth_from_conf_user_pass_none(self):
        cfg.CONF.set_override('image_server_auth_strategy', 'noauth', 'deploy')
        cfg.CONF.set_override('image_server_password', 'SpongeBob', 'deploy')
        cfg.CONF.set_override('image_server_user', 'SquarePants', 'deploy')
        return_auth = \
            self.service.gen_auth_from_conf_user_pass(self.href)
        self.assertIsNone(return_auth)

    @mock.patch.object(requests, 'head', autospec=True)
    def _test_show(self, head_mock, mtime, mtime_date):
        head_mock.return_value.status_code = http_client.OK
        head_mock.return_value.headers = {
            'Content-Length': 100,
            'Last-Modified': mtime
        }
        result = self.service.show(self.href)
        head_mock.assert_called_once_with(self.href, verify=True,
                                          timeout=60, auth=None)
        self.assertEqual({'size': 100, 'updated_at': mtime_date,
                          'properties': {}, 'no_cache': False}, result)

    def test_show_rfc_822(self):
        self._test_show(mtime='Tue, 15 Nov 2014 08:12:31 GMT',
                        mtime_date=datetime.datetime(2014, 11, 15, 8, 12, 31))

    def test_show_rfc_850(self):
        self._test_show(mtime='Tuesday, 15-Nov-14 08:12:31 GMT',
                        mtime_date=datetime.datetime(2014, 11, 15, 8, 12, 31))

    def test_show_ansi_c(self):
        self._test_show(mtime='Tue Nov 15 08:12:31 2014',
                        mtime_date=datetime.datetime(2014, 11, 15, 8, 12, 31))

    @mock.patch.object(requests, 'head', autospec=True)
    def _test_show_with_cache(self, head_mock, cache_control, no_cache):
        head_mock.return_value.status_code = http_client.OK
        head_mock.return_value.headers = {
            'Content-Length': 100,
            'Last-Modified': 'Tue, 15 Nov 2014 08:12:31 GMT',
            'Cache-Control': cache_control,
        }
        result = self.service.show(self.href)
        head_mock.assert_called_once_with(self.href, verify=True,
                                          timeout=60, auth=None)
        self.assertEqual({
            'size': 100,
            'updated_at': datetime.datetime(2014, 11, 15, 8, 12, 31),
            'properties': {},
            'no_cache': no_cache}, result)

    def test_show_cache_allowed(self):
        self._test_show_with_cache(
            # Just because we cannot have nice things, "no-cache" actually
            # means "cache, but always re-validate".
            cache_control='no-cache, private', no_cache=False)

    def test_show_cache_disabled(self):
        self._test_show_with_cache(
            cache_control='no-store', no_cache=True)

    @mock.patch.object(requests, 'head', autospec=True)
    def test_show_no_content_length(self, head_mock):
        head_mock.return_value.status_code = http_client.OK
        head_mock.return_value.headers = {}
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.show, self.href)
        head_mock.assert_called_with(self.href, verify=True,
                                     timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_http_scheme(self, req_get_mock, shutil_mock):
        self.href = 'http://127.0.0.1:12345/fedora.qcow2'
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify=True,
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_verify_false(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'False')
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify=False,
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_verify_false_basic_auth_sucess(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'False')
        cfg.CONF.set_override('image_server_auth_strategy',
                              'http_basic',
                              'deploy')
        cfg.CONF.set_override('image_server_user', 'test', 'deploy')
        cfg.CONF.set_override('image_server_password', 'test', 'deploy')
        user = cfg.CONF.deploy.image_server_user
        password = cfg.CONF.deploy.image_server_password
        auth_creds = requests.auth.HTTPBasicAuth(user, password)
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify=False, timeout=60,
                                             auth=auth_creds)

    def test_download_success_verify_false_basic_auth_failed(self):
        cfg.CONF.set_override('webserver_verify_ca', 'False')
        cfg.CONF.set_override('image_server_auth_strategy',
                              'http_basic',
                              'deploy')
        file_mock = mock.Mock(spec=io.BytesIO)
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.download, self.href, file_mock)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_verify_true(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', 'True')
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify=True,
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_verify_path(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify='/some/path',
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_fail_verify_false_connerror(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', False)
        req_get_mock.side_effect = requests.ConnectionError()
        file_mock = mock.Mock(spec=io.BytesIO)
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_fail_verify_false_ioerror(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', False)
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        shutil_mock.side_effect = IOError
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify=False, timeout=60,
                                             auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_verify_true_connerror(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        response_mock = mock.Mock()
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        req_get_mock.side_effect = requests.ConnectionError

        file_mock = mock.Mock(spec=io.BytesIO)
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify='/some/path',
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_fail_verify_true_ioerror(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        shutil_mock.side_effect = IOError
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify='/some/path',
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_fail_verify_true_oserror(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_verify_ca', '/some/path')
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        shutil_mock.side_effect = OSError()
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify='/some/path',
                                             timeout=60, auth=None)

    @mock.patch.object(shutil, 'copyfileobj', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_download_success_custom_timeout(
            self, req_get_mock, shutil_mock):
        cfg.CONF.set_override('webserver_connection_timeout', 15)
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.raw = mock.MagicMock(spec=io.BytesIO)
        file_mock = mock.Mock(spec=io.BytesIO)
        self.service.download(self.href, file_mock)
        shutil_mock.assert_called_once_with(
            response_mock.raw.__enter__(), file_mock,
            image_service.IMAGE_CHUNK_SIZE
        )
        req_get_mock.assert_called_once_with(self.href, stream=True,
                                             verify=True,
                                             timeout=15, auth=None)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_success(self, req_get_mock):
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.text = 'value'
        self.assertEqual('value', self.service.get('http://url'))
        req_get_mock.assert_called_once_with('http://url', stream=False,
                                             verify=True, timeout=60,
                                             auth=None)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_handles_exceptions(self, req_get_mock):
        for exc in [OSError, requests.ConnectionError,
                    requests.RequestException, IOError]:
            req_get_mock.reset_mock()
            req_get_mock.side_effect = exc
            self.assertRaises(exception.ImageDownloadFailed,
                              self.service.get,
                              'http://url')
            req_get_mock.assert_called_once_with('http://url', stream=False,
                                                 verify=True, timeout=60,
                                                 auth=None)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_success_verify_false(self, req_get_mock):
        cfg.CONF.set_override('webserver_verify_ca', False)
        response_mock = req_get_mock.return_value
        response_mock.status_code = http_client.OK
        response_mock.text = 'value'
        self.assertEqual('value', self.service.get('http://url'))
        req_get_mock.assert_called_once_with('http://url', stream=False,
                                             verify=False, timeout=60,
                                             auth=None)


class FileImageServiceTestCase(base.TestCase):
    def setUp(self):
        super(FileImageServiceTestCase, self).setUp()
        self.service = image_service.FileImageService()
        self.href = 'file:///var/lib/ironic/images/image.qcow2'
        self.href_path = '/var/lib/ironic/images/image.qcow2'

    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    def test_validate_href(self, path_exists_mock):
        self.service.validate_href(self.href)
        path_exists_mock.assert_called_once_with(self.href_path)

    @mock.patch.object(os.path, 'isfile', return_value=False,
                       autospec=True)
    def test_validate_href_path_not_found_or_not_file(self, path_exists_mock):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service.validate_href, self.href)
        path_exists_mock.assert_called_once_with(self.href_path)

    @mock.patch.object(os.path, 'abspath', autospec=True)
    def test_validate_href_blocked_path(self, abspath_mock):
        href = 'file:///dev/sda1'
        href_path = '/dev/sda1'
        href_dir = '/dev'
        abspath_mock.side_effect = [href_dir, href_path]
        # Explicitly allow the bad path
        cfg.CONF.set_override('file_url_allowed_paths', [href_dir],
                              'conductor')

        # Still raises an error because /dev is expressly forbidden
        self.assertRaisesRegex(exception.ImageRefValidationFailed,
                               "is not permitted in file URLs",
                               self.service.validate_href, href)
        abspath_mock.assert_has_calls(
            [mock.call(href_dir), mock.call(href_path)])

    @mock.patch.object(os.path, 'abspath', autospec=True)
    def test_validate_href_empty_allowlist(self, abspath_mock):
        abspath_mock.return_value = self.href_path
        cfg.CONF.set_override('file_url_allowed_paths', [], 'conductor')
        self.assertRaisesRegex(exception.ImageRefValidationFailed,
                               "is not allowed for image source file URLs",
                               self.service.validate_href, self.href)

    @mock.patch.object(os.path, 'abspath', autospec=True)
    def test_validate_href_not_in_allowlist(self, abspath_mock):
        href = "file:///var/is/allowed/not/this/path/image.qcow2"
        href_path = "/var/is/allowed/not/this/path/image.qcow2"
        abspath_mock.side_effect = ['/var/lib/ironic', href_path]
        cfg.CONF.set_override('file_url_allowed_paths', ['/var/lib/ironic'],
                              'conductor')
        self.assertRaisesRegex(exception.ImageRefValidationFailed,
                               "is not allowed for image source file URLs",
                               self.service.validate_href, href)

    @mock.patch.object(os.path, 'abspath', autospec=True)
    @mock.patch.object(os.path, 'isfile',
                       return_value=True, autospec=True)
    def test_validate_href_in_allowlist(self,
                                        path_exists_mock,
                                        abspath_mock):
        href_dir = '/var/lib'  # self.href_path is in /var/lib/ironic/images/
        # First call is ironic.conf.types.ExplicitAbsolutePath
        # Second call is in validate_href()
        abspath_mock.side_effect = [href_dir, self.href_path]
        cfg.CONF.set_override('file_url_allowed_paths', [href_dir],
                              'conductor')
        result = self.service.validate_href(self.href)
        self.assertEqual(self.href_path, result)
        path_exists_mock.assert_called_once_with(self.href_path)
        abspath_mock.assert_has_calls(
            [mock.call(href_dir), mock.call(self.href_path)])

    @mock.patch.object(os.path, 'getmtime', return_value=1431087909.1641912,
                       autospec=True)
    @mock.patch.object(os.path, 'getsize', return_value=42, autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_show(self, _validate_mock, getsize_mock, getmtime_mock):
        _validate_mock.return_value = self.href_path
        result = self.service.show(self.href)
        getsize_mock.assert_called_once_with(self.href_path)
        getmtime_mock.assert_called_once_with(self.href_path)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        self.assertEqual({'size': 42,
                          'updated_at': datetime.datetime(2015, 5, 8,
                                                          12, 25, 9, 164191),
                          'properties': {},
                          'no_cache': True}, result)

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os.path, 'realpath', lambda p: p)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_hard_link(self, _validate_mock, remove_mock, link_mock,
                                copy_mock):
        _validate_mock.return_value = self.href_path
        file_mock = mock.Mock(spec=io.BytesIO)
        file_mock.name = 'file'
        self.service.download(self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        remove_mock.assert_called_once_with('file')
        link_mock.assert_called_once_with(self.href_path, 'file')
        copy_mock.assert_not_called()

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_copy(self, _validate_mock, remove_mock, link_mock,
                           copy_mock):
        _validate_mock.return_value = self.href_path
        link_mock.side_effect = PermissionError
        file_mock = mock.MagicMock(spec=io.BytesIO)
        file_mock.name = 'file'
        self.service.download(self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        link_mock.assert_called_once_with(self.href_path, 'file')
        copy_mock.assert_called_once_with(self.href_path, 'file')

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os.path, 'realpath', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_symlink(self, _validate_mock, remove_mock,
                              realpath_mock, link_mock, copy_mock):
        _validate_mock.return_value = self.href_path
        realpath_mock.side_effect = lambda p: p + '.real'
        file_mock = mock.MagicMock(spec=io.BytesIO)
        file_mock.name = 'file'
        self.service.download(self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        realpath_mock.assert_called_once_with(self.href_path)
        link_mock.assert_called_once_with(self.href_path + '.real', 'file')
        copy_mock.assert_not_called()

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(image_service.FileImageService, 'validate_href',
                       autospec=True)
    def test_download_copy_fail(self, _validate_mock, remove_mock, link_mock,
                                copy_mock):
        _validate_mock.return_value = self.href_path
        link_mock.side_effect = PermissionError
        copy_mock.side_effect = PermissionError
        file_mock = mock.MagicMock(spec=io.BytesIO)
        file_mock.name = 'file'
        self.assertRaises(exception.ImageDownloadFailed,
                          self.service.download, self.href, file_mock)
        _validate_mock.assert_called_once_with(mock.ANY, self.href)
        link_mock.assert_called_once_with(self.href_path, 'file')
        copy_mock.assert_called_once_with(self.href_path, 'file')


class OciImageServiceTestCase(base.TestCase):
    def setUp(self):
        super(OciImageServiceTestCase, self).setUp()
        self.service = image_service.OciImageService()
        self.href = 'oci://localhost/podman/machine-os:5.3'
        # NOTE(TheJulia): These test usesdata structures captured from
        # requests from quay.io with podman's machine-os container
        # image. As a result, they are a bit verbose and rather...
        # annoyingly large, but they are as a result, accurate.
        self.artifact_index = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': [
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:9d046091b3dbeda26e1f4364a116ca8d942840'
                               '00f103da7310e3a4703df1d3e4'),
                    'size': 475,
                    'annotations': {'disktype': 'applehv'},
                    'platform': {'architecture': 'x86_64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:f2981621c1bf821ce44c1cb31c507abe6293d8'
                               'eea646b029c6b9dc773fa7821a'),
                    'size': 476,
                    'annotations': {'disktype': 'applehv'},
                    'platform': {'architecture': 'aarch64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:3e42f5c348842b9e28bdbc9382962791a791a2'
                               'e5cdd42ad90e7d6807396c59db'),
                    'size': 475,
                    'annotations': {'disktype': 'hyperv'},
                    'platform': {'architecture': 'x86_64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:7efa5128a3a82e414cc8abd278a44f0c191a28'
                               '067e91154c238ef8df39966008'),
                    'size': 476,
                    'annotations': {'disktype': 'hyperv'},
                    'platform': {'architecture': 'aarch64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:dfcb3b199378320640d78121909409599b58b8'
                               '012ed93320dae48deacde44d45'),
                    'size': 474,
                    'annotations': {'disktype': 'qemu'},
                    'platform': {'architecture': 'x86_64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:1010f100f03dba1e5e2bad9905fd9f96ba8554'
                               '158beb7e6f030718001fa335d8'),
                    'size': 475,
                    'annotations': {'disktype': 'qemu'},
                    'platform': {'architecture': 'aarch64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:605c96503253b2e8cd4d1eb46c68e633192bb9'
                               'b61742cffb54ad7eb3aef7ad6b'),
                    'size': 11538,
                    'platform': {'architecture': 'amd64', 'os': 'linux'}},
                {
                    'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'digest': ('sha256:d9add02195d33fa5ec9a2b35076caae88eea3a'
                               '7fa15f492529b56c7813949a15'),
                    'size': 11535,
                    'platform': {'architecture': 'arm64', 'os': 'linux'}}
            ]
        }
        self.empty_artifact_index = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': []
        }

    @mock.patch.object(ociclient, 'get_manifest', autospec=True)
    @mock.patch.object(ociclient, 'get_artifact_index',
                       autospec=True)
    def test_identify_specific_image_local(
            self,
            mock_get_artifact_index,
            mock_get_manifest):

        mock_get_artifact_index.return_value = self.artifact_index
        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {
                'mediaType': 'application/vnd.oci.empty.v1+json',
                'digest': ('sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21'
                           'fe77e8310c060f61caaff8a'),
                'size': 2,
                'data': 'e30='},
            'layers': [
                {
                    'mediaType': 'application/zstd',
                    'digest': ('sha256:bf53aea26da8c4b2e4ca2d52db138e20fc7e73'
                               '0e6b34b866e9e8e39bcaaa2dc5'),
                    'size': 1059455878,
                    'annotations': {
                        'org.opencontainers.image.title': ('podman-machine.'
                                                           'x86_64.qemu.'
                                                           'qcow2.zst')
                    }
                }
            ]
        }

        expected_data = {
            'image_checksum': 'bf53aea26da8c4b2e4ca2d52db138e20fc7e730e6b34b866e9e8e39bcaaa2dc5',  # noqa
            'image_compression_type': 'zstd',
            'image_container_manifest_digest': 'sha256:dfcb3b199378320640d78121909409599b58b8012ed93320dae48deacde44d45',  # noqa
            'image_disk_format': 'qcow2',
            'image_filename': 'podman-machine.x86_64.qemu.qcow2.zst',
            'image_media_type': 'application/zstd',
            'image_request_authorization_secret': None,
            'image_size': 1059455878,
            'image_url': 'https://localhost/v2/podman/machine-os/blobs/sha256:bf53aea26da8c4b2e4ca2d52db138e20fc7e730e6b34b866e9e8e39bcaaa2dc5',  # noqa
            'oci_image_manifest_url': 'oci://localhost/podman/machine-os@sha256:dfcb3b199378320640d78121909409599b58b8012ed93320dae48deacde44d45'  # noqa
        }
        img_data = self.service.identify_specific_image(
            self.href, image_download_source='local')
        self.assertEqual(expected_data, img_data)
        mock_get_artifact_index.assert_called_once_with(mock.ANY, self.href)
        mock_get_manifest.assert_called_once_with(
            mock.ANY, self.href,
            'sha256:dfcb3b199378320640d78121909409599b58b8012ed93320dae48de'
            'acde44d45')

    @mock.patch.object(ociclient, 'get_manifest', autospec=True)
    @mock.patch.object(ociclient, 'get_artifact_index', autospec=True)
    def test_identify_specific_image(
            self, mock_get_artifact_index, mock_get_manifest):

        mock_get_artifact_index.return_value = self.artifact_index
        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {
                'mediaType': 'application/vnd.oci.empty.v1+json',
                'digest': ('sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21'
                           'fe77e8310c060f61caaff8a'),
                'size': 2,
                'data': 'e30='},
            'layers': [
                {
                    'mediaType': 'application/zstd',
                    'digest': ('sha256:047caa9c410038075055e1e41d520fc975a097'
                               '97838541174fa3066e58ebd8ea'),
                    'size': 1060062418,
                    'annotations': {
                        'org.opencontainers.image.title': ('podman-machine.'
                                                           'x86_64.applehv.'
                                                           'raw.zst')}
                }
            ]
        }

        expected_data = {
            'image_checksum': '047caa9c410038075055e1e41d520fc975a09797838541174fa3066e58ebd8ea',  # noqa
            'image_compression_type': 'zstd',
            'image_container_manifest_digest': 'sha256:9d046091b3dbeda26e1f4364a116ca8d94284000f103da7310e3a4703df1d3e4', # noqa
            'image_filename': 'podman-machine.x86_64.applehv.raw.zst',
            'image_disk_format': 'raw',
            'image_media_type': 'application/zstd',
            'image_request_authorization_secret': None,
            'image_size': 1060062418,
            'image_url': 'https://localhost/v2/podman/machine-os/blobs/sha256:047caa9c410038075055e1e41d520fc975a09797838541174fa3066e58ebd8ea',  # noqa
            'oci_image_manifest_url': 'oci://localhost/podman/machine-os@sha256:9d046091b3dbeda26e1f4364a116ca8d94284000f103da7310e3a4703df1d3e4'  # noqa
        }
        img_data = self.service.identify_specific_image(
            self.href, cpu_arch='amd64')
        self.assertEqual(expected_data, img_data)
        mock_get_artifact_index.assert_called_once_with(mock.ANY, self.href)
        mock_get_manifest.assert_called_once_with(
            mock.ANY, self.href,
            'sha256:9d046091b3dbeda26e1f4364a116ca8d94284000f103da7310e'
            '3a4703df1d3e4')

    @mock.patch.object(ociclient, 'get_manifest', autospec=True)
    @mock.patch.object(ociclient, 'get_artifact_index',
                       autospec=True)
    def test_identify_specific_image_aarch64(
            self,
            mock_get_artifact_index,
            mock_get_manifest):

        mock_get_artifact_index.return_value = self.artifact_index
        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {
                'mediaType': 'application/vnd.oci.empty.v1+json',
                'digest': ('sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21'
                           'fe77e8310c060f61caaff8a'),
                'size': 2,
                'data': 'e30='},
            'layers': [
                {
                    'mediaType': 'application/zstd',
                    'digest': ('sha256:13b69bec70305ccd85d47a0bd6d2357381c95'
                               '7cf87dceb862427aace4b964a2b'),
                    'size': 1013782193,
                    'annotations': {
                        'org.opencontainers.image.title': ('podman-machine.'
                                                           'aarch64.applehv'
                                                           '.raw.zst')}
                }
            ]
        }

        expected_data = {
            'image_checksum': '13b69bec70305ccd85d47a0bd6d2357381c957cf87dceb862427aace4b964a2b',  # noqa
            'image_compression_type': 'zstd',
            'image_container_manifest_digest': 'sha256:f2981621c1bf821ce44c1cb31c507abe6293d8eea646b029c6b9dc773fa7821a',  # noqa
            'image_disk_format': 'raw',
            'image_filename': 'podman-machine.aarch64.applehv.raw.zst',
            'image_media_type': 'application/zstd',
            'image_request_authorization_secret': None,
            'image_size': 1013782193,
            'image_url': 'https://localhost/v2/podman/machine-os/blobs/sha256:13b69bec70305ccd85d47a0bd6d2357381c957cf87dceb862427aace4b964a2b',  # noqa
            'oci_image_manifest_url': 'oci://localhost/podman/machine-os@sha256:f2981621c1bf821ce44c1cb31c507abe6293d8eea646b029c6b9dc773fa7821a'  # noqa
        }

        img_data = self.service.identify_specific_image(
            self.href, cpu_arch='aarch64')
        self.assertEqual(expected_data, img_data)
        mock_get_artifact_index.assert_called_once_with(mock.ANY, self.href)
        mock_get_manifest.assert_called_once_with(
            mock.ANY, self.href,
            'sha256:f2981621c1bf821ce44c1cb31c507abe6293d8eea646b029c6b9'
            'dc773fa7821a')

    @mock.patch.object(ociclient, 'get_manifest', autospec=True)
    @mock.patch.object(ociclient, 'get_artifact_index', autospec=True)
    def test_identify_specific_image_specific_digest(
            self, mock_get_artifact_index, mock_get_manifest):

        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {
                'mediaType': 'application/vnd.oci.empty.v1+json',
                'digest': ('sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21'
                           'fe77e8310c060f61caaff8a'),
                'size': 2,
                'data': 'e30='},
            'layers': [
                {
                    'mediaType': 'application/zstd',
                    'digest': ('sha256:047caa9c410038075055e1e41d520fc975a097'
                               '97838541174fa3066e58ebd8ea'),
                    'size': 1060062418,
                    'annotations': {
                        'org.opencontainers.image.title': ('podman-machine.'
                                                           'x86_64.applehv.'
                                                           'raw.zst')}
                }
            ]
        }

        expected_data = {
            'image_checksum': ('047caa9c410038075055e1e41d520fc975a0979783'
                               '8541174fa3066e58ebd8ea'),
            'image_disk_format': 'unknown',
            'image_request_authorization_secret': None,
            'image_url': ('https://localhost/v2/podman/machine-os/blobs/'
                          'sha256:047caa9c410038075055e1e41d520fc975a097'
                          '97838541174fa3066e58ebd8ea'),
            'oci_image_manifest_url': ('oci://localhost/podman/machine-os'
                                       '@sha256:9d046091b3dbeda26e1f4364a'
                                       '116ca8d94284000f103da7310e3a4703d'
                                       'f1d3e4')
        }
        url = ('oci://localhost/podman/machine-os@sha256:9d046091b3dbeda26e'
               '1f4364a116ca8d94284000f103da7310e3a4703df1d3e4')
        img_data = self.service.identify_specific_image(
            url, cpu_arch='amd64')
        self.assertEqual(expected_data, img_data)
        mock_get_artifact_index.assert_not_called()
        mock_get_manifest.assert_called_once_with(
            mock.ANY, url)

    @mock.patch.object(ociclient, 'get_manifest', autospec=True)
    @mock.patch.object(ociclient, 'get_artifact_index',
                       autospec=True)
    def test_identify_specific_image_bad_manifest(
            self,
            mock_get_artifact_index,
            mock_get_manifest):
        mock_get_artifact_index.return_value = self.empty_artifact_index
        self.assertRaises(exception.ImageNotFound,
                          self.service.identify_specific_image,
                          self.href)
        mock_get_artifact_index.assert_called_once_with(mock.ANY, self.href)
        mock_get_manifest.assert_not_called()

    @mock.patch.object(rs_helper, 'get', autospec=True)
    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch.object(ociclient, 'get_manifest', autospec=True)
    def test_download_direct_manifest_reference(self, mock_get_manifest,
                                                mock_open,
                                                mock_hash,
                                                mock_request):
        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {},
            'layers': [
                {
                    'mediaType': 'application/vnd.cyclonedx+json',
                    'size': 402627,
                    'digest': ('sha256:96f33f01d5347424f947e43ff05634915f422'
                               'debc2ca1bb88307824ff0c4b00d')}
            ]
        }

        response = mock_request.return_value
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        mock_open.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = mock_hash.return_value.hexdigest
        hexdigest_mock.return_value = ('96f33f01d5347424f947e43ff05634915f422'
                                       'debc2ca1bb88307824ff0c4b00d')
        self.service.download(
            'oci://localhost/project/container:latest@sha256:96f33'
            'f01d5347424f947e43ff05634915f422debc2ca1bb88307824ff0c4b00d',
            file_mock)
        mock_request.assert_called_once_with(
            mock.ANY,
            'https://localhost/v2/project/container/blobs/sha256:96f33f01d53'
            '47424f947e43ff05634915f422debc2ca1bb88307824ff0c4b00d',
            stream=True, timeout=60)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)

    @mock.patch.object(rs_helper, 'get', autospec=True)
    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch.object(ociclient, '_get_manifest', autospec=True)
    def test_download_direct_manifest_reference_just_digest(
            self, mock_get_manifest,
            mock_open,
            mock_hash,
            mock_request):
        # NOTE(TheJulia): This is ultimately exercising the interface between
        # the oci image service, and the oci registry client, and ultimately
        # the checksum_utils.TransferHelper logic.
        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {},
            'layers': [
                {
                    'mediaType': 'application/vnd.cyclonedx+json',
                    'size': 402627,
                    'digest': ('sha256:96f33f01d5347424f947e43ff05634915f422'
                               'debc2ca1bb88307824ff0c4b00d')}
            ]
        }  # noqa
        response = mock_request.return_value
        response.status_code = 200
        response.headers = {}
        csum = ('96f33f01d5347424f947e43ff05634915f422'
                'debc2ca1bb88307824ff0c4b00d')
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        mock_open.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = mock_hash.return_value.hexdigest
        hexdigest_mock.return_value = csum
        self.service.download(
            'oci://localhost/project/container@sha256:96f33f01d53'
            '47424f947e43ff05634915f422debc2ca1bb88307824ff0c4b00d',
            file_mock)
        mock_request.assert_called_once_with(
            mock.ANY,
            'https://localhost/v2/project/container/blobs/sha256:96f33f01d53'
            '47424f947e43ff05634915f422debc2ca1bb88307824ff0c4b00d',
            stream=True, timeout=60)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)
        self.assertEqual('sha256:' + csum,
                         self.service.transfer_verified_checksum)

    @mock.patch.object(ociclient, '_get_manifest', autospec=True)
    def test_show(self, mock_get_manifest):
        layer_csum = ('96f33f01d5347424f947e43ff05634915f422debc'
                      '2ca1bb88307824ff0c4b00d')
        mock_get_manifest.return_value = {
            'schemaVersion': 2,
            'mediaType': 'foo',
            'config': {},
            'layers': [{'mediaType': 'app/fee',
                        'size': 402627,
                        'digest': 'sha256:%s' % layer_csum}]
        }
        res = self.service.show(
            'oci://localhost/project/container@sha256:96f33f01d53'
            '47424f947e43ff05634915f422debc2ca1bb88307824ff0c4b00d')
        self.assertEqual(402627, res['size'])
        self.assertEqual(layer_csum, res['checksum'])
        self.assertEqual('sha256:' + layer_csum, res['digest'])

    @mock.patch.object(image_service.OciImageService, 'show', autospec=True)
    def test_validate_href(self, mock_show):
        self.service.validate_href("oci://foo")
        mock_show.assert_called_once_with(mock.ANY, "oci://foo")

    def test__validate_url_is_specific(self):
        csum = 'f' * 64
        self.service._validate_url_is_specific('oci://foo/bar@sha256:' + csum)
        csum = 'f' * 128
        self.service._validate_url_is_specific('oci://foo/bar@sha512:' + csum)

    def test__validate_url_is_specific_bad_format(self):
        self.assertRaises(exception.ImageRefValidationFailed,
                          self.service._validate_url_is_specific,
                          'oci://foo/bar@sha256')

    def test__validate_url_is_specific_not_specific(self):
        self.assertRaises(exception.OciImageNotSpecific,
                          self.service._validate_url_is_specific,
                          'oci://foo/bar')
        self.assertRaises(exception.OciImageNotSpecific,
                          self.service._validate_url_is_specific,
                          'oci://foo/bar:baz')
        self.assertRaises(exception.OciImageNotSpecific,
                          self.service._validate_url_is_specific,
                          'oci://foo/bar@baz:meow')


class ServiceGetterTestCase(base.TestCase):

    @mock.patch.object(glance_v2_service.GlanceImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_glance_image_service(self, glance_service_mock):
        image_href = uuidutils.generate_uuid()
        image_service.get_image_service(image_href, context=self.context)
        glance_service_mock.assert_called_once_with(mock.ANY, None,
                                                    self.context)

    @mock.patch.object(glance_v2_service.GlanceImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_glance_image_service_url(self, glance_service_mock):
        image_href = 'glance://%s' % uuidutils.generate_uuid()
        image_service.get_image_service(image_href, context=self.context)
        glance_service_mock.assert_called_once_with(mock.ANY, None,
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

    def test_get_image_service_invalid_image_ref(self):
        invalid_refs = (
            'usenet://alt.binaries.dvd/image.qcow2',
            'no scheme, no uuid')
        for image_ref in invalid_refs:
            self.assertRaises(exception.ImageRefValidationFailed,
                              image_service.get_image_service, image_ref)

    @mock.patch.object(image_service.OciImageService, '__init__',
                       return_value=None, autospec=True)
    def test_get_image_service_oci_url(self, oci_mock):
        image_hrefs = [
            'oci://fqdn.tld/user/image:tag@sha256:f00f',
            'oci://fqdn.tld/user/image:latest',
            'oci://fqdn.tld/user/image',
        ]
        for href in image_hrefs:
            image_service.get_image_service(href)
            oci_mock.assert_called_once_with(mock.ANY)
            oci_mock.reset_mock()

    def test_get_image_service_auth_override(self):
        test_node = mock.Mock()
        test_node.instance_info = {'image_pull_secret': 'foo'}
        test_node.driver_info = {'image_pull_secret': 'bar'}
        res = image_service.get_image_service_auth_override(test_node)
        self.assertDictEqual({'username': '',
                              'password': 'foo'}, res)

    def test_get_image_service_auth_override_no_user_auth(self):
        test_node = mock.Mock()
        test_node.instance_info = {'image_pull_secret': 'foo'}
        test_node.driver_info = {'image_pull_secret': 'bar'}
        res = image_service.get_image_service_auth_override(
            test_node, permit_user_auth=False)
        self.assertDictEqual({'username': '',
                              'password': 'bar'}, res)

    def test_get_image_service_auth_override_no_data(self):
        test_node = mock.Mock()
        test_node.instance_info = {}
        test_node.driver_info = {}
        res = image_service.get_image_service_auth_override(test_node)
        self.assertIsNone(res)

    def test_is_container_registry_url(self):
        self.assertFalse(image_service.is_container_registry_url(None))
        self.assertFalse(image_service.is_container_registry_url('https://'))
        self.assertTrue(image_service.is_container_registry_url('oci://.'))
