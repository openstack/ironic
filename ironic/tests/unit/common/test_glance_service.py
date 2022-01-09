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

from glanceclient import client as glance_client
from glanceclient import exc as glance_exc
from keystoneauth1 import loading as ks_loading
from oslo_config import cfg
from oslo_utils import uuidutils
import tenacity
import testtools

from ironic.common import context
from ironic.common import exception
from ironic.common.glance_service import image_service
from ironic.common.glance_service import service_utils
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
                   'status': "active"}
        fixture.update(kwargs)
        return stubs.FakeImage(fixture)

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
            'tags': None,
            'updated_at': None,
            'visibility': None,
            'os_hash_algo': None,
            'os_hash_value': None,
        }
        with mock.patch.object(self.service, 'call', return_value=image,
                               autospec=True):
            image_meta = self.service.show(image_id)
            self.service.call.assert_called_once_with('get', image_id)
        self.assertEqual(expected, image_meta)

    def test_show_makes_datetimes(self):
        image_id = uuidutils.generate_uuid()
        image = self._make_datetime_fixture()
        with mock.patch.object(self.service, 'call', return_value=image,
                               autospec=True):
            image_meta = self.service.show(image_id)
            self.service.call.assert_called_once_with('get', image_id)
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
        with mock.patch.object(self.service, 'call', return_value=image,
                               autospec=True):
            self.assertRaises(exception.ImageUnacceptable,
                              self.service.show, image_id)

    @mock.patch.object(tenacity, 'retry', autospec=True)
    def test_download_with_retries(self, mock_retry):
        tries = [0]

        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that fails the first time, then succeeds."""
            def get(self, image_id):
                if tries[0] == 0:
                    tries[0] = 1
                    raise glance_exc.ServiceUnavailable('')
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
        mock_retry.assert_called_once()

    def test_download_no_data(self):
        self.client.fake_wrapped = None
        image_id = uuidutils.generate_uuid()

        image = self._make_datetime_fixture()
        with mock.patch.object(self.client, 'get', return_value=image,
                               autospec=True):
            self.assertRaisesRegex(exception.ImageDownloadFailed,
                                   'image contains no data',
                                   self.service.download, image_id)

    @mock.patch('os.sendfile', autospec=True)
    @mock.patch('os.path.getsize', autospec=True)
    @mock.patch('%s.open' % __name__, new=mock.mock_open(), create=True)
    def test_download_file_url(self, mock_getsize, mock_sendfile):
        # NOTE: only in v2 API
        class MyGlanceStubClient(stubs.StubGlanceClient):

            """A client that returns a file url."""

            s_tmpfname = '/whatever/source'

            def get(self, image_id):
                return type('GlanceTestDirectUrlMeta', (object,),
                            {'direct_url': 'file://%s' + self.s_tmpfname})

        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_client = MyGlanceStubClient()

        stub_service = image_service.GlanceImageService(stub_client,
                                                        context=stub_context)
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
            def get(self, image_id):
                raise glance_exc.Forbidden(image_id)

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

    def test_client_httpforbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a HTTPForbidden exception."""
            def get(self, image_id):
                raise glance_exc.HTTPForbidden(image_id)

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
            def get(self, image_id):
                raise glance_exc.NotFound(image_id)

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

    def test_client_httpnotfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a HTTPNotFound exception."""
            def get(self, image_id):
                raise glance_exc.HTTPNotFound(image_id)

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
@mock.patch.object(glance_client, 'Client', autospec=True)
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

    def _assert_client_call(self, mock_gclient, url, user=False):
        mock_gclient.assert_called_once_with(
            2,
            session=mock.sentinel.session,
            global_request_id='global',
            auth=mock.sentinel.sauth if user else mock.sentinel.auth,
            endpoint_override=url)

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
        self._assert_client_call(mock_gclient, 'glance_url')
        mock_auth.assert_called_once_with('glance')
        mock_sess.assert_called_once_with('glance')
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
        self._assert_client_call(mock_gclient, 'glance_url', user=True)
        mock_sess.assert_called_once_with('glance')
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
        self._assert_client_call(mock_gclient, 'foo')
        mock_sess.assert_called_once_with('glance')
        mock_adapter.assert_called_once_with('glance',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        self.assertEqual(0, mock_sauth.call_count)


def _create_failing_glance_client(info):
    class MyGlanceStubClient(stubs.StubGlanceClient):
        """A client that fails the first time, then succeeds."""
        def get(self, image_id):
            info['num_calls'] += 1
            if info['num_calls'] == 1:
                raise glance_exc.ServiceUnavailable('')
            return {}

    return MyGlanceStubClient()


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

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url(self, tempurl_mock):

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')

    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_endpoint_detected(self, tempurl_mock,
                                              adapter_mock):
        self.config(swift_endpoint_url=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
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
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')

    @mock.patch('ironic.common.keystone.get_adapter', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_endpoint_with_suffix(self, tempurl_mock,
                                                 adapter_mock):
        self.config(swift_endpoint_url=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
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
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_account_detected(self, tempurl_mock, swift_mock):
        self.config(swift_account=None, group='glance')

        path = ('/v1/AUTH_42/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        auth_ref = swift_mock.return_value.auth.get_auth_ref.return_value
        auth_ref.project_id = '42'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')
        swift_mock.assert_called_once_with()

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_account_detected_with_prefix(self, tempurl_mock,
                                                         swift_mock):
        self.config(swift_account=None, group='glance')
        self.config(swift_account_prefix='SWIFTPREFIX', group='glance')

        path = ('/v1/SWIFTPREFIX_42/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        auth_ref = swift_mock.return_value.auth.get_auth_ref.return_value
        auth_ref.project_id = '42'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')
        swift_mock.assert_called_once_with()

    @mock.patch('ironic.common.swift.get_swift_session', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_account_detected_with_prefix_underscore(
            self, tempurl_mock, swift_mock):
        self.config(swift_account=None, group='glance')
        self.config(swift_account_prefix='SWIFTPREFIX_', group='glance')

        path = ('/v1/SWIFTPREFIX_42/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        auth_ref = swift_mock.return_value.auth.get_auth_ref.return_value
        auth_ref.project_id = '42'

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')
        swift_mock.assert_called_once_with()

    @mock.patch('ironic.common.swift.SwiftAPI', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_key_detected(self, tempurl_mock, swift_mock):
        self.config(swift_temp_url_key=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        conn = swift_mock.return_value.connection
        conn.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secret'
        }

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            seconds=CONF.glance.swift_temp_url_duration,
            key='secret',
            method='GET')
        conn.head_account.assert_called_once_with()

    @mock.patch('ironic.common.swift.SwiftAPI', autospec=True)
    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_no_key_detected(self, tempurl_mock, swift_mock):
        self.config(swift_temp_url_key=None, group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')
        conn = swift_mock.return_value.connection
        conn.head_account.return_value = {}

        self.service._validate_temp_url_config = mock.Mock()

        self.assertRaises(exception.InvalidParameterValue,
                          self.service.swift_temp_url,
                          image_info=self.fake_image)
        conn.head_account.assert_called_once_with()

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_invalid_image_info(self, tempurl_mock):
        self.service._validate_temp_url_config = mock.Mock()
        image_info = {}
        self.assertRaises(exception.ImageUnacceptable,
                          self.service.swift_temp_url, image_info)
        image_info = {'id': 'not an id'}
        self.assertRaises(exception.ImageUnacceptable,
                          self.service.swift_temp_url, image_info)
        self.assertFalse(tempurl_mock.called)

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_swift_temp_url_multiple_containers(self, tempurl_mock):

        self.config(swift_store_multiple_containers_seed=8,
                    group='glance')

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance_757274c4'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (
            path + '?temp_url_sig=hmacsig&temp_url_expires=1400001200')

        self.service._validate_temp_url_config = mock.Mock()

        temp_url = self.service.swift_temp_url(image_info=self.fake_image)

        self.assertEqual(CONF.glance.swift_endpoint_url
                         + tempurl_mock.return_value,
                         temp_url)
        tempurl_mock.assert_called_with(
            path=path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
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

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_add_items_to_cache(self, tempurl_mock):
        fake_image = {
            'id': uuidutils.generate_uuid()
        }

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/%s' % fake_image['id'])
        exp_time = int(time.time()) + 1200
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
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET')
        self.assertEqual((temp_url, exp_time),
                         self.glance_service._cache[fake_image['id']])

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_return_cached_tempurl(self, tempurl_mock):
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

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def test_do_not_return_expired_tempurls(self, tempurl_mock):
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
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
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

    @mock.patch('swiftclient.utils.generate_temp_url', autospec=True)
    def _test__generate_temp_url(self, fake_image, tempurl_mock):
        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/%s' % fake_image['id'])
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
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
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
