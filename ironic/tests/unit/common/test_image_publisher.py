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
from unittest import mock

from ironic_lib import utils as ironic_utils

from ironic.common import image_publisher
from ironic.common import utils
from ironic.tests.unit.db import base as db_base


class SwiftPublisherTestCase(db_base.DbTestCase):

    container = "test"
    publisher = image_publisher.SwiftPublisher(container, 42)

    def test__append_filename_param_without_qs(self):
        res = self.publisher._append_filename_param(
            'http://a.b/c', 'b.img')
        expected = 'http://a.b/c?filename=b.img'
        self.assertEqual(expected, res)

    def test__append_filename_param_with_qs(self):
        res = self.publisher._append_filename_param(
            'http://a.b/c?d=e&f=g', 'b.img')
        expected = 'http://a.b/c?d=e&f=g&filename=b.img'
        self.assertEqual(expected, res)

    def test__append_filename_param_with_filename(self):
        res = self.publisher._append_filename_param(
            'http://a.b/c?filename=bootme.img', 'b.img')
        expected = 'http://a.b/c?filename=bootme.img'
        self.assertEqual(expected, res)

    @mock.patch.object(image_publisher, 'swift', autospec=True)
    def test_publish(self, mock_swift):
        mock_swift_api = mock_swift.SwiftAPI.return_value
        mock_swift_api.get_temp_url.return_value = 'https://a.b/c.f?e=f'

        url = self.publisher.publish('file.iso', 'boot.iso')

        self.assertEqual(
            'https://a.b/c.f?e=f&filename=file.iso', url)

        mock_swift.SwiftAPI.assert_called_once_with()

        mock_swift_api.create_object.assert_called_once_with(
            mock.ANY, mock.ANY, mock.ANY, mock.ANY)

        mock_swift_api.get_temp_url.assert_called_once_with(
            mock.ANY, mock.ANY, mock.ANY)

    @mock.patch.object(image_publisher, 'swift', autospec=True)
    def test_unpublish(self, mock_swift):
        object_name = 'boot.iso'

        self.publisher.unpublish(object_name)

        mock_swift.SwiftAPI.assert_called_once_with()
        mock_swift_api = mock_swift.SwiftAPI.return_value

        mock_swift_api.delete_object.assert_called_once_with(
            self.container, object_name)


class LocalPublisherTestCase(db_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.config(http_url='http://localhost', group='deploy')
        self.publisher = image_publisher.LocalPublisher('redfish')

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_local_link(
            self, mock_mkdir, mock_link, mock_chmod, mock_execute):
        url = self.publisher.publish('file.iso', 'boot.iso')
        self.assertEqual(
            'http://localhost/redfish/boot.iso', url)
        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)
        mock_link.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('file.iso', 0o644)
        mock_execute.assert_called_once_with(
            '/usr/sbin/restorecon', '-i', '-R', 'v', '/httpboot/redfish')

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_local_link_no_restorecon(
            self, mock_mkdir, mock_link, mock_copyfile, mock_chmod,
            mock_execute):
        url = self.publisher.publish('file.iso', 'boot.iso')
        self.assertEqual(
            'http://localhost/redfish/boot.iso', url)
        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)
        mock_link.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('file.iso', 0o644)
        mock_execute.return_value = FileNotFoundError
        mock_copyfile.assert_not_called()

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_external_ip(
            self, mock_mkdir, mock_link, mock_chmod, mock_execute):
        self.config(external_http_url='http://non-local.host', group='deploy')
        self.publisher = image_publisher.LocalPublisher(image_subdir='redfish')
        url = self.publisher.publish('file.iso', 'boot.iso')
        self.assertEqual(
            'http://non-local.host/redfish/boot.iso', url)
        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)
        mock_link.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('file.iso', 0o644)
        mock_execute.assert_called_once_with(
            '/usr/sbin/restorecon', '-i', '-R', 'v', '/httpboot/redfish')

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_external_ip_node_override(
            self, mock_mkdir, mock_link, mock_chmod, mock_execute):
        self.config(external_http_url='http://non-local.host', group='deploy')
        override_url = "http://node.override.url"
        self.publisher = image_publisher.LocalPublisher(
            image_subdir='redfish', root_url=override_url)
        url = self.publisher.publish('file.iso', 'boot.iso')
        self.assertEqual(
            'http://node.override.url/redfish/boot.iso', url)
        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)
        mock_link.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('file.iso', 0o644)
        mock_execute.assert_called_once_with(
            '/usr/sbin/restorecon', '-i', '-R', 'v', '/httpboot/redfish')

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_local_copy(self, mock_mkdir, mock_link,
                                mock_copyfile, mock_chmod):
        mock_link.side_effect = OSError()

        url = self.publisher.publish('file.iso', 'boot.iso')

        self.assertEqual(
            'http://localhost/redfish/boot.iso', url)

        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)

        mock_copyfile.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('/httpboot/redfish/boot.iso',
                                           0o644)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    def test_unpublish_local(self, mock_unlink):
        object_name = 'boot.iso'
        expected_file = '/httpboot/redfish/' + object_name

        self.publisher.unpublish(object_name)

        mock_unlink.assert_called_once_with(expected_file)
