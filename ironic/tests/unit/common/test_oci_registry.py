#    Copyright (C) 2025 Red Hat, Inc
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

import hashlib
import io
import json
from unittest import mock
from urllib import parse

from oslo_config import cfg
import requests

from ironic.common import exception
from ironic.common import oci_registry
from ironic.tests import base

CONF = cfg.CONF


class OciClientTestCase(base.TestCase):

    def setUp(self):
        super().setUp()
        self.client = oci_registry.OciClient(verify=False)

    @mock.patch.object(oci_registry, 'MakeSession',
                       autospec=True)
    def test_client_init_make_session(self, mock_session):
        oci_registry.OciClient(verify=True)
        mock_session.assert_called_once_with(verify=True)
        mock_session.return_value.create.assert_called_once()

    def test__image_to_url(self):
        url = self.client._image_to_url('oci://host/path')
        self.assertEqual('host', url.netloc)
        self.assertEqual('/path', url.path)
        self.assertEqual('oci', url.scheme)

    def test__image_to_url_adds_oci(self):
        url = self.client._image_to_url('host/path')
        self.assertEqual('oci', url.scheme)
        self.assertEqual('host', url.netloc)
        self.assertEqual('/path', url.path)

    def test_image_tag_from_url(self):
        url = self.client._image_to_url('oci://host/path')
        img, tag = self.client._image_tag_from_url(url)
        self.assertEqual('/path', img)
        self.assertEqual('latest', tag)

    def test_image_tag_from_url_with_tag(self):
        url = self.client._image_to_url('oci://host/path:5.3')
        img, tag = self.client._image_tag_from_url(url)
        self.assertEqual('/path', img)
        self.assertEqual('5.3', tag)

    def test_image_tag_from_url_with_digest(self):
        url = self.client._image_to_url('oci://host/path@sha256:f00')
        img, tag = self.client._image_tag_from_url(url)
        self.assertEqual('/path', img)
        self.assertEqual('sha256:f00', tag)

    def test_get_blob_url(self):
        digest = ('sha256:' + 'a' * 64)
        image = 'oci://host/project/container'
        res = self.client.get_blob_url(image, digest)
        self.assertEqual(
            'https://host/v2/project/container/blobs/' + digest,
            res)


@mock.patch.object(requests.sessions.Session, 'get', autospec=True)
class OciClientRequestTestCase(base.TestCase):

    def setUp(self):
        super().setUp()
        self.client = oci_registry.OciClient(verify=True)

    def test_get_manifest_checksum_verifies(self, get_mock):
        fake_csum = 'f' * 64
        get_mock.return_value.status_code = 200
        get_mock.return_value.text = '{}'
        self.assertRaises(
            exception.ImageChecksumError,
            self.client.get_manifest,
            'oci://localhost/local@sha256:' + fake_csum)
        get_mock.return_value.assert_has_calls([
            mock.call.raise_for_status(),
            mock.call.encoding.__bool__()])
        get_mock.assert_called_once_with(
            mock.ANY,
            ('https://localhost/v2/local/manifests/sha256:ffffffffff'
             'ffffffffffffffffffffffffffffffffffffffffffffffffffffff'),
            headers={'Accept': 'application/vnd.oci.image.manifest.v1+json'},
            timeout=60)

    def test_get_manifest(self, get_mock):
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_mock.return_value.status_code = 200
        get_mock.return_value.text = '{}'
        res = self.client.get_manifest(
            'oci://localhost/local@sha256:' + csum)
        self.assertEqual({}, res)
        get_mock.return_value.assert_has_calls([
            mock.call.raise_for_status(),
            mock.call.encoding.__bool__()])
        get_mock.assert_called_once_with(
            mock.ANY,
            'https://localhost/v2/local/manifests/sha256:' + csum,
            headers={'Accept': 'application/vnd.oci.image.manifest.v1+json'},
            timeout=60)

    def test_get_manifest_auth_required(self, get_mock):
        fake_csum = 'f' * 64
        response = mock.Mock()
        response.status_code = 401
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageServiceAuthenticationRequired,
            self.client.get_manifest,
            'oci://localhost/local@sha256:' + fake_csum)
        call_mock = mock.call(
            mock.ANY,
            ('https://localhost/v2/local/manifests/sha256:ffffffffff'
             'ffffffffffffffffffffffffffffffffffffffffffffffffffffff'),
            headers={'Accept': 'application/vnd.oci.image.manifest.v1+json'},
            timeout=60)
        # Gets retried.
        get_mock.assert_has_calls([call_mock, call_mock])

    def test_get_manifest_image_access_denied(self, get_mock):
        fake_csum = 'f' * 64
        response = mock.Mock()
        response.status_code = 403
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageNotFound,
            self.client.get_manifest,
            'oci://localhost/local@sha256:' + fake_csum)
        call_mock = mock.call(
            mock.ANY,
            ('https://localhost/v2/local/manifests/sha256:ffffffffff'
             'ffffffffffffffffffffffffffffffffffffffffffffffffffffff'),
            headers={'Accept': 'application/vnd.oci.image.manifest.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test_get_manifest_image_not_found(self, get_mock):
        fake_csum = 'f' * 64
        response = mock.Mock()
        response.status_code = 404
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageNotFound,
            self.client.get_manifest,
            'oci://localhost/local@sha256:' + fake_csum)
        call_mock = mock.call(
            mock.ANY,
            ('https://localhost/v2/local/manifests/sha256:ffffffffff'
             'ffffffffffffffffffffffffffffffffffffffffffffffffffffff'),
            headers={'Accept': 'application/vnd.oci.image.manifest.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test_get_manifest_image_temporary_failure(self, get_mock):
        fake_csum = 'f' * 64
        response = mock.Mock()
        response.status_code = 500
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.TemporaryFailure,
            self.client.get_manifest,
            'oci://localhost/local@sha256:' + fake_csum)
        call_mock = mock.call(
            mock.ANY,
            ('https://localhost/v2/local/manifests/sha256:ffffffffff'
             'ffffffffffffffffffffffffffffffffffffffffffffffffffffff'),
            headers={'Accept': 'application/vnd.oci.image.manifest.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    @mock.patch.object(oci_registry.OciClient, '_resolve_tag',
                       autospec=True)
    def test_get_artifact_index_with_tag(self, resolve_tag_mock, get_mock):
        resolve_tag_mock.return_value = {
            'image': '/local',
            'tag': 'tag'
        }
        get_mock.return_value.status_code = 200
        get_mock.return_value.text = '{}'
        res = self.client.get_artifact_index(
            'oci://localhost/local:tag')
        self.assertEqual({}, res)
        resolve_tag_mock.assert_called_once_with(
            mock.ANY,
            parse.urlparse('oci://localhost/local:tag'))
        get_mock.return_value.assert_has_calls([
            mock.call.raise_for_status(),
            mock.call.encoding.__bool__()])
        get_mock.assert_called_once_with(
            mock.ANY,
            'https://localhost/v2/local/manifests/tag',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)

    @mock.patch.object(oci_registry.OciClient, '_resolve_tag',
                       autospec=True)
    def test_get_artifact_index_not_found(self, resolve_tag_mock, get_mock):
        resolve_tag_mock.return_value = {
            'image': '/local',
            'tag': 'tag'
        }
        response = mock.Mock()
        response.status_code = 404
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageNotFound,
            self.client.get_artifact_index,
            'oci://localhost/local:tag')
        resolve_tag_mock.assert_called_once_with(
            mock.ANY,
            parse.urlparse('oci://localhost/local:tag'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/manifests/tag',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    @mock.patch.object(oci_registry.OciClient, '_resolve_tag',
                       autospec=True)
    def test_get_artifact_index_not_authorized(self, resolve_tag_mock,
                                               get_mock):
        resolve_tag_mock.return_value = {
            'image': '/local',
            'tag': 'tag'
        }
        response = mock.Mock()
        response.status_code = 401
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageServiceAuthenticationRequired,
            self.client.get_artifact_index,
            'oci://localhost/local:tag')
        resolve_tag_mock.assert_called_once_with(
            mock.ANY,
            parse.urlparse('oci://localhost/local:tag'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/manifests/tag',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        # Automatic retry to authenticate
        get_mock.assert_has_calls([call_mock, call_mock])

    @mock.patch.object(oci_registry.OciClient, '_resolve_tag',
                       autospec=True)
    def test_get_artifact_index_temporaryfailure(self, resolve_tag_mock,
                                                 get_mock):
        resolve_tag_mock.return_value = {
            'image': '/local',
            'tag': 'tag'
        }
        response = mock.Mock()
        response.status_code = 500
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.TemporaryFailure,
            self.client.get_artifact_index,
            'oci://localhost/local:tag')
        resolve_tag_mock.assert_called_once_with(
            mock.ANY,
            parse.urlparse('oci://localhost/local:tag'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/manifests/tag',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    @mock.patch.object(oci_registry.OciClient, '_resolve_tag',
                       autospec=True)
    def test_get_artifact_index_access_denied(self, resolve_tag_mock,
                                              get_mock):
        resolve_tag_mock.return_value = {
            'image': '/local',
            'tag': 'tag'
        }
        response = mock.Mock()
        response.status_code = 403
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageNotFound,
            self.client.get_artifact_index,
            'oci://localhost/local:tag')
        resolve_tag_mock.assert_called_once_with(
            mock.ANY,
            parse.urlparse('oci://localhost/local:tag'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/manifests/tag',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test__resolve_tag(self, get_mock):
        response = mock.Mock()
        response.json.return_value = {'tags': ['latest', 'foo', 'bar']}
        response.status_code = 200
        response.links = {}
        get_mock.return_value = response
        res = self.client._resolve_tag(
            parse.urlparse('oci://localhost/local'))
        self.assertDictEqual({'image': '/local', 'tag': 'latest'}, res)
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/tags/list',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test__resolve_tag_if_not_found(self, get_mock):
        response = mock.Mock()
        response.json.return_value = {'tags': ['foo', 'bar']}
        response.status_code = 200
        response.links = {}
        get_mock.return_value = response
        self.assertRaises(
            exception.ImageNotFound,
            self.client._resolve_tag,
            parse.urlparse('oci://localhost/local'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/tags/list',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test__resolve_tag_follows_links(self, get_mock):
        response = mock.Mock()
        response.json.return_value = {'tags': ['foo', 'bar']}
        response.status_code = 200
        response.links = {'next': {'url': 'list2'}}
        response2 = mock.Mock()
        response2.json.return_value = {'tags': ['zoo']}
        response2.status_code = 200
        response2.links = {}
        get_mock.side_effect = iter([response, response2])
        res = self.client._resolve_tag(
            parse.urlparse('oci://localhost/local:zoo'))
        self.assertDictEqual({'image': '/local', 'tag': 'zoo'}, res)
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/tags/list',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        call_mock_2 = mock.call(
            mock.ANY,
            'https://localhost/v2/local/tags/list2',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock, call_mock_2])

    def test__resolve_tag_auth_needed(self, get_mock):
        response = mock.Mock()
        response.json.return_value = {}
        response.status_code = 401
        response.text = 'Authorization Required'
        response.links = {}
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.ImageServiceAuthenticationRequired,
            self.client._resolve_tag,
            parse.urlparse('oci://localhost/local'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/tags/list',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test__resolve_tag_temp_failure(self, get_mock):
        response = mock.Mock()
        response.json.return_value = {}
        response.status_code = 500
        response.text = 'Server on vacation'
        response.links = {}
        exc = requests.exceptions.HTTPError(
            response=response)
        get_mock.side_effect = exc
        self.assertRaises(
            exception.TemporaryFailure,
            self.client._resolve_tag,
            parse.urlparse('oci://localhost/local'))
        call_mock = mock.call(
            mock.ANY,
            'https://localhost/v2/local/tags/list',
            headers={'Accept': 'application/vnd.oci.image.index.v1+json'},
            timeout=60)
        get_mock.assert_has_calls([call_mock])

    def test_authenticate_noop(self, get_mock):
        """Test authentication when the remote endpoint doesn't require it."""
        response = mock.Mock()
        response.status_code = 200
        get_mock.return_value = response
        self.client.authenticate(
            'oci://localhost/foo/bar:meow',
            username='foo',
            password='bar')
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60)])

    def test_authenticate_401_no_header(self, get_mock):
        """Test authentication when the remote endpoint doesn't require it."""
        response = mock.Mock()
        response.status_code = 401
        response.headers = {}
        get_mock.return_value = response
        self.assertRaisesRegex(
            AttributeError,
            'Unknown authentication method',
            self.client.authenticate,
            'oci://localhost/foo/bar:meow',
            username='foo',
            password='bar')
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60)])

    def test_authenticate_401_bad_header(self, get_mock):
        """Test authentication when the remote endpoint doesn't require it."""
        response = mock.Mock()
        response.status_code = 401
        response.headers = {'www-authenticate': 'magic'}
        get_mock.return_value = response
        self.assertRaisesRegex(
            AttributeError,
            'Unknown www-authenticate value',
            self.client.authenticate,
            'oci://localhost/foo/bar:meow',
            username='foo',
            password='bar')
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60)])

    def test_authenticate_401_bearer_auth(self, get_mock):
        self.assertIsNone(self.client._cached_auth)
        self.assertIsNone(self.client.session.headers.get('Authorization'))
        response = mock.Mock()
        response.status_code = 401
        response.json.return_value = {'token': 'me0w'}
        response.headers = {'www-authenticate': 'bearer realm="foo"'}
        response2 = mock.Mock()
        response2.status_code = 200
        response2.json.return_value = {'token': 'me0w'}
        get_mock.side_effect = iter([response, response2])
        self.client.authenticate(
            'oci://localhost/foo/bar:meow',
            username='',
            password='bar')
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60),
            mock.call(mock.ANY, 'foo',
                      params={'scope': 'repository:foo/bar:pull'},
                      auth=mock.ANY, timeout=60)])
        self.assertIsNotNone(self.client._cached_auth)
        self.assertEqual('bearer me0w',
                         self.client.session.headers['Authorization'])

    def test_authenticate_401_basic_auth_no_username(self, get_mock):
        self.assertIsNone(self.client._cached_auth)
        self.assertIsNone(self.client.session.headers.get('Authorization'))
        response = mock.Mock()
        response.status_code = 401
        response.headers = {'www-authenticate': 'basic service="foo"'}
        get_mock.return_value = response
        self.assertRaises(
            exception.ImageServiceAuthenticationRequired,
            self.client.authenticate,
            'oci://localhost/foo/bar:meow',
            username='',
            password='bar')
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60)])

    def test_authenticate_401_basic_auth(self, get_mock):
        self.assertIsNone(self.client._cached_auth)
        self.assertIsNone(self.client.session.headers.get('Authorization'))
        response = mock.Mock()
        response.status_code = 401
        response.headers = {'www-authenticate': 'basic service="foo"'}
        response2 = mock.Mock()
        response2.status_code = 200
        get_mock.side_effect = iter([response, response2])
        self.client.authenticate(
            'oci://localhost/foo/bar:meow',
            username='user',
            password='bar')
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60),
            mock.call(mock.ANY, 'https://localhost/v2/',
                      params={},
                      auth=mock.ANY, timeout=60)])
        self.assertIsNotNone(self.client._cached_auth)
        self.assertEqual('basic dXNlcjpiYXI=',
                         self.client.session.headers['Authorization'])

    @mock.patch.object(oci_registry.RegistrySessionHelper,
                       'get_token_from_config',
                       autospec=True)
    def test_authenticate_401_fallback_to_service_config(self, token_mock,
                                                         get_mock):
        self.assertIsNone(self.client._cached_auth)
        self.assertIsNone(self.client.session.headers.get('Authorization'))
        response = mock.Mock()
        response.status_code = 401
        response.headers = {
            'www-authenticate': 'bearer realm="https://foo/bar"'}
        response2 = mock.Mock()
        response2.status_code = 200
        response2.json.return_value = {'token': 'me0w'}
        get_mock.side_effect = iter([response, response2])
        self.client.authenticate(
            'oci://localhost/foo/bar:meow',
            username=None,
            password=None)
        get_mock.assert_has_calls([
            mock.call(mock.ANY, 'https://localhost/v2/', timeout=60),
            mock.call(mock.ANY, 'https://foo/bar',
                      params={'scope': 'repository:foo/bar:pull'},
                      auth=mock.ANY, timeout=60)])
        self.assertIsNotNone(self.client._cached_auth)
        self.assertEqual('bearer me0w',
                         self.client.session.headers['Authorization'])
        token_mock.assert_called_once_with('foo')

    @mock.patch.object(hashlib, 'new', autospec=True)
    def test_download_blob_from_manifest(self, mock_hash, get_mock):
        CONF.set_override('secure_cdn_registries', ['localhost'], group='oci')
        self.client.session.headers = {'Authorization': 'bearer zoo'}
        mock_file = mock.MagicMock(spec=io.BytesIO)
        mock_hash.return_value.hexdigest.side_effect = iter([
            ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f'
             '61caaff8a'),
            ('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e8'
             '86266e7ae')
        ])
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_1 = mock.Mock()
        get_1.status_code = 200
        manifest = {
            'layers': [{
                'digest': ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706'
                           '483bfa0f98a5e886266e7ae')}]
        }
        get_1.text = json.dumps(manifest)
        get_2 = mock.Mock()
        get_2.status_code = 301
        get_2.headers = {'Location': 'https://localhost/foo/sha'}
        get_3 = mock.Mock()
        get_3.status_code = 200
        get_3.iter_content.return_value = ['some', 'content']
        get_mock.side_effect = iter([get_1, get_2, get_3])

        res = self.client.download_blob_from_manifest(
            'oci://localhost/foo/bar@sha256:' + csum,
            mock_file)

        mock_file.write.assert_has_calls([
            mock.call('some'),
            mock.call('content')])
        self.assertEqual(
            ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98'
             'a5e886266e7ae'),
            res)
        get_mock.assert_has_calls([
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/manifests/sha256:44136fa355b'
                 '3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'),
                headers={
                    'Accept': 'application/vnd.oci.image.manifest.v1+json'},
                timeout=60),
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/blobs/sha256:2c26b46b68ffc68f'
                 'f99b453c1d30413413422d706483bfa0f98a5e886266e7ae'),
                stream=True,
                timeout=60),
            mock.call(
                mock.ANY,
                'https://localhost/foo/sha',
                stream=True,
                timeout=60)
        ])

    @mock.patch.object(hashlib, 'new', autospec=True)
    def test_download_blob_from_manifest_code_check(self, mock_hash,
                                                    get_mock):
        mock_file = mock.MagicMock(spec=io.BytesIO)
        mock_hash.return_value.hexdigest.side_effect = iter([
            ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f'
             '61caaff8a'),
            ('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e8'
             '86266e7ae')
        ])
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_1 = mock.Mock()
        get_1.status_code = 200
        manifest = {
            'layers': [{
                'digest': ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706'
                           '483bfa0f98a5e886266e7ae')}]
        }
        get_1.text = json.dumps(manifest)
        get_2 = mock.Mock()
        get_2.status_code = 301
        get_2.headers = {'Location': 'https://localhost/foo/sha'}
        get_3 = mock.Mock()
        get_3.status_code = 204
        get_3.iter_content.return_value = ['some', 'content']
        get_mock.side_effect = iter([get_1, get_2, get_3])

        self.assertRaisesRegex(
            exception.ImageRefValidationFailed,
            'Got HTTP code 204',
            self.client.download_blob_from_manifest,
            'oci://localhost/foo/bar@sha256:' + csum,
            mock_file)

        mock_file.write.assert_not_called()
        get_mock.assert_has_calls([
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/manifests/sha256:44136fa355b'
                 '3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'),
                headers={
                    'Accept': 'application/vnd.oci.image.manifest.v1+json'},
                timeout=60),
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/blobs/sha256:2c26b46b68ffc68f'
                 'f99b453c1d30413413422d706483bfa0f98a5e886266e7ae'),
                stream=True,
                timeout=60),
            mock.call(
                mock.ANY,
                'https://localhost/foo/sha',
                stream=True,
                timeout=60)
        ])

    @mock.patch.object(hashlib, 'new', autospec=True)
    def test_download_blob_from_manifest_code_401(self, mock_hash,
                                                  get_mock):
        self.client.session.headers = {'Authorization': 'bearer zoo'}
        mock_file = mock.MagicMock(spec=io.BytesIO)
        mock_hash.return_value.hexdigest.side_effect = iter([
            ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f'
             '61caaff8a'),
            ('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e8'
             '86266e7ae')
        ])
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_1 = mock.Mock()
        get_1.status_code = 200
        manifest = {
            'layers': [{
                'digest': ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706'
                           '483bfa0f98a5e886266e7ae')}]
        }
        get_1.text = json.dumps(manifest)
        get_2 = mock.Mock()
        get_2.status_code = 401
        get_2_exc = requests.exceptions.HTTPError(
            response=get_2)
        # Authentication is automatically retried, hence
        # needing to return exceptions twice.
        get_mock.side_effect = iter([get_1, get_2_exc, get_2_exc])

        self.assertRaises(
            exception.ImageServiceAuthenticationRequired,
            self.client.download_blob_from_manifest,
            'oci://localhost/foo/bar@sha256:' + csum,
            mock_file)

        mock_file.write.assert_not_called()
        get_mock.assert_has_calls([
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/manifests/sha256:44136fa355b'
                 '3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'),
                headers={
                    'Accept': 'application/vnd.oci.image.manifest.v1+json'},
                timeout=60),
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/blobs/sha256:2c26b46b68ffc68f'
                 'f99b453c1d30413413422d706483bfa0f98a5e886266e7ae'),
                stream=True,
                timeout=60),
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/blobs/sha256:2c26b46b68ffc68f'
                 'f99b453c1d30413413422d706483bfa0f98a5e886266e7ae'),
                stream=True,
                timeout=60),
        ])

    @mock.patch.object(hashlib, 'new', autospec=True)
    def test_download_blob_from_manifest_code_404(self, mock_hash,
                                                  get_mock):
        mock_file = mock.MagicMock(spec=io.BytesIO)
        mock_hash.return_value.hexdigest.side_effect = iter([
            ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f'
             '61caaff8a'),
            ('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e8'
             '86266e7ae')
        ])
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_1 = mock.Mock()
        get_1.status_code = 200
        manifest = {
            'layers': [{
                'digest': ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706'
                           '483bfa0f98a5e886266e7ae')}]
        }
        get_1.text = json.dumps(manifest)
        get_2 = mock.Mock()
        get_2.status_code = 404
        get_2_exc = requests.exceptions.HTTPError(
            response=get_2)
        get_mock.side_effect = iter([get_1, get_2_exc])

        self.assertRaises(
            exception.ImageNotFound,
            self.client.download_blob_from_manifest,
            'oci://localhost/foo/bar@sha256:' + csum,
            mock_file)

        mock_file.write.assert_not_called()
        get_mock.assert_has_calls([
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/manifests/sha256:44136fa355b'
                 '3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'),
                headers={
                    'Accept': 'application/vnd.oci.image.manifest.v1+json'},
                timeout=60),
            mock.call(
                mock.ANY,
                ('https://localhost/v2/foo/bar/blobs/sha256:2c26b46b68ffc68f'
                 'f99b453c1d30413413422d706483bfa0f98a5e886266e7ae'),
                stream=True,
                timeout=60),
        ])

    @mock.patch.object(hashlib, 'new', autospec=True)
    def test_download_blob_from_manifest_code_403(self, mock_hash,
                                                  get_mock):
        mock_file = mock.MagicMock(spec=io.BytesIO)
        mock_hash.return_value.hexdigest.side_effect = iter([
            ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f'
             '61caaff8a'),
            ('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e8'
             '86266e7ae')
        ])
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_1 = mock.Mock()
        get_1.status_code = 200
        manifest = {
            'layers': [{
                'digest': ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706'
                           '483bfa0f98a5e886266e7ae')}]
        }
        get_1.text = json.dumps(manifest)
        get_2 = mock.Mock()
        get_2.status_code = 403
        get_2_exc = requests.exceptions.HTTPError(
            response=get_2)
        get_mock.side_effect = iter([get_1, get_2_exc])

        self.assertRaises(
            exception.ImageNotFound,
            self.client.download_blob_from_manifest,
            'oci://localhost/foo/bar@sha256:' + csum,
            mock_file)
        mock_file.write.assert_not_called()
        self.assertEqual(2, get_mock.call_count)

    @mock.patch.object(hashlib, 'new', autospec=True)
    def test_download_blob_from_manifest_code_500(self, mock_hash,
                                                  get_mock):
        mock_file = mock.MagicMock(spec=io.BytesIO)
        mock_hash.return_value.hexdigest.side_effect = iter([
            ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f'
             '61caaff8a'),
            ('2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e8'
             '86266e7ae')
        ])
        csum = ('44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c0'
                '60f61caaff8a')
        get_1 = mock.Mock()
        get_1.status_code = 200
        manifest = {
            'layers': [{
                'digest': ('sha256:2c26b46b68ffc68ff99b453c1d30413413422d706'
                           '483bfa0f98a5e886266e7ae')}]
        }
        get_1.text = json.dumps(manifest)
        get_2 = mock.Mock()
        get_2.status_code = 500
        get_2_exc = requests.exceptions.HTTPError(
            response=get_2)
        get_mock.side_effect = iter([get_1, get_2_exc])

        self.assertRaises(
            exception.TemporaryFailure,
            self.client.download_blob_from_manifest,
            'oci://localhost/foo/bar@sha256:' + csum,
            mock_file)
        mock_file.write.assert_not_called()
        self.assertEqual(2, get_mock.call_count)


class TestRegistrySessionHelper(base.TestCase):

    def test_get_token_from_config_default(self):
        self.assertIsNone(
            oci_registry.RegistrySessionHelper.get_token_from_config(
                'foo.bar'))

    def test_get_token_from_config(self):
        CONF.set_override('authentication_config', '/tmp/foo',
                          group='oci')
        read_data = """{"auths": {"foo.fqdn": {"auth": "secret"}}}"""
        with mock.patch('builtins.open', mock.mock_open(
                read_data=read_data)):
            res = oci_registry.RegistrySessionHelper.get_token_from_config(
                'foo.fqdn')
        self.assertEqual('secret', res)

    def test_get_token_from_config_no_match(self):
        CONF.set_override('authentication_config', '/tmp/foo',
                          group='oci')
        read_data = """{"auths": {"bar.fqdn": {}}}"""
        with mock.patch('builtins.open', mock.mock_open(
                read_data=read_data)):
            res = oci_registry.RegistrySessionHelper.get_token_from_config(
                'foo.fqdn')
        self.assertIsNone(res)

    def test_get_token_from_config_bad_file(self):
        CONF.set_override('authentication_config', '/tmp/foo',
                          group='oci')
        read_data = """{"auths":..."""
        with mock.patch('builtins.open', mock.mock_open(
                read_data=read_data)):
            res = oci_registry.RegistrySessionHelper.get_token_from_config(
                'foo.fqdn')
        self.assertIsNone(res)
