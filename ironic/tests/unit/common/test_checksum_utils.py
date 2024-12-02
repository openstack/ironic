# coding=utf-8

# Copyright 2024 Red Hat, Inc.
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

from unittest import mock

from oslo_config import cfg
from oslo_utils import fileutils

from ironic.common import checksum_utils
from ironic.common import exception
from ironic.common import image_service
from ironic.tests import base

CONF = cfg.CONF


@mock.patch.object(checksum_utils, 'compute_image_checksum',
                   autospec=True)
class IronicChecksumUtilsValidateTestCase(base.TestCase):

    def test_validate_checksum(self, mock_compute):
        mock_compute.return_value = 'f00'
        checksum_utils.validate_checksum('path', 'f00', 'algo')
        mock_compute.assert_called_once_with('path', 'algo')

    def test_validate_checksum_mixed_case(self, mock_compute):
        mock_compute.return_value = 'f00'
        checksum_utils.validate_checksum('path', 'F00', 'ALGO')
        mock_compute.assert_called_once_with('path', 'algo')

    def test_validate_checksum_mixed_md5(self, mock_compute):
        mock_compute.return_value = 'f00'
        checksum_utils.validate_checksum('path', 'F00')
        mock_compute.assert_called_once_with('path')

    def test_validate_checksum_mismatch(self, mock_compute):
        mock_compute.return_value = 'a00'
        self.assertRaises(exception.ImageChecksumError,
                          checksum_utils.validate_checksum,
                          'path', 'f00', 'algo')
        mock_compute.assert_called_once_with('path', 'algo')

    def test_validate_checksum_hashlib_not_supports_algo(self, mock_compute):
        mock_compute.side_effect = ValueError()
        self.assertRaises(exception.ImageChecksumAlgorithmFailure,
                          checksum_utils.validate_checksum,
                          'path', 'f00', 'algo')
        mock_compute.assert_called_once_with('path', 'algo')

    def test_validate_checksum_file_not_found(self, mock_compute):
        mock_compute.side_effect = OSError()
        self.assertRaises(exception.ImageChecksumFileReadFailure,
                          checksum_utils.validate_checksum,
                          'path', 'f00', 'algo')
        mock_compute.assert_called_once_with('path', 'algo')

    def test_validate_checksum_mixed_case_delimited(self, mock_compute):
        mock_compute.return_value = 'f00'
        checksum_utils.validate_checksum('path', 'algo:F00')
        mock_compute.assert_called_once_with('path', 'algo')


class IronicChecksumUtilsTestCase(base.TestCase):

    def test_is_checksum_url_string(self):
        self.assertFalse(checksum_utils.is_checksum_url('f00'))

    def test_is_checksum_url_file(self):
        self.assertFalse(checksum_utils.is_checksum_url('file://foo'))

    def test_is_checksum_url(self):
        urls = ['http://foo.local/file',
                'https://foo.local/file']
        for url in urls:
            self.assertTrue(checksum_utils.is_checksum_url(url))

    def test_get_checksum_and_algo_image_checksum(self):
        value = 'c46f2c98efe1cd246be1796cd842246e'
        i_info = {'image_checksum': value}
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        self.assertEqual(value, csum)
        self.assertIsNone(algo)

    def test_get_checksum_and_algo_image_checksum_not_allowed(self):
        CONF.set_override('allow_md5_checksum', False, group='agent')
        value = 'c46f2c98efe1cd246be1796cd842246e'
        i_info = {'image_checksum': value}
        self.assertRaises(exception.ImageChecksumAlgorithmFailure,
                          checksum_utils.get_checksum_and_algo,
                          i_info)

    def test_get_checksum_and_algo_image_checksum_glance(self):
        value = 'c46f2c98efe1cd246be1796cd842246e'
        i_info = {'image_os_hash_value': value,
                  'image_os_hash_algo': 'foobar'}
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        self.assertEqual(value, csum)
        self.assertEqual('foobar', algo)

    def test_get_checksum_and_algo_image_checksum_sha256(self):
        value = 'a' * 64
        i_info = {'image_checksum': value}
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        self.assertEqual(value, csum)
        self.assertEqual('sha256', algo)

    def test_get_checksum_and_algo_image_checksum_sha512(self):
        value = 'f' * 128
        i_info = {'image_checksum': value}
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        self.assertEqual(value, csum)
        self.assertEqual('sha512', algo)

    @mock.patch.object(checksum_utils, 'get_checksum_from_url', autospec=True)
    def test_get_checksum_and_algo_image_checksum_http_url(self, mock_get):
        value = 'http://checksum-url'
        i_info = {
            'image_checksum': value,
            'image_source': 'image-ref'
        }
        mock_get.return_value = 'f' * 64
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        mock_get.assert_called_once_with(value, 'image-ref')
        self.assertEqual('f' * 64, csum)
        self.assertEqual('sha256', algo)

    @mock.patch.object(checksum_utils, 'get_checksum_from_url', autospec=True)
    def test_get_checksum_and_algo_image_checksum_https_url(self, mock_get):
        value = 'https://checksum-url'
        i_info = {
            'image_checksum': value,
            'image_source': 'image-ref'
        }
        mock_get.return_value = 'f' * 128
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        mock_get.assert_called_once_with(value, 'image-ref')
        self.assertEqual('f' * 128, csum)
        self.assertEqual('sha512', algo)

    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    def test_get_checksum_and_algo_no_checksum_file_url(self, mock_cfc):
        i_info = {
            'image_source': 'file:///var/lib/ironic/images/foo.raw'
        }
        mock_cfc.return_value = 'f' * 64
        csum, algo = checksum_utils.get_checksum_and_algo(i_info)
        mock_cfc.assert_called_once_with('/var/lib/ironic/images/foo.raw',
                                         algorithm='sha256')
        self.assertEqual('f' * 64, csum)
        self.assertEqual('sha256', algo)

    def test_validate_text_checksum(self):
        csum = ('sha256:02edbb53017ded13c286e27d14285cb82f5a'
                '87f6dcbae280d6c53b5d98477bb7')
        res = checksum_utils.validate_text_checksum('me0w', csum)
        self.assertIsNone(res)

    def test_validate_text_checksum_invalid(self):
        self.assertRaises(exception.ImageChecksumError,
                          checksum_utils.validate_text_checksum,
                          'me0w', 'sha256:f00')


@mock.patch.object(image_service.HttpImageService, 'get',
                   autospec=True)
class IronicChecksumUtilsGetChecksumTestCase(base.TestCase):

    def test_get_checksum_from_url_empty_response(self, mock_get):
        mock_get.return_value = ''
        error = ('Failed to download image https://checksum-url, '
                 'reason: Checksum file empty.')
        self.assertRaisesRegex(exception.ImageDownloadFailed,
                               error,
                               checksum_utils.get_checksum_from_url,
                               'https://checksum-url',
                               'https://image-url/file')
        mock_get.assert_called_once_with('https://checksum-url')

    def test_get_checksum_from_url_one_line(self, mock_get):
        mock_get.return_value = 'a' * 32
        csum = checksum_utils.get_checksum_from_url(
            'https://checksum-url', 'https://image-url/file')
        mock_get.assert_called_once_with('https://checksum-url')
        self.assertEqual('a' * 32, csum)

    def test_get_checksum_from_url_nomatch_line(self, mock_get):
        mock_get.return_value = 'foobar'
        # For some reason assertRaisesRegex really doesn't like
        # the error. Easiest path is just to assertTrue the compare.
        exc = self.assertRaises(exception.ImageDownloadFailed,
                                checksum_utils.get_checksum_from_url,
                                'https://checksum-url',
                                'https://image-url/file')
        self.assertTrue(
            'Invalid checksum file (No valid checksum found' in str(exc))
        mock_get.assert_called_once_with('https://checksum-url')

    def test_get_checksum_from_url_multiline(self, mock_get):
        test_csum = ('f2ca1bb6c7e907d06dafe4687e579fce76b37e4e9'
                     '3b7605022da52e6ccc26fd2')
        mock_get.return_value = ('fee f00\n%s file\nbar fee\nf00' % test_csum)
        # For some reason assertRaisesRegex really doesn't like
        # the error. Easiest path is just to assertTrue the compare.
        checksum = checksum_utils.get_checksum_from_url(
            'https://checksum-url',
            'https://image-url/file')
        self.assertEqual(test_csum, checksum)
        mock_get.assert_called_once_with('https://checksum-url')

    def test_get_checksum_from_url_multiline_no_file(self, mock_get):
        test_csum = 'a' * 64
        error = ("Failed to download image https://checksum-url, reason: "
                 "Checksum file does not contain name file")
        mock_get.return_value = ('f00\n%s\nbar\nf00' % test_csum)
        # For some reason assertRaisesRegex really doesn't like
        # the error. Easiest path is just to assertTrue the compare.
        self.assertRaisesRegex(exception.ImageDownloadFailed,
                               error,
                               checksum_utils.get_checksum_from_url,
                               'https://checksum-url',
                               'https://image-url/file')
        mock_get.assert_called_once_with('https://checksum-url')
