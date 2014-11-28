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
import filecmp
import os
import tempfile

import mock
import testtools


from ironic.common import exception
from ironic.common.glance_service import base_image_service
from ironic.common.glance_service import service_utils
from ironic.common import image_service as service
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests import matchers
from ironic.tests import stubs

from oslo.config import cfg
from oslo.serialization import jsonutils

CONF = cfg.CONF


class NullWriter(object):
    """Used to test ImageService.get which takes a writer object."""

    def write(self, *arg, **kwargs):
        pass


class TestGlanceSerializer(testtools.TestCase):
    def test_serialize(self):
        metadata = {'name': 'image1',
                    'is_public': True,
                    'foo': 'bar',
                    'properties': {
                        'prop1': 'propvalue1',
                        'mappings': [
                            {'virtual': 'aaa',
                             'device': 'bbb'},
                            {'virtual': 'xxx',
                             'device': 'yyy'}],
                        'block_device_mapping': [
                            {'virtual_device': 'fake',
                             'device_name': '/dev/fake'},
                            {'virtual_device': 'ephemeral0',
                             'device_name': '/dev/fake0'}]}}

        converted_expected = {
            'name': 'image1',
            'is_public': True,
            'foo': 'bar',
            'properties': {'prop1': 'propvalue1'}
        }
        converted = service_utils._convert(metadata, 'to')
        self.assertEqual(metadata,
                         service_utils._convert(converted, 'from'))
        # Fields that rely on dict ordering can't be compared as text
        mappings = jsonutils.loads(converted['properties']
                                   .pop('mappings'))
        self.assertEqual([{"device": "bbb", "virtual": "aaa"},
                          {"device": "yyy", "virtual": "xxx"}],
                         mappings)
        bd_mapping = jsonutils.loads(converted['properties']
                                     .pop('block_device_mapping'))
        self.assertEqual([{"virtual_device": "fake",
                           "device_name": "/dev/fake"},
                          {"virtual_device": "ephemeral0",
                           "device_name": "/dev/fake0"}],
                         bd_mapping)
        # Compare the remaining
        self.assertEqual(converted_expected, converted)


class TestGlanceImageService(base.TestCase):
    NOW_GLANCE_OLD_FORMAT = "2010-10-11T10:30:22"
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"

    class tzinfo(datetime.tzinfo):
        @staticmethod
        def utcoffset(*args, **kwargs):
            return datetime.timedelta()

    NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22, tzinfo=tzinfo())

    def setUp(self):
        super(TestGlanceImageService, self).setUp()
        client = stubs.StubGlanceClient()
        self.context = context.RequestContext(auth_token=True)
        self.context.user_id = 'fake'
        self.context.project_id = 'fake'
        self.service = service.Service(client, 1, self.context)

        self.config(glance_host='localhost', group='glance')
        try:
            self.config(auth_strategy='keystone', group='glance')
        except Exception:
            opts = [
                cfg.StrOpt('auth_strategy', default='keystone'),
            ]
            CONF.register_opts(opts)

        return

    @staticmethod
    def _make_fixture(**kwargs):
        fixture = {'name': None,
                   'properties': {},
                   'status': None,
                   'is_public': None}
        fixture.update(kwargs)
        return fixture

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

    def test_create_with_instance_id(self):
        # Ensure instance_id is persisted as an image-property.
        fixture = {'name': 'test image',
                   'is_public': False,
                   'properties': {'instance_id': '42', 'user_id': 'fake'}}
        image_id = self.service.create(fixture)['id']
        image_meta = self.service.show(image_id)
        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {'instance_id': '42', 'user_id': 'fake'},
            'owner': None,
        }
        self.assertThat(image_meta, matchers.DictMatches(expected))

        image_metas = self.service.detail()
        self.assertThat(image_metas[0], matchers.DictMatches(expected))

    def test_create_without_instance_id(self):
        """Test creating an image without an instance ID.

        Ensure we can create an image without having to specify an
        instance_id. Public images are an example of an image not tied to an
        instance.
        """
        fixture = {'name': 'test image', 'is_public': False}
        image_id = self.service.create(fixture)['id']

        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        actual = self.service.show(image_id)
        self.assertThat(actual, matchers.DictMatches(expected))

    def test_create(self):
        fixture = self._make_fixture(name='test image')
        num_images = len(self.service.detail())
        image_id = self.service.create(fixture)['id']

        self.assertIsNotNone(image_id)
        self.assertEqual(num_images + 1,
                          len(self.service.detail()))

    def test_create_and_show_non_existing_image(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(fixture)['id']

        self.assertIsNotNone(image_id)
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          'bad image id')

    def test_detail_private_image(self):
        fixture = self._make_fixture(name='test image')
        fixture['is_public'] = False
        properties = {'owner_id': 'proj1'}
        fixture['properties'] = properties

        self.service.create(fixture)['id']

        proj = self.context.project_id
        self.context.project_id = 'proj1'

        image_metas = self.service.detail()

        self.context.project_id = proj

        self.assertEqual(1, len(image_metas))
        self.assertEqual('test image', image_metas[0]['name'])
        self.assertEqual(False, image_metas[0]['is_public'])

    def test_detail_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(fixture)['id'])

        image_metas = self.service.detail(marker=ids[1])
        self.assertEqual(8, len(image_metas))
        i = 2
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'is_public': None,
                'name': 'TestImage %d' % (i),
                'properties': {},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'owner': None,
            }

            self.assertThat(meta, matchers.DictMatches(expected))
            i = i + 1

    def test_detail_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(fixture)['id'])

        image_metas = self.service.detail(limit=5)
        self.assertEqual(5, len(image_metas))

    def test_detail_default_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(fixture)['id'])

        image_metas = self.service.detail()
        for i, meta in enumerate(image_metas):
            self.assertEqual(meta['name'], 'TestImage %d' % (i))

    def test_detail_marker_and_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(fixture)['id'])

        image_metas = self.service.detail(marker=ids[3], limit=5)
        self.assertEqual(5, len(image_metas))
        i = 4
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'is_public': None,
                'name': 'TestImage %d' % (i),
                'properties': {},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'owner': None,
            }
            self.assertThat(meta, matchers.DictMatches(expected))
            i = i + 1

    def test_detail_invalid_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(fixture)['id'])

        self.assertRaises(exception.Invalid, self.service.detail,
                          marker='invalidmarker')

    def test_update(self):
        fixture = self._make_fixture(name='test image')
        image = self.service.create(fixture)
        image_id = image['id']
        fixture['name'] = 'new image name'
        self.service.update(image_id, fixture)

        new_image_data = self.service.show(image_id)
        self.assertEqual('new image name', new_image_data['name'])

    def test_delete(self):
        fixture1 = self._make_fixture(name='test image 1')
        fixture2 = self._make_fixture(name='test image 2')
        fixtures = [fixture1, fixture2]

        num_images = len(self.service.detail())
        self.assertEqual(0, num_images)

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(fixture)['id']
            ids.append(new_id)

        num_images = len(self.service.detail())
        self.assertEqual(2, num_images)

        self.service.delete(ids[0])
        # When you delete an image from glance, it sets the status to DELETED
        # and doesn't actually remove the image.

        # Check the image is still there.
        num_images = len(self.service.detail())
        self.assertEqual(2, num_images)

        # Check the image is marked as deleted.
        num_images = reduce(lambda x, y: x + (0 if y['deleted'] else 1),
                            self.service.detail(), 0)
        self.assertEqual(1, num_images)

    def test_show_passes_through_to_client(self):
        fixture = self._make_fixture(name='image1', is_public=True)
        image_id = self.service.create(fixture)['id']

        image_meta = self.service.show(image_id)
        expected = {
            'id': image_id,
            'name': 'image1',
            'is_public': True,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        self.assertEqual(expected, image_meta)

    def test_show_raises_when_no_authtoken_in_the_context(self):
        fixture = self._make_fixture(name='image1',
                                     is_public=False,
                                     properties={'one': 'two'})
        image_id = self.service.create(fixture)['id']
        self.context.auth_token = False
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          image_id)

    def test_detail_passes_through_to_client(self):
        fixture = self._make_fixture(name='image10', is_public=True)
        image_id = self.service.create(fixture)['id']
        image_metas = self.service.detail()
        expected = [
            {
                'id': image_id,
                'name': 'image10',
                'is_public': True,
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'status': None,
                'properties': {},
                'owner': None,
            },
        ]
        self.assertEqual(expected, image_metas)

    def test_show_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(fixture)['id']
        image_meta = self.service.show(image_id)
        self.assertEqual(self.NOW_DATETIME, image_meta['created_at'])
        self.assertEqual(self.NOW_DATETIME, image_meta['updated_at'])

    def test_detail_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        self.service.create(fixture)
        image_meta = self.service.detail()[0]
        self.assertEqual(self.NOW_DATETIME, image_meta['created_at'])
        self.assertEqual(self.NOW_DATETIME, image_meta['updated_at'])

    def test_download_with_retries(self):
        tries = [0]

        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that fails the first time, then succeeds."""
            def get(self, image_id):
                if tries[0] == 0:
                    tries[0] = 1
                    raise exception.ServiceUnavailable('')
                else:
                    return {}

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = service.Service(stub_client, 1, stub_context)
        image_id = 1  # doesn't matter
        writer = NullWriter()

        # When retries are disabled, we should get an exception
        self.config(glance_num_retries=0, group='glance')
        self.assertRaises(exception.GlanceConnectionFailed,
                          stub_service.download, image_id, writer)

        # Now lets enable retries. No exception should happen now.
        tries = [0]
        self.config(glance_num_retries=1, group='glance')
        stub_service.download(image_id, writer)

    def test_download_file_url(self):
        # NOTE: only in v2 API
        class MyGlanceStubClient(stubs.StubGlanceClient):

            """A client that returns a file url."""

            (outfd, s_tmpfname) = tempfile.mkstemp(prefix='directURLsrc')
            outf = os.fdopen(outfd, 'w')
            inf = open('/dev/urandom', 'r')
            for i in range(10):
                _data = inf.read(1024)
                outf.write(_data)
            outf.close()

            def get(self, image_id):
                return type('GlanceTestDirectUrlMeta', (object,),
                            {'direct_url': 'file://%s' + self.s_tmpfname})

        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_client = MyGlanceStubClient()
        (outfd, tmpfname) = tempfile.mkstemp(prefix='directURLdst')
        writer = os.fdopen(outfd, 'w')

        stub_service = service.Service(stub_client,
                                       context=stub_context,
                                       version=2)
        image_id = 1  # doesn't matter

        self.config(allowed_direct_url_schemes=['file'], group='glance')
        stub_service.download(image_id, writer)
        writer.close()

        # compare the two files
        rc = filecmp.cmp(tmpfname, stub_client.s_tmpfname)
        self.assertTrue(rc, "The file %s and %s should be the same" %
                        (tmpfname, stub_client.s_tmpfname))
        os.remove(stub_client.s_tmpfname)
        os.remove(tmpfname)

    def test_client_forbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a Forbidden exception."""
            def get(self, image_id):
                raise exception.Forbidden(image_id)

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = service.Service(stub_client, 1, stub_context)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotAuthorized, stub_service.download,
                          image_id, writer)

    def test_client_httpforbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a HTTPForbidden exception."""
            def get(self, image_id):
                raise exception.HTTPForbidden(image_id)

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = service.Service(stub_client, 1, stub_context)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotAuthorized, stub_service.download,
                          image_id, writer)

    def test_client_notfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a NotFound exception."""
            def get(self, image_id):
                raise exception.NotFound(image_id)

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = service.Service(stub_client, 1, stub_context)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotFound, stub_service.download,
                          image_id, writer)

    def test_client_httpnotfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(stubs.StubGlanceClient):
            """A client that raises a HTTPNotFound exception."""
            def get(self, image_id):
                raise exception.HTTPNotFound(image_id)

        stub_client = MyGlanceStubClient()
        stub_context = context.RequestContext(auth_token=True)
        stub_context.user_id = 'fake'
        stub_context.project_id = 'fake'
        stub_service = service.Service(stub_client, 1, stub_context)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotFound, stub_service.download,
                          image_id, writer)

    def test_check_image_service_client_set(self):
        def func(self):
            return True

        self.service.client = True

        wrapped_func = base_image_service.check_image_service(func)
        self.assertTrue(wrapped_func(self.service))

    def test_check_image_service__no_client_set_http(self):
        def func(service, *args, **kwargs):
            return (self.endpoint, args, kwargs)

        self.service.client = None
        params = {'image_href': 'http://123.123.123.123:9292/image_uuid'}
        self.config(auth_strategy='keystone', group='glance')
        wrapped_func = base_image_service.check_image_service(func)
        self.assertEqual(('http://123.123.123.123:9292', (), params),
                         wrapped_func(self.service, **params))

    def test_get_image_service__no_client_set_https(self):
        def func(service, *args, **kwargs):
            return (self.endpoint, args, kwargs)

        self.service.client = None
        params = {'image_href': 'https://123.123.123.123:9292/image_uuid'}
        self.config(auth_strategy='keystone', group='glance')
        wrapped_func = base_image_service.check_image_service(func)

        self.assertEqual(('https://123.123.123.123:9292', (), params),
                         wrapped_func(self.service, **params))


def _create_failing_glance_client(info):
    class MyGlanceStubClient(stubs.StubGlanceClient):
        """A client that fails the first time, then succeeds."""
        def get(self, image_id):
            info['num_calls'] += 1
            if info['num_calls'] == 1:
                raise exception.ServiceUnavailable('')
            return {}

    return MyGlanceStubClient()


class TestGlanceSwiftTempURL(base.TestCase):
    def setUp(self):
        super(TestGlanceSwiftTempURL, self).setUp()
        client = stubs.StubGlanceClient()
        self.context = context.RequestContext()
        self.service = service.Service(client, 2, self.context)
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
        self.config()
        self.fake_image = {
            'id': '757274c4-2856-4bd2-bb20-9a4a231e187b'
        }

    @mock.patch('swiftclient.utils.generate_temp_url')
    def test_swift_temp_url(self, tempurl_mock):

        path = ('/v1/AUTH_a422b2-91f3-2f46-74b7-d7c9e8958f5d30'
                '/glance'
                '/757274c4-2856-4bd2-bb20-9a4a231e187b')
        tempurl_mock.return_value = (path +
            '?temp_url_sig=hmacsig'
            '&temp_url_expires=1400001200')

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

    def test__validate_temp_url_key_exception(self):
        self.config(swift_temp_url_key=None, group='glance')
        self.assertRaises(exception.MissingParameterValue,
                          self.service._validate_temp_url_config)

    def test__validate_temp_url_endpoint_config_exception(self):
        self.config(swift_endpoint_url=None, group='glance')
        self.assertRaises(exception.MissingParameterValue,
                          self.service._validate_temp_url_config)

    def test__validate_temp_url_account_exception(self):
        self.config(swift_account=None, group='glance')
        self.assertRaises(exception.MissingParameterValue,
                          self.service._validate_temp_url_config)

    def test__validate_temp_url_endpoint_negative_duration(self):
        self.config(swift_temp_url_duration=-1,
                    group='glance')
        self.assertRaises(exception.InvalidParameterValue,
                          self.service._validate_temp_url_config)


class TestGlanceUrl(base.TestCase):

    def test_generate_glance_http_url(self):
        self.config(glance_host="127.0.0.1", group='glance')
        generated_url = service_utils.generate_glance_url()
        http_url = "http://%s:%d" % (CONF.glance.glance_host,
                                     CONF.glance.glance_port)
        self.assertEqual(http_url, generated_url)

    def test_generate_glance_https_url(self):
        self.config(glance_protocol="https", group='glance')
        self.config(glance_host="127.0.0.1", group='glance')
        generated_url = service_utils.generate_glance_url()
        https_url = "https://%s:%d" % (CONF.glance.glance_host,
                                       CONF.glance.glance_port)
        self.assertEqual(https_url, generated_url)


class TestServiceUtils(base.TestCase):

    def test_parse_image_ref_no_ssl(self):
        image_href = 'http://127.0.0.1:9292/image_path/image_uuid'
        parsed_href = service_utils.parse_image_ref(image_href)
        self.assertEqual(('image_uuid', '127.0.0.1', 9292, False), parsed_href)

    def test_parse_image_ref_ssl(self):
        image_href = 'https://127.0.0.1:9292/image_path/image_uuid'
        parsed_href = service_utils.parse_image_ref(image_href)
        self.assertEqual(('image_uuid', '127.0.0.1', 9292, True), parsed_href)

    def test_generate_image_url(self):
        image_href = 'image_uuid'
        self.config(glance_host='123.123.123.123', group='glance')
        self.config(glance_port=1234, group='glance')
        self.config(glance_protocol='https', group='glance')
        generated_url = service_utils.generate_image_url(image_href)
        self.assertEqual('https://123.123.123.123:1234/images/image_uuid',
                         generated_url)


class TestGlanceAPIServers(base.TestCase):

    def setUp(self):
        super(TestGlanceAPIServers, self).setUp()
        service_utils._GLANCE_API_SERVER = None

    def test__get_api_servers_default(self):
        host, port, use_ssl = service_utils._get_api_server()
        self.assertEqual(CONF.glance.glance_host, host)
        self.assertEqual(CONF.glance.glance_port, port)
        self.assertEqual(CONF.glance.glance_protocol == 'https', use_ssl)

    def test__get_api_servers_one(self):
        CONF.set_override('glance_api_servers', ['https://10.0.0.1:9293'],
                          'glance')
        s1 = service_utils._get_api_server()
        s2 = service_utils._get_api_server()
        self.assertEqual(('10.0.0.1', 9293, True), s1)

        # Only one server, should always get the same one
        self.assertEqual(s1, s2)

    def test__get_api_servers_two(self):
        CONF.set_override('glance_api_servers',
                          ['http://10.0.0.1:9293', 'http://10.0.0.2:9294'],
                          'glance')
        s1 = service_utils._get_api_server()
        s2 = service_utils._get_api_server()
        s3 = service_utils._get_api_server()

        self.assertNotEqual(s1, s2)

        # 2 servers, so cycles to the first again
        self.assertEqual(s1, s3)
