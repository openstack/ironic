# Copyright 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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


import datetime
import importlib
import time
from unittest import mock

from keystoneauth1 import exceptions as ks_exception
from keystoneauth1 import loading as ks_loading
import openstack
from openstack.connection import exceptions as openstack_exc
from oslo_config import cfg
from oslo_utils import uuidutils
import testtools

from ironic.common import context
from ironic.common import exception
from ironic.common.glance_service import image_service
from ironic.common.glance_service import service_utils
from ironic.common import swift
from ironic.tests import base
from ironic.tests.unit import stubs


CONF = cfg.CONF


class NullWriter(object):
    """Used to test ImageService.get which takes a writer object."""

    def write(self, *arg, **kwargs):
        pass


class TestGlanceSerializer(testtools.TestCase):
    def test_serialize(self):
        metadata = {'name': 'image1',
                    'foo': 'bar',
                    'properties': {
                        'prop1': 'propvalue1',
                        'mappings': '['
                        '{"virtual":"aaa","device":"bbb"},'
                        '{"virtual":"xxx","device":"yyy"}]',
                        'block_device_mapping': '['
                        '{"virtual_device":"fake","device_name":"/dev/fake"},'
                        '{"virtual_device":"ephemeral0",'
                        '"device_name":"/dev/fake0"}]'}}

        expected = {
            'name': 'image1',
            'foo': 'bar',
            'properties': {'prop1': 'propvalue1',
                           'mappings': [
                               {'virtual': 'aaa',
                                'device': 'bbb'},
                               {'virtual': 'xxx',
                                'device': 'yyy'},
                           ],
                           'block_device_mapping': [
                               {'virtual_device': 'fake',
                                'device_name': '/dev/fake'},
                               {'virtual_device': 'ephemeral0',
                                'device_name': '/dev/fake0'}
                           ]
                           }
        }
        converted = service_utils._convert(metadata)
        self.assertEqual(expected, converted)


class TestGlanceImageService(base.TestCase):
    NOW_GLANCE_OLD_FORMAT = "2010-10-11T10:30:22"
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"

    NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22)

    def setUp(self):
        super(TestGlanceImageService, self).setUp()
        self.client = stubs.StubGlanceClient()
        self.context = context.RequestContext(auth_token=True)
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.service = image_service.GlanceImageService(self.client,
                                                        self.context)

    @staticmethod
    def _make_fixture(**kwargs):
        fixture = {'name': None,
                   'owner': None,
                   'properties': {},
                   'status': "active",
                   'visibility': "public"}
        fixture.update(kwargs)
        return openstack.image.v2.image.Image.new(**fixture)

    @property
    def endpoint(self):
        # For glanceclient versions >= 0.13, the endpoint is located
        # under http_client (blueprint common-client-library-2)
        # I5addc38eb2e2dd0be91b566fda7c0d81787ffa75
        # Test both options to keep backward compatibility
        if getattr(self.service.client, 'endpoint', None):
            endpoint = self.service.client.endpoint
        else:
            endpoint = self.service.client.http_client.endpoint
        return endpoint

    def _make_datetime_fixture(self):
        return self._make_fixture(created_at=self.NOW_GLANCE_FORMAT,
                                  updated_at=self.NOW_GLANCE_FORMAT,
                                  deleted_at=self.NOW_GLANCE_FORMAT)

    def test_show_passes_through_to_client(self):
        image_id = uuidutils.generate_uuid()
        image = self._make_fixture(name='image1', id=image_id)
        expected = {
            'checksum': None,
            'container_format': None,
            'created_at': None,
            'deleted': None,
            'deleted_at': None,
            'disk_format': None,
            'file': None,
            'id': image_id,
            'min_disk': None,
            'min_ram': None,
            'name': 'image1',
            'owner': None,
            'properties': {},
            'protected': None,
            'schema': None,
            'size': None,
            'status': "active",
            'tags': [],
            'updated_at': None,
            'visibility': "public",
            'os_hash_algo': None,
            'os_hash_value': None,
        }
        with mock.patch.object(self.service, 'call', autospec=True):
            self.service.call.return_value = image
            image_meta = self.service.show(image_id)
            self.service.call.assert_called_with('get_image', image_id)
            self.assertEqual(expected, image_meta)

    def test_show_makes_datetimes(self):
        image_id = uuidutils.generate_uuid()
        image = self._make_datetime_fixture()
        with mock.patch.object(self.service, 'call', autospec=True):
            self.service.call.return_value = image
            image_meta = self.service.show(image_id)
            self.service.call.assert_called_with('get_image', image_id)
            self.assertEqual(self.NOW_DATETIME, image_meta['created_at'])
            self.assertEqual(self.NOW_DATETIME, image_meta['updated_at'])

    @mock.patch.object(service_utils, 'is_image_active', autospec=True)
    def test_show_raises_when_no_authtoken_in_the_context(self,
                                                          mock_is_active):
        self.context.auth_token = False
        mock_is_active.return_value = True
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          uuidutils.generate_uuid())

    def test_show_raises_when_image_not_active(self):
        image_id = uuidutils.generate_uuid()
        image = self._make_fixture(name='image1', id=image_id, status="queued")
        with mock.patch.object(self.service, 'call', autospec=True):
            self.service.call.return_value = image
            self.assertRaises(exception.ImageUnacceptable,
                              self.service.show, image_id)

    def test_download_with_retries(self):
        tries = [0]

        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that fails the first time, then succeeds."""

            def get_image(self, image_id):
                if tries[0] == 0:
                    tries[0] = 1
                    raise ks_exception.ServiceUnavailable()
                else:
                    return {}

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = image_service.GlanceImageService(stub_client,
                                                        stub_context)
        stub_service.call.retry.sleep = mock.Mock()
        image_id = uuidutils.generate_uuid()
        writer = NullWriter()

        # When retries are disabled, we should get an exception
        self.config(num_retries=0, group='glance')
        self.assertRaises(exception.GlanceConnectionFailed,
                          stub_service.download, image_id, writer)

        # Now lets enable retries. No exception should happen now.
        self.config(num_retries=1, group='glance')
        importlib.reload(image_service)
        stub_service = image_service.GlanceImageService(stub_client,
                                                        stub_context)
        tries = [0]
        stub_service.download(image_id, writer)

    def test_download_no_data(self):
        self.client.image_data = b''
        image_id = uuidutils.generate_uuid()

        image = self._make_datetime_fixture()
        with mock.patch.object(self.client, 'get_image', return_value=image,
                               autospec=True):
            self.assertRaisesRegex(exception.ImageDownloadFailed,
                                   'image contains no data',
                                   self.service.download, image_id)

    @mock.patch.object(service_utils, '_GLANCE_SESSION', autospec=True)
    @mock.patch('os.sendfile', autospec=True)
    @mock.patch('os.path.getsize', autospec=True)
    @mock.patch('%s.open' % __name__, new=mock.mock_open(), create=True)
    def test_download_file_url(self, mock_getsize, mock_sendfile,
                               mock_serviceutils_glance):
        # NOTE: only in v2 API
        class MyGlanceStubClient(stubs.StubGlanceClient):

            """A client that returns a file url."""

            s_tmpfname = '/whatever/source'

            def get_image(self, image_id):
                direct_url = "file://%s" + self.s_tmpfname
                return type('GlanceTestDirectUrlMeta', (object,),
                            dict(visibility='public', direct_url=direct_url))

        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_client = MyGlanceStubClient()

        stub_service = image_service.GlanceImageService(stub_client,
                                                        context=stub_context)
        mock_serviceutils_glance.return_value = stub_service
        image_id = uuidutils.generate_uuid()

        self.config(allowed_direct_url_schemes=['file'], group='glance')

        # patching open in image_service module namespace
        # to make call-spec assertions
        with mock.patch('ironic.common.glance_service.image_service.open',
                        new=mock.mock_open(), create=True) as mock_ironic_open:
            with open('/whatever/target', 'w') as mock_target_fd:
                stub_service.download(image_id, mock_target_fd)

        # assert the image data was neither read nor written
        # but rather sendfiled
        mock_ironic_open.assert_called_once_with(MyGlanceStubClient.s_tmpfname,
                                                 'r')
        mock_source_fd = mock_ironic_open()
        self.assertFalse(mock_source_fd.read.called)
        self.assertFalse(mock_target_fd.write.called)
        mock_sendfile.assert_called_once_with(
            mock_target_fd.fileno(),
            mock_source_fd.fileno(),
            0,
            mock_getsize(MyGlanceStubClient.s_tmpfname))

    def test_client_forbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a Forbidden exception."""

            def get_image(self, image_id):
                raise openstack_exc.ForbiddenException()

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = image_service.GlanceImageService(stub_client,
                                                        stub_context)
        image_id = uuidutils.generate_uuid()
        writer = NullWriter()
        self.assertRaises(exception.ImageNotAuthorized, stub_service.download,
                          image_id, writer)

    def test_client_notfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a NotFound exception."""

            def get_image(self, image_id):
                raise openstack_exc.NotFoundException()

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = image_service.GlanceImageService(stub_client,
                                                        stub_context)
        image_id = uuidutils.generate_uuid()
        writer = NullWriter()
        self.assertRaises(exception.ImageNotFound, stub_service.download,
                          image_id, writer)


@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_service_auth', autospec=True,
            return_value=mock.sentinel.sauth)
@mock.patch('ironic.common.keystone.get_adapter', autospec=True)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(openstack.connection, 'Connection', autospec=True)
class CheckImageServiceTestCase(base.TestCase):
    def setUp(self):
        super(CheckImageServiceTestCase, self).setUp()
        self.context = context.RequestContext(global_request_id='global')
        self.service = image_service.GlanceImageService(None, self.context)
        # NOTE(pas-ha) register keystoneauth dynamic options manually
        plugin = ks_loading.get_plugin_loader('password')
        opts = ks_loading.get_auth_plugin_conf_options(plugin)
        self.cfg_fixture.register_opts(opts, group='glance')
        self.config(auth_type='password',
                    auth_url='viking',
                    username='spam',
                    password='ham',
                    project_name='parrot',
                    service_type='image',
                    region_name='SomeRegion',
                    interface='internal',
                    group='glance')
        image_service._GLANCE_SESSION = None

    def test_check_image_service_client_already_set(self, mock_gclient,
                                                    mock_sess, mock_adapter,
                                                    mock_sauth, mock_auth):
        def func(self):
            return True

        self.service.client = True

        wrapped_func = image_service.check_image_service(func)
        self.assertTrue(wrapped_func(self.service))
        self.assertEqual(0, mock_gclient.call_count)
        self.assertEqual(0, mock_sess.call_count)
        self.assertEqual(0, mock_adapter.call_count)
        self.assertEqual(0, mock_auth.call_count)
        self.assertEqual(0, mock_sauth.call_count)

    def _assert_connnection_call(self, mock_gclient, url):
        mock_gclient.assert_called_once_with(
            session=mock.sentinel.session,
            image_endpoint_override=url,
            image_api_version='2')

    def test_check_image_service__config_auth(self, mock_gclient, mock_sess,
                                              mock_adapter, mock_sauth,
                                              mock_auth):
        def func(service, *args, **kwargs):
            return args, kwargs

        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'glance_url'
        uuid = uuidutils.generate_uuid()
        params = {'image_href': uuid}

        wrapped_func = image_service.check_image_service(func)
        self.assertEqual(((), params), wrapped_func(self.service, **params))
        self._assert_connnection_call(mock_gclient, 'glance_url')
        mock_auth.assert_called_once_with('glance')
        mock_sess.assert_has_calls([
            mock.call('glance'),
            mock.call('glance', auth=mock.sentinel.auth)
        ])
        mock_adapter.assert_called_once_with('glance',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        adapter.get_endpoint.assert_called_once_with()
        self.assertEqual(0, mock_sauth.call_count)

    def test_check_image_service__token_auth(self, mock_gclient, mock_sess,
                                             mock_adapter, mock_sauth,
                                             mock_auth):
        def func(service, *args, **kwargs):
            return args, kwargs

        self.service.context = context.RequestContext(
            auth_token='token', global_request_id='global')
        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'glance_url'
        uuid = uuidutils.generate_uuid()
        params = {'image_href': uuid}

        wrapped_func = image_service.check_image_service(func)
        self.assertEqual(((), params), wrapped_func(self.service, **params))
        self._assert_connnection_call(mock_gclient, 'glance_url')
        mock_sess.assert_has_calls([
            mock.call('glance'),
            mock.call('glance', auth=mock.sentinel.sauth)
        ])
        mock_adapter.assert_called_once_with('glance',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        mock_sauth.assert_called_once_with(self.service.context, 'glance_url',
                                           mock.sentinel.auth)
        mock_auth.assert_called_once_with('glance')

    def test_check_image_service__no_auth(self, mock_gclient, mock_sess,
                                          mock_adapter, mock_sauth, mock_auth):
        def func(service, *args, **kwargs):
            return args, kwargs

        self.config(endpoint_override='foo',
                    auth_type='none',
                    group='glance')
        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'foo'
        uuid = uuidutils.generate_uuid()
        params = {'image_href': uuid}

        wrapped_func = image_service.check_image_service(func)
        self.assertEqual(((), params), wrapped_func(self.service, **params))
        self.assertEqual('none', image_service.CONF.glance.auth_type)
        self._assert_connnection_call(mock_gclient, 'foo')
        mock_sess.assert_has_calls([
            mock.call('glance'),
            mock.call('glance', auth=mock.sentinel.auth)
        ])
        mock_adapter.assert_called_once_with('glance',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        self.assertEqual(0, mock_sauth.call_count)


class TestGlanceSwiftTempURL(base.TestCase):
    def setUp(self):
        super(TestGlanceSwiftTempURL, self).setUp()
        client = stubs.StubGlanceClient()
        self.context = context.RequestContext()
        self.context.auth_token = 'fake'
        self.service = image_service.GlanceImageService(client, self.context)
        self.config(swift_temp_url_key='correcthorsebatterystaple',
                    group='glance')
        self.config(swift_endpoint_url='https://swift.example.com',
                    group='glance')
        self.config(swift_account='AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30',
                    group='glance')
        self.config(swift_api_version='v1',
                    group='glance')
        self.config(swift_container='glance',
                    group='glance')
        self.config(swift_temp_url_duration=1200,
                    group='glance')
        self.config(swift_store_multiple_containers_seed=0,
                    group='glance')
        self.fake_image = {
            'id': '757274c4-2856-4bd2-bb20-9a4a231e187b'
        }

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url(self, swift_mock):

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_endpoint_detected(self, swift_mock,
                                              adapter_mock, session_mock):
        self.config(swift_endpoint_url=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        endpoint = 'http://another.example.com:8080'
        adapter_mock.return_value.get_endpoint.return_value = endpoint

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(endpoint + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_endpoint_with_suffix(self, swift_mock,
                                                 adapter_mock, session_mock):
        self.config(swift_endpoint_url=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        endpoint = 'http://another.example.com:8080'
        adapter_mock.return_value.get_endpoint.return_value = (
            endpoint + '/v1/AUTH_foobar')

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(endpoint + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_account_detected(self, swift_mock, session_mock):
        self.config(swift_account=None, group='glance')

        path = ('/v1/AUTH_42/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        auth_ref = session_mock.return_value.auth.get_auth_ref.return_value
        auth_ref.project_id = '42'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')
        session_mock.assert_called_once_with()

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_account_detected_with_prefix(self, swift_mock,
                                                         session_mock):
        self.config(swift_account=None, group='glance')
        self.config(swift_account_prefix='SWIFTPREFIX', group='glance')

        path = ('/v1/SWIFTPREFIX_42/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        auth_ref = session_mock.return_value.auth.get_auth_ref.return_value
        auth_ref.project_id = '42'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')
        session_mock.assert_called_once_with()

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_account_detected_with_prefix_underscore(
            self, swift_mock, session_mock):
        self.config(swift_account=None, group='glance')
        self.config(swift_account_prefix='SWIFTPREFIX_', group='glance')

        path = ('/v1/SWIFTPREFIX_42/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        auth_ref = session_mock.return_value.auth.get_auth_ref.return_value
        auth_ref.project_id = '42'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')
        session_mock.assert_called_once_with()

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_key_detected(self, swift_mock):
        self.config(swift_temp_url_key=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        swift_mock.return_value.get_temp_url_key.return_value = 'secret'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key='secret',
            method='GET')

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_no_key_detected(self, swift_mock):
        self.config(swift_temp_url_key=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        swift_mock.return_value.get_temp_url_key.return_value = None

        self.service._validate_temp_url_config = mock.Mock()

        self.assertRaises(exception.InvalidParameterValue,
                          self.service.swift_temp_url,
                          image_info=self.fake_image)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_invalid_image_info(self, swift_mock):
        self.service._validate_temp_url_config = mock.Mock()
        image_info = {}
        tempurl_mock = swift_mock.return_value.generate_temp_url
        self.assertRaises(exception.ImageUnacceptable,
                          self.service.swift_temp_url, image_info)
        image_info = {'id': 'not an id'}
        self.assertRaises(exception.ImageUnacceptable,
                          self.service.swift_temp_url, image_info)
        self.assertFalse(tempurl_mock.called)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_swift_temp_url_multiple_containers(self, swift_mock):

        self.config(swift_store_multiple_containers_seed=8,
                    group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance_757274c4'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')

    def test_swift_temp_url_url_bad_no_info(self):
        self.assertRaises(exception.ImageUnacceptable,
                          self.service.swift_temp_url,
                          image_info={})

    def test__validate_temp_url_config(self):
        self.service._validate_temp_url_config()

    def test__validate_temp_url_no_key_no_exception(self):
        self.config(swift_temp_url_key=None, group='glance')
        self.service._validate_temp_url_config()

    def test__validate_temp_url_endpoint_less_than_download_delay(self):
        self.config(swift_temp_url_expected_download_start_delay=1000,
                    group='glance')
        self.config(swift_temp_url_duration=15,
                    group='glance')
        self.assertRaises(exception.InvalidParameterValue,
                          self.service._validate_temp_url_config)

    def test__validate_temp_url_multiple_containers(self):
        self.config(swift_store_multiple_containers_seed=-1,
                    group='glance')
        self.assertRaises(exception.InvalidParameterValue,
                          self.service._validate_temp_url_config)
        self.config(swift_store_multiple_containers_seed=None,
                    group='glance')
        self.assertRaises(exception.InvalidParameterValue,
                          self.service._validate_temp_url_config)
        self.config(swift_store_multiple_containers_seed=33,
                    group='glance')
        self.assertRaises(exception.InvalidParameterValue,
                          self.service._validate_temp_url_config)


class TestSwiftTempUrlCache(base.TestCase):

    def setUp(self):
        super(TestSwiftTempUrlCache, self).setUp()
        client = stubs.StubGlanceClient()
        self.context = context.RequestContext()
        self.context.auth_token = 'fake'
        self.config(swift_temp_url_expected_download_start_delay=100,
                    group='glance')
        self.config(swift_temp_url_key='correcthorsebatterystaple',
                    group='glance')
        self.config(swift_endpoint_url='https://swift.example.com',
                    group='glance')
        self.config(swift_account='AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30',
                    group='glance')
        self.config(swift_api_version='v1',
                    group='glance')
        self.config(swift_container='glance',
                    group='glance')
        self.config(swift_temp_url_duration=1200,
                    group='glance')
        self.config(swift_temp_url_cache_enabled=True,
                    group='glance')
        self.config(swift_store_multiple_containers_seed=0,
                    group='glance')
        self.glance_service = image_service.GlanceImageService(
            client, context=self.context)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_add_items_to_cache(self, swift_mock):
        fake_image = {
            'id': uuidutils.generate_uuid()
        }

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/%s' % fake_image['id'])
        exp_time = int(time.time()) + 1200
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=%s' % exp_time)

        cleanup_mock = mock.Mock()
        self.glance_service._remove_expired_items_from_cache = cleanup_mock
        self.glance_service._validate_temp_url_config = mock.Mock()

        temp_url = self.glance_service.swift_temp_url(
            image_info=fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        cleanup_mock.assert_called_once_with()
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')
        self.assertEqual((temp_url, exp_time),
                         self.glance_service._cache[fake_image['id']])

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_return_cached_tempurl(self, swift_mock):
        fake_image = {
            'id': uuidutils.generate_uuid()
        }

        exp_time = int(time.time()) + 1200
        temp_url = CONF.glance.swift_endpoint_url + (
            '/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
            '/glance'
            '/%(uuid)s'
            '?temp_url_sig=hmacsig&temp_url_expires=%(exp_time)s' %
            {'uuid': fake_image['id'], 'exp_time': exp_time}
        )
        tempurl_mock = swift_mock.return_value.generate_temp_url
        self.glance_service._cache[fake_image['id']] = (
            image_service.TempUrlCacheElement(url=temp_url,
                                              url_expires_at=exp_time)
        )

        cleanup_mock = mock.Mock()
        self.glance_service._remove_expired_items_from_cache = cleanup_mock
        self.glance_service._validate_temp_url_config = mock.Mock()

        self.assertEqual(
            temp_url, self.glance_service.swift_temp_url(image_info=fake_image)
        )

        cleanup_mock.assert_called_once_with()
        self.assertFalse(tempurl_mock.called)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_do_not_return_expired_tempurls(self, swift_mock):
        fake_image = {
            'id': uuidutils.generate_uuid()
        }
        old_exp_time = int(time.time()) + 99
        path = (
            '/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
            '/glance'
            '/%s' % fake_image['id']
        )
        query = '?temp_url_sig=hmacsig&temp_url_expires=%s'
        self.glance_service._cache[fake_image['id']] = (
            image_service.TempUrlCacheElement(
                url=(CONF.glance.swift_endpoint_url + path
                     + query % old_exp_time),
                url_expires_at=old_exp_time)
        )

        new_exp_time = int(time.time()) + 1200
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + query % new_exp_time)

        self.glance_service._validate_temp_url_config = mock.Mock()

        fresh_temp_url = self.glance_service.swift_temp_url(
            image_info=fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         fresh_temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')
        self.assertEqual(
            (fresh_temp_url, new_exp_time),
            self.glance_service._cache[fake_image['id']])

    def test_remove_expired_items_from_cache(self):
        expired_items = {
            uuidutils.generate_uuid(): image_service.TempUrlCacheElement(
                'fake-url-1',
                int(time.time()) - 10
            ),
            uuidutils.generate_uuid(): image_service.TempUrlCacheElement(
                'fake-url-2',
                int(time.time()) + 90  # Agent won't be able to start in time
            )
        }
        valid_items = {
            uuidutils.generate_uuid(): image_service.TempUrlCacheElement(
                'fake-url-3',
                int(time.time()) + 1000
            ),
            uuidutils.generate_uuid(): image_service.TempUrlCacheElement(
                'fake-url-4',
                int(time.time()) + 2000
            )
        }
        self.glance_service._cache.update(expired_items)
        self.glance_service._cache.update(valid_items)
        self.glance_service._remove_expired_items_from_cache()
        for uuid in valid_items:
            self.assertEqual(valid_items[uuid],
                             self.glance_service._cache[uuid])
        for uuid in expired_items:
            self.assertNotIn(uuid, self.glance_service._cache)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def _test__generate_temp_url(self, fake_image, swift_mock):
        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/%s' % fake_image['id'])
        tempurl_mock = swift_mock.return_value.generate_temp_url
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')

        self.glance_service._validate_temp_url_config = mock.Mock()

        temp_url = self.glance_service._generate_temp_url(
            path, seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key, method='GET',
            endpoint=CONF.glance.swift_endpoint_url,
            image_id=fake_image['id']
        )

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            timeout=CONF.glance.swift_temp_url_duration,
            temp_url_key=CONF.glance.swift_temp_url_key,
            method='GET')

    def test_swift_temp_url_cache_enabled(self):
        fake_image = {
            'id': uuidutils.generate_uuid()
        }
        rm_expired = mock.Mock()
        self.glance_service._remove_expired_items_from_cache = rm_expired
        self._test__generate_temp_url(fake_image)
        rm_expired.assert_called_once_with()
        self.assertIn(fake_image['id'], self.glance_service._cache)

    def test_swift_temp_url_cache_disabled(self):
        self.config(swift_temp_url_cache_enabled=False,
                    group='glance')
        fake_image = {
            'id': uuidutils.generate_uuid()
        }
        rm_expired = mock.Mock()
        self.glance_service._remove_expired_items_from_cache = rm_expired
        self._test__generate_temp_url(fake_image)
        self.assertFalse(rm_expired.called)
        self.assertNotIn(fake_image['id'], self.glance_service._cache)


class TestServiceUtils(base.TestCase):

    def setUp(self):
        super(TestServiceUtils, self).setUp()
        service_utils._GLANCE_API_SERVER = None

    def test_parse_image_id_from_uuid(self):
        image_href = uuidutils.generate_uuid()
        parsed_id = service_utils.parse_image_id(image_href)
        self.assertEqual(image_href, parsed_id)

    def test_parse_image_id_from_glance(self):
        uuid = uuidutils.generate_uuid()
        image_href = u'glance://some-stuff/%s' % uuid
        parsed_id = service_utils.parse_image_id(image_href)
        self.assertEqual(uuid, parsed_id)

    def test_parse_image_id_from_glance_fail(self):
        self.assertRaises(exception.InvalidImageRef,
                          service_utils.parse_image_id, u'glance://not-a-uuid')

    def test_parse_image_id_fail(self):
        self.assertRaises(exception.InvalidImageRef,
                          service_utils.parse_image_id,
                          u'http://spam.ham/eggs')

    def test_is_glance_image(self):
        image_href = u'uui\u0111'
        self.assertFalse(service_utils.is_glance_image(image_href))
        image_href = u'733d1c44-a2ea-414b-aca7-69decf20d810'
        self.assertTrue(service_utils.is_glance_image(image_href))
        image_href = u'glance://uui\u0111'
        self.assertTrue(service_utils.is_glance_image(image_href))
        image_href = 'http://aaa/bbb'
        self.assertFalse(service_utils.is_glance_image(image_href))
        image_href = None
        self.assertFalse(service_utils.is_glance_image(image_href))


class TestIsImageAvailable(base.TestCase):

    def setUp(self):
        super(TestIsImageAvailable, self).setUp()
        self.image = mock.Mock()
        self.context = context.RequestContext()
        self.context.roles = []

    def test_allow_access_via_auth_token_enabled(self):
        self.context.auth_token = 'fake-token'
        self.config(allow_image_access_via_auth_token=True)
        self.assertTrue(service_utils.is_image_available(
            self.context, self.image))

    def test_allow_public_image(self):
        self.image.visibility = 'public'
        self.assertTrue(service_utils.is_image_available(
            self.context, self.image))

    def test_allow_community_image(self):
        self.image.visibility = 'community'
        self.assertTrue(service_utils.is_image_available(
            self.context, self.image))

    def test_allow_admin_if_config_enabled(self):
        self.context.roles = ['admin']
        self.config(ignore_project_check_for_admin_tasks=True)
        self.assertTrue(service_utils.is_image_available(
            self.context, self.image))

    def test_allow_private_image_owned_by_conductor(self):
        self.image.visibility = 'private'
        self.image.owner = service_utils.get_conductor_project_id()
        self.assertTrue(service_utils.is_image_available(
            self.context, self.image))

    @mock.patch.object(service_utils, 'get_image_member_list', autospec=True)
    def test_allow_shared_image_if_member(self, mock_get_members):
        self.image.visibility = 'shared'
        self.image.id = 'shared-image-id'
        self.image.owner = 'some-other-project'

        self.context.project = 'test-project'

        # Mock the conductor project ID and the shared member list
        conductor_id = service_utils.get_conductor_project_id()
        mock_get_members.return_value = [conductor_id]

        self.assertTrue(service_utils.is_image_available(
            self.context, self.image))
        mock_get_members.assert_called_once_with('shared-image-id',
                                                 self.context)

    def test_deny_private_image_different_owner(self):
        self.config(ignore_project_check_for_admin_tasks=False)

        self.image.visibility = 'private'
        self.image.owner = 'other-owner'
        self.image.id = 'fake-id'

        self.context.project = 'test-project'
        self.context.roles = []
        self.context.auth_token = None

        result = service_utils.is_image_available(self.context, self.image)
        self.assertFalse(result)
