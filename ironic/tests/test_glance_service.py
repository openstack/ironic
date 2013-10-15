# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
            'properties': {
                'prop1': 'propvalue1',
                'mappings':
                '[{"device": "bbb", "virtual": "aaa"}, '
                '{"device": "yyy", "virtual": "xxx"}]',
                'block_device_mapping':
                '[{"virtual_device": "fake", "device_name": "/dev/fake"}, '
                '{"virtual_device": "ephemeral0", '
                '"device_name": "/dev/fake0"}]'}}
        converted = service_utils._convert(metadata, 'to')
        self.assertEqual(converted, converted_expected)
        self.assertEqual(service_utils._convert(converted, 'from'),
                         metadata)


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

        CONF.set_default('glance_host', 'localhost', group='glance')
        try:
            CONF.set_default('auth_strategy', 'keystone', group='glance')
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
        """Ensure we can create an image without having to specify an
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

        self.assertNotEquals(None, image_id)
        self.assertEquals(num_images + 1,
                          len(self.service.detail()))

    def test_create_and_show_non_existing_image(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(fixture)['id']

        self.assertNotEquals(None, image_id)
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
        self.assertEqual(image_metas[0]['name'], 'test image')
        self.assertEqual(image_metas[0]['is_public'], False)

    def test_detail_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(fixture)['id'])

        image_metas = self.service.detail(marker=ids[1])
        self.assertEquals(len(image_metas), 8)
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
        self.assertEquals(len(image_metas), 5)

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
        self.assertEquals(len(image_metas), 5)
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
        self.assertEquals('new image name', new_image_data['name'])

    def test_delete(self):
        fixture1 = self._make_fixture(name='test image 1')
        fixture2 = self._make_fixture(name='test image 2')
        fixtures = [fixture1, fixture2]

        num_images = len(self.service.detail())
        self.assertEquals(0, num_images)

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(fixture)['id']
            ids.append(new_id)

        num_images = len(self.service.detail())
        self.assertEquals(2, num_images)

        self.service.delete(ids[0])
        # When you delete an image from glance, it sets the status to DELETED
        # and doesn't actually remove the image.

        # Check the image is still there.
        num_images = len(self.service.detail())
        self.assertEquals(2, num_images)

        # Check the image is marked as deleted.
        num_images = reduce(lambda x, y: x + (0 if y['deleted'] else 1),
                            self.service.detail(), 0)
        self.assertEquals(1, num_images)

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
        self.assertEqual(image_meta, expected)

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
        self.assertEqual(image_metas, expected)

    def test_show_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(fixture)['id']
        image_meta = self.service.show(image_id)
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_detail_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        self.service.create(fixture)
        image_meta = self.service.detail()[0]
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

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
        #NOTE: only in v2 API
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
            return (service.client.endpoint, args, kwargs)

        self.service.client = None
        params = {'image_href': 'http://123.123.123.123:9292/image_uuid'}
        self.config(auth_strategy='keystone', group='glance')
        wrapped_func = base_image_service.check_image_service(func)
        self.assertEqual(('http://123.123.123.123:9292', (), params),
                         wrapped_func(self.service, **params))

    def test_get_image_service__no_client_set_https(self):
        def func(service, *args, **kwargs):
            return (service.client.endpoint, args, kwargs)

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


class TestGlanceUrl(base.TestCase):

    def test_generate_glance_http_url(self):
        self.config(glance_host="127.0.0.1", group='glance')
        generated_url = service_utils.generate_glance_url()
        http_url = "http://%s:%d" % (CONF.glance.glance_host,
                                     CONF.glance.glance_port)
        self.assertEqual(generated_url, http_url)

    def test_generate_glance_https_url(self):
        self.config(glance_protocol="https", group='glance')
        self.config(glance_host="127.0.0.1", group='glance')
        generated_url = service_utils.generate_glance_url()
        https_url = "https://%s:%d" % (CONF.glance.glance_host,
                                       CONF.glance.glance_port)
        self.assertEqual(generated_url, https_url)


class TestServiceUtils(base.TestCase):

    def test_parse_image_ref_no_ssl(self):
        image_href = 'http://127.0.0.1:9292/image_path/image_uuid'
        parsed_href = service_utils.parse_image_ref(image_href)
        self.assertEqual(parsed_href, ('image_uuid', '127.0.0.1', 9292, False))

    def test_parse_image_ref_ssl(self):
        image_href = 'https://127.0.0.1:9292/image_path/image_uuid'
        parsed_href = service_utils.parse_image_ref(image_href)
        self.assertEqual(parsed_href, ('image_uuid', '127.0.0.1', 9292, True))

    def test_generate_image_url(self):
        image_href = 'image_uuid'
        CONF.set_default('glance_host', '123.123.123.123', group='glance')
        CONF.set_default('glance_port', 1234, group='glance')
        CONF.set_default('glance_protocol', 'https', group='glance')
        generated_url = service_utils.generate_image_url(image_href)
        self.assertEqual(generated_url,
                         'https://123.123.123.123:1234/images/image_uuid')
