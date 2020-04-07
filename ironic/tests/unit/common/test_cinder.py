# Copyright 2016 Hewlett Packard Enterprise Development Company LP.
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
import json
from unittest import mock

from cinderclient import exceptions as cinder_exceptions
import cinderclient.v3 as cinderclient
from oslo_utils import uuidutils

from ironic.common import cinder
from ironic.common import context
from ironic.common import exception
from ironic.common import keystone
from ironic.conductor import task_manager
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


@mock.patch.object(keystone, 'get_auth', autospec=True)
@mock.patch.object(keystone, 'get_session', autospec=True)
class TestCinderSession(base.TestCase):

    def setUp(self):
        super(TestCinderSession, self).setUp()
        self.config(timeout=1,
                    retries=2,
                    group='cinder')
        cinder._CINDER_SESSION = None

    def test__get_cinder_session(self, mock_keystone_session, mock_auth):
        """Check establishing new session when no session exists."""
        mock_keystone_session.return_value = 'session1'
        self.assertEqual('session1', cinder._get_cinder_session())
        mock_keystone_session.assert_called_once_with('cinder')

        """Check if existing session is used."""
        mock_keystone_session.reset_mock()
        mock_keystone_session.return_value = 'session2'
        self.assertEqual('session1', cinder._get_cinder_session())
        self.assertFalse(mock_keystone_session.called)
        self.assertFalse(mock_auth.called)


@mock.patch('ironic.common.keystone.get_adapter', autospec=True)
@mock.patch('ironic.common.keystone.get_service_auth', autospec=True,
            return_value=mock.sentinel.sauth)
@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(cinderclient.Client, '__init__', autospec=True,
                   return_value=None)
class TestCinderClient(base.TestCase):

    def setUp(self):
        super(TestCinderClient, self).setUp()
        self.config(timeout=1,
                    retries=2,
                    group='cinder')
        cinder._CINDER_SESSION = None
        self.context = context.RequestContext(global_request_id='global')

    def _assert_client_call(self, init_mock, url, auth=mock.sentinel.auth):
        cinder.get_client(self.context)
        init_mock.assert_called_once_with(
            mock.ANY,
            session=mock.sentinel.session,
            auth=auth,
            endpoint_override=url,
            connect_retries=2,
            global_request_id='global')

    def test_get_client(self, mock_client_init, mock_session, mock_auth,
                        mock_sauth, mock_adapter):

        mock_adapter.return_value = mock_adapter_obj = mock.Mock()
        mock_adapter_obj.get_endpoint.return_value = 'cinder_url'
        self._assert_client_call(mock_client_init, 'cinder_url')
        mock_session.assert_called_once_with('cinder')
        mock_auth.assert_called_once_with('cinder')
        mock_adapter.assert_called_once_with('cinder',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        self.assertFalse(mock_sauth.called)

    def test_get_client_deprecated_opts(self, mock_client_init, mock_session,
                                        mock_auth, mock_sauth, mock_adapter):

        self.config(url='http://test-url', group='cinder')
        mock_adapter.return_value = mock_adapter_obj = mock.Mock()
        mock_adapter_obj.get_endpoint.return_value = 'http://test-url'

        self._assert_client_call(mock_client_init, 'http://test-url')
        mock_auth.assert_called_once_with('cinder')
        mock_session.assert_called_once_with('cinder')
        mock_adapter.assert_called_once_with(
            'cinder', session=mock.sentinel.session, auth=mock.sentinel.auth,
            endpoint_override='http://test-url')
        self.assertFalse(mock_sauth.called)


class TestCinderUtils(db_base.DbTestCase):

    def setUp(self):
        super(TestCinderUtils, self).setUp()
        self.node = object_utils.create_test_node(
            self.context,
            instance_uuid=uuidutils.generate_uuid())

    def test_is_volume_available(self):
        available_volumes = [
            mock.Mock(status=cinder.AVAILABLE, multiattach=False),
            mock.Mock(status=cinder.IN_USE, multiattach=True)]
        unavailable_volumes = [
            mock.Mock(status=cinder.IN_USE, multiattach=False),
            mock.Mock(status='fake-non-status', multiattach=True)]

        for vol in available_volumes:
            result = cinder.is_volume_available(vol)
            self.assertTrue(result,
                            msg="Failed for status '%s'." % vol.status)

        for vol in unavailable_volumes:
            result = cinder.is_volume_available(vol)
            self.assertFalse(result,
                             msg="Failed for status '%s'." % vol.status)

    def test_is_volume_attached(self):
        attached_vol = mock.Mock(id='foo', attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'meow'}])
        attached_vol2 = mock.Mock(id='bar', attachments=[
            {'server_id': self.node.instance_uuid, 'attachment_id': 'meow'}],)
        unattached = mock.Mock(attachments=[])
        self.assertTrue(cinder.is_volume_attached(self.node, attached_vol))
        self.assertTrue(cinder.is_volume_attached(self.node, attached_vol2))
        self.assertFalse(cinder.is_volume_attached(self.node, unattached))

    def test__get_attachment_id(self):
        expectation = 'meow'
        attached_vol = mock.Mock(attachments=[
            {'server_id': self.node.instance_uuid, 'attachment_id': 'meow'}])
        attached_vol2 = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'meow'}])
        unattached = mock.Mock(attachments=[])
        no_attachment = mock.Mock(attachments=[
            {'server_id': 'cat', 'id': 'cat'}])

        self.assertEqual(expectation,
                         cinder._get_attachment_id(self.node, attached_vol))
        self.assertEqual(expectation,
                         cinder._get_attachment_id(self.node, attached_vol2))
        self.assertIsNone(cinder._get_attachment_id(self.node, unattached))
        self.assertIsNone(cinder._get_attachment_id(self.node, no_attachment))

    @mock.patch.object(datetime, 'datetime', autospec=True)
    def test__create_metadata_dictionary(self, mock_datetime):
        fake_time = '2017-06-05T00:33:26.574676'
        mock_utcnow = mock.Mock()
        mock_datetime.utcnow.return_value = mock_utcnow
        mock_utcnow.isoformat.return_value = fake_time
        expected_key = ("ironic_node_%s" % self.node.uuid)
        expected_data = {
            'instance_uuid': self.node.instance_uuid,
            'last_seen': fake_time,
            'last_action': 'meow'
        }

        result = cinder._create_metadata_dictionary(self.node, 'meow')
        data = json.loads(result[expected_key])
        self.assertEqual(expected_data, data)


@mock.patch.object(cinder, '_get_cinder_session', autospec=True)
@mock.patch.object(cinderclient.volumes.VolumeManager, 'set_metadata',
                   autospec=True)
@mock.patch.object(cinderclient.volumes.VolumeManager, 'get', autospec=True)
class TestCinderActions(db_base.DbTestCase):

    def setUp(self):
        super(TestCinderActions, self).setUp()
        self.node = object_utils.create_test_node(
            self.context,
            instance_uuid=uuidutils.generate_uuid())
        self.mount_point = 'ironic_mountpoint'

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'attach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'initialize_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes(self, mock_create_meta, mock_is_attached,
                            mock_reserve, mock_init, mock_attach, mock_get,
                            mock_set_meta, mock_session):
        """Iterate once on a single volume with success."""

        volume_id = '111111111-0000-0000-0000-000000000003'
        expected = [{
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'volume_id': volume_id,
                'target_lun': 2,
                'ironic_volume_uuid': '000-001'}}]
        volumes = [volume_id]

        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = False
        mock_get.return_value = mock.Mock(attachments=[], id='000-001')

        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            attachments = cinder.attach_volumes(task, volumes, connector)

        self.assertEqual(expected, attachments)
        mock_reserve.assert_called_once_with(mock.ANY, volume_id)
        mock_init.assert_called_once_with(mock.ANY, volume_id, connector)
        mock_attach.assert_called_once_with(mock.ANY, volume_id,
                                            self.node.instance_uuid,
                                            self.mount_point)
        mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                              {'bar': 'baz'})
        mock_get.assert_called_once_with(mock.ANY, volume_id)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'attach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'initialize_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_one_attached(
            self, mock_create_meta, mock_reserve, mock_init, mock_attach,
            mock_get, mock_set_meta, mock_session):
        """Iterate with two volumes, one already attached."""

        volume_id = '111111111-0000-0000-0000-000000000003'
        expected = [
            {'driver_volume_type': 'iscsi',
             'data': {
                 'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                 'target_portal': '127.0.0.0.1:3260',
                 'volume_id': volume_id,
                 'target_lun': 2,
                 'ironic_volume_uuid': '000-000'}},
            {'already_attached': True,
             'data': {
                 'volume_id': 'already_attached',
                 'ironic_volume_uuid': '000-001'}}]

        volumes = [volume_id, 'already_attached']
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_get.side_effect = [
            mock.Mock(attachments=[], id='000-000'),
            mock.Mock(attachments=[{'server_id': self.node.uuid}],
                      id='000-001')
        ]

        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            attachments = cinder.attach_volumes(task, volumes, connector)

        self.assertEqual(expected, attachments)
        mock_reserve.assert_called_once_with(mock.ANY, volume_id)
        mock_init.assert_called_once_with(mock.ANY, volume_id, connector)
        mock_attach.assert_called_once_with(mock.ANY, volume_id,
                                            self.node.instance_uuid,
                                            self.mount_point)
        mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                              {'bar': 'baz'})

    @mock.patch.object(cinderclient.Client, '__init__', autospec=True)
    def test_attach_volumes_client_init_failure(
            self, mock_client, mock_get, mock_set_meta, mock_session):
        connector = {'foo': 'bar'}
        volumes = ['111111111-0000-0000-0000-000000000003']
        mock_client.side_effect = cinder_exceptions.BadRequest(
            http_client.BAD_REQUEST)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'attach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'initialize_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_vol_not_found(
            self, mock_create_meta, mock_reserve, mock_init, mock_attach,
            mock_get, mock_set_meta, mock_session):
        """Raise an error if the volume lookup fails"""

        def __mock_get_side_effect(client, volume_id):
            if volume_id == 'not_found':
                raise cinder_exceptions.NotFound(
                    http_client.NOT_FOUND, message='error')
            else:
                return mock.Mock(attachments=[], uuid='000-000')

        volumes = ['111111111-0000-0000-0000-000000000003',
                   'not_found',
                   'not_reached']
        connector = {'foo': 'bar'}
        mock_get.side_effect = __mock_get_side_effect
        mock_create_meta.return_value = {'bar': 'baz'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)
        mock_get.assert_any_call(mock.ANY,
                                 '111111111-0000-0000-0000-000000000003')
        mock_get.assert_any_call(mock.ANY, 'not_found')
        self.assertEqual(2, mock_get.call_count)
        mock_reserve.assert_called_once_with(
            mock.ANY, '111111111-0000-0000-0000-000000000003')
        mock_init.assert_called_once_with(
            mock.ANY, '111111111-0000-0000-0000-000000000003', connector)
        mock_attach.assert_called_once_with(
            mock.ANY, '111111111-0000-0000-0000-000000000003',
            self.node.instance_uuid, self.mount_point)
        mock_set_meta.assert_called_once_with(
            mock.ANY, '111111111-0000-0000-0000-000000000003', {'bar': 'baz'})

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    def test_attach_volumes_reserve_failure(self, mock_is_attached,
                                            mock_reserve, mock_get,
                                            mock_set_meta, mock_session):
        volumes = ['111111111-0000-0000-0000-000000000003']
        connector = {'foo': 'bar'}
        volume = mock.Mock(attachments=[])
        mock_get.return_value = volume
        mock_is_attached.return_value = False
        mock_reserve.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)
        mock_is_attached.assert_called_once_with(mock.ANY, volume)

    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'initialize_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_initialize_connection_failure(
            self, mock_create_meta, mock_is_attached, mock_reserve, mock_init,
            mock_get, mock_set_meta, mock_session):
        """Fail attachment upon an initialization failure."""

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = False
        mock_get.return_value = mock.Mock(attachments=[])
        mock_init.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)

        mock_get.assert_called_once_with(mock.ANY, volume_id)
        mock_reserve.assert_called_once_with(mock.ANY, volume_id)
        mock_init.assert_called_once_with(mock.ANY, volume_id, connector)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'attach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'initialize_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_attach_record_failure(
            self, mock_create_meta, mock_is_attached, mock_reserve,
            mock_init, mock_attach, mock_get, mock_set_meta, mock_session):
        """Attach a volume and fail if final record failure occurs"""
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = False
        mock_get.return_value = mock.Mock(attachments=[], id='000-003')
        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}
        mock_attach.side_effect = cinder_exceptions.ClientException(
            http_client.NOT_ACCEPTABLE, 'error')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError, cinder.attach_volumes,
                              task, volumes, connector)

        mock_reserve.assert_called_once_with(mock.ANY, volume_id)
        mock_init.assert_called_once_with(mock.ANY, volume_id, connector)
        mock_attach.assert_called_once_with(mock.ANY, volume_id,
                                            self.node.instance_uuid,
                                            self.mount_point)
        mock_get.assert_called_once_with(mock.ANY, volume_id)
        mock_is_attached.assert_called_once_with(mock.ANY,
                                                 mock_get.return_value)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'attach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'initialize_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'reserve',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_attach_volumes_attach_set_meta_failure(
            self, mock_log, mock_create_meta, mock_is_attached,
            mock_reserve, mock_init, mock_attach, mock_get, mock_set_meta,
            mock_session):
        """Attach a volume and tolerate set_metadata failure."""

        expected = [{
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'volume_id': '111111111-0000-0000-0000-000000000003',
                'target_lun': 2,
                'ironic_volume_uuid': '000-000'}}]
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = False
        mock_get.return_value = mock.Mock(attachments=[], id='000-000')
        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}
        mock_set_meta.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            attachments = cinder.attach_volumes(task, volumes, connector)

        self.assertEqual(expected, attachments)
        mock_reserve.assert_called_once_with(mock.ANY, volume_id)
        mock_init.assert_called_once_with(mock.ANY, volume_id, connector)
        mock_attach.assert_called_once_with(mock.ANY, volume_id,
                                            self.node.instance_uuid,
                                            self.mount_point)
        mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                              {'bar': 'baz'})
        mock_get.assert_called_once_with(mock.ANY, volume_id)
        mock_is_attached.assert_called_once_with(mock.ANY,
                                                 mock_get.return_value)
        self.assertTrue(mock_log.warning.called)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'detach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes(
            self, mock_create_meta, mock_is_attached, mock_begin, mock_term,
            mock_detach, mock_get, mock_set_meta, mock_session):
        """Iterate once and detach a volume without issues."""
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]

        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_get.return_value = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=False)

        mock_begin.assert_called_once_with(mock.ANY, volume_id)
        mock_term.assert_called_once_with(mock.ANY, volume_id, {'foo': 'bar'})
        mock_detach.assert_called_once_with(mock.ANY, volume_id, 'qux')
        mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                              {'bar': 'baz'})

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'detach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_one_detached(
            self, mock_create_meta, mock_begin, mock_term, mock_detach,
            mock_get, mock_set_meta, mock_session):
        """Iterate with two volumes, one already detached."""
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id, 'detached']

        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}

        mock_get.side_effect = [
            mock.Mock(attachments=[
                {'server_id': self.node.uuid, 'attachment_id': 'qux'}]),
            mock.Mock(attachments=[])
        ]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=False)

        mock_begin.assert_called_once_with(mock.ANY, volume_id)
        mock_term.assert_called_once_with(mock.ANY, volume_id, {'foo': 'bar'})
        mock_detach.assert_called_once_with(mock.ANY, volume_id, 'qux')
        mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                              {'bar': 'baz'})

    @mock.patch.object(cinderclient.Client, '__init__', autospec=True)
    def test_detach_volumes_client_init_failure_bad_request(
            self, mock_client, mock_get, mock_set_meta, mock_session):
        connector = {'foo': 'bar'}
        volumes = ['111111111-0000-0000-0000-000000000003']

        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_client.side_effect = cinder_exceptions.BadRequest(
                http_client.BAD_REQUEST)
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)

    @mock.patch.object(cinderclient.Client, '__init__', autospec=True)
    def test_detach_volumes_client_init_failure_invalid_parameter_value(
            self, mock_client, mock_get, mock_set_meta, mock_session):
        connector = {'foo': 'bar'}
        volumes = ['111111111-0000-0000-0000-000000000003']
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # While we would be permitting failures, this is an exception that
            # must be raised since the client cannot be initialized.
            mock_client.side_effect = exception.InvalidParameterValue('error')
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes, task, volumes,
                              connector, allow_errors=True)

    def test_detach_volumes_vol_not_found(self, mock_get, mock_set_meta,
                                          mock_session):
        """Raise an error if the volume lookup fails"""
        volumes = ['vol1']
        connector = {'foo': 'bar'}
        mock_get.side_effect = cinder_exceptions.NotFound(
            http_client.NOT_FOUND, message='error')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)
            self.assertFalse(mock_set_meta.called)
            # We should not raise any exception when issuing a command
            # with errors being permitted.
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            self.assertFalse(mock_set_meta.called)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'detach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_begin_detaching_failure(
            self, mock_create_meta, mock_is_attached, mock_begin, mock_term,
            mock_detach, mock_get, mock_set_meta, mock_session):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        volume = mock.Mock(attachments=[])
        mock_get.return_value = volume
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_begin.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)
            mock_is_attached.assert_called_once_with(mock.ANY, volume)
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            mock_term.assert_called_once_with(mock.ANY, volume_id,
                                              {'foo': 'bar'})
            mock_detach.assert_called_once_with(mock.ANY, volume_id, None)
            mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                                  {'bar': 'baz'})

    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_term_failure(
            self, mock_create_meta, mock_is_attached, mock_begin, mock_term,
            mock_get, mock_set_meta, mock_session):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_get.return_value = {'id': volume_id, 'attachments': []}
        mock_term.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)
            mock_begin.assert_called_once_with(mock.ANY, volume_id)
            mock_term.assert_called_once_with(mock.ANY, volume_id, connector)
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            self.assertFalse(mock_set_meta.called)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'detach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_detach_failure_errors_not_allowed(
            self, mock_create_meta, mock_is_attached, mock_begin, mock_term,
            mock_detach, mock_get, mock_set_meta, mock_session):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_get.return_value = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_detach.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector,
                              allow_errors=False)
            mock_detach.assert_called_once_with(mock.ANY, volume_id, 'qux')
            self.assertFalse(mock_set_meta.called)

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'detach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_detach_failure_errors_allowed(
            self, mock_create_meta, mock_is_attached, mock_begin, mock_term,
            mock_detach, mock_get, mock_set_meta, mock_session):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_get.return_value = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_set_meta.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            mock_detach.assert_called_once_with(mock.ANY, volume_id, 'qux')
            mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                                  {'bar': 'baz'})

    @mock.patch.object(cinderclient.volumes.VolumeManager, 'detach',
                       autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager,
                       'terminate_connection', autospec=True)
    @mock.patch.object(cinderclient.volumes.VolumeManager, 'begin_detaching',
                       autospec=True)
    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_detach_meta_failure_errors_not_allowed(
            self, mock_create_meta, mock_is_attached, mock_begin, mock_term,
            mock_detach, mock_get, mock_set_meta, mock_session):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_get.return_value = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_set_meta.side_effect = cinder_exceptions.NotAcceptable(
            http_client.NOT_ACCEPTABLE)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=False)
            mock_detach.assert_called_once_with(mock.ANY, volume_id, 'qux')
            mock_set_meta.assert_called_once_with(mock.ANY, volume_id,
                                                  {'bar': 'baz'})
