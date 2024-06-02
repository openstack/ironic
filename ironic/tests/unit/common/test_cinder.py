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

import json
from unittest import mock

from keystoneauth1 import loading as ks_loading
import openstack
from openstack.connection import exceptions as openstack_exc
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import cinder
from ironic.common import context
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


@mock.patch('ironic.common.keystone.get_service_auth', autospec=True,
            return_value=mock.sentinel.sauth)
@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_adapter', autospec=True)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(openstack.connection, "Connection", autospec=True)
class TestCinderClient(base.TestCase):

    def setUp(self):
        super(TestCinderClient, self).setUp()
        # NOTE(pas-ha) register keystoneauth dynamic options manually
        plugin = ks_loading.get_plugin_loader('password')
        opts = ks_loading.get_auth_plugin_conf_options(plugin)
        self.cfg_fixture.register_opts(opts, group='cinder')
        self.config(retries=2,
                    group='cinder')
        self.config(username='test-admin-user',
                    project_name='test-admin-tenant',
                    password='test-admin-password',
                    auth_url='test-auth-uri',
                    auth_type='password',
                    interface='internal',
                    service_type='block_storage',
                    timeout=10,
                    group='cinder')
        # force-reset the global session object
        cinder._CINDER_SESSION = None
        self.context = context.RequestContext(global_request_id='global')

    def test_get_cinder_client_with_context(self, mock_client_init,
                                            mock_session, mock_adapter,
                                            mock_auth, mock_sauth):
        self.context = context.RequestContext(global_request_id='global',
                                              auth_token='test-token-123')
        cinder.get_client(context=self.context)
        mock_client_init.assert_called_once_with(
            session=mock.sentinel.session,
            block_storage_endpoint_override=mock.ANY,
            block_storage_api_version='3')
        # testing handling of default url_timeout
        mock_session.assert_has_calls([
            mock.call('cinder'),
            mock.call('cinder', auth=mock.sentinel.sauth, timeout=10)
        ])

    def test__get_cinder_session(self, mock_client_init,
                                 mock_session, mock_adapter,
                                 mock_auth, mock_sauth):
        """Check establishing new session when no session exists."""
        mock_session.return_value = 'session1'
        self.assertEqual('session1', cinder._get_cinder_session())
        mock_session.assert_called_once_with('cinder')

        """Check if existing session is used."""
        mock_session.reset_mock()
        mock_session.return_value = 'session2'
        self.assertEqual('session1', cinder._get_cinder_session())
        self.assertFalse(mock_session.called)


class TestCinderUtils(db_base.DbTestCase):

    def setUp(self):
        super(TestCinderUtils, self).setUp()
        self.node = object_utils.create_test_node(
            self.context,
            instance_uuid=uuidutils.generate_uuid())

    def test_is_volume_available(self):
        available_volumes = [
            mock.Mock(status=cinder.AVAILABLE, is_multiattach=False),
            mock.Mock(status=cinder.IN_USE, is_multiattach=True)]
        unavailable_volumes = [
            mock.Mock(status=cinder.IN_USE, is_multiattach=False),
            mock.Mock(status='fake-non-status', is_multiattach=True)]

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

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test__create_metadata_dictionary(self, mock_utcnow):
        fake_time = '2017-06-05T00:33:26.574676'
        mock_datetime = mock.Mock()
        mock_datetime.isoformat.return_value = fake_time

        mock_utcnow.return_value = mock_datetime

        expected_key = ("ironic_node_%s" % self.node.uuid)
        expected_data = {
            'instance_uuid': self.node.instance_uuid,
            'last_seen': fake_time,
            'last_action': 'meow'
        }

        result = cinder._create_metadata_dictionary(self.node, 'meow')
        data = json.loads(result[expected_key])
        self.assertEqual(expected_data, data)


@mock.patch.object(cinder, 'get_client', autospec=True)
class TestCinderActions(db_base.DbTestCase):

    def setUp(self):
        super(TestCinderActions, self).setUp()
        self.node = object_utils.create_test_node(
            self.context,
            instance_uuid=uuidutils.generate_uuid())
        self.mount_point = 'ironic_mountpoint'

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes(self, mock_create_meta, mock_is_attached,
                            mock_client):
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

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_init = mock_bs.init_volume_attachment
        mock_reserve = mock_bs.reserve_volume
        mock_attach = mock_bs.attach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[], id='000-001')
        mock_get.return_value = volume

        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            attachments = cinder.attach_volumes(task, volumes, connector)

        self.assertEqual(expected, attachments)
        mock_reserve.assert_called_once_with(volume)
        mock_init.assert_called_once_with(volume, connector)
        mock_attach.assert_called_once_with(volume,
                                            self.mount_point,
                                            instance=self.node.instance_uuid)
        mock_set_meta.assert_called_once_with(volume, bar='baz')
        mock_get.assert_called_once_with(volume_id)

    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_one_attached(
            self, mock_create_meta, mock_client):
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

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_init = mock_bs.init_volume_attachment
        mock_reserve = mock_bs.reserve_volume
        mock_attach = mock_bs.attach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[], id='000-000')
        mock_get.side_effect = [
            volume,
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
        mock_reserve.assert_called_once_with(volume)
        mock_init.assert_called_once_with(volume, connector)
        mock_attach.assert_called_once_with(volume,
                                            self.mount_point,
                                            instance=self.node.instance_uuid)
        mock_set_meta.assert_called_once_with(volume, bar='baz')

    def test_attach_volumes_conn_init_failure(
            self, mock_client):
        connector = {'foo': 'bar'}
        volumes = ['111111111-0000-0000-0000-000000000003']
        mock_client.side_effect = openstack_exc.EndpointNotFound()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)

    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_vol_not_found(
            self, mock_create_meta, mock_client):
        """Raise an error if the volume lookup fails"""

        volume = mock.Mock(attachments=[], uuid='000-000')

        def __mock_get_side_effect(vol):
            if vol == 'not_found':
                raise openstack_exc.ResourceNotFound()
            else:
                return volume

        volumes = ['111111111-0000-0000-0000-000000000003',
                   'not_found',
                   'not_reached']
        connector = {'foo': 'bar'}

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_init = mock_bs.init_volume_attachment
        mock_reserve = mock_bs.reserve_volume
        mock_attach = mock_bs.attach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        mock_get.side_effect = __mock_get_side_effect
        mock_create_meta.return_value = {'bar': 'baz'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)
        mock_get.assert_any_call('111111111-0000-0000-0000-000000000003')
        mock_get.assert_any_call('not_found')
        self.assertEqual(2, mock_get.call_count)
        mock_reserve.assert_called_once_with(volume)
        mock_init.assert_called_once_with(volume, connector)
        mock_attach.assert_called_once_with(
            volume, self.mount_point, instance=self.node.instance_uuid)
        mock_set_meta.assert_called_once_with(volume, bar='baz')

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    def test_attach_volumes_reserve_failure(self, mock_is_attached,
                                            mock_client):
        volumes = ['111111111-0000-0000-0000-000000000003']
        connector = {'foo': 'bar'}
        volume = mock.Mock(attachments=[])
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_reserve = mock_bs.reserve_volume
        mock_get.return_value = volume
        mock_is_attached.return_value = False
        mock_reserve.side_effect = openstack_exc.HttpException()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)
        mock_is_attached.assert_called_once_with(mock.ANY, volume)

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_initialize_connection_failure(
            self, mock_create_meta, mock_is_attached,
            mock_client):
        """Fail attachment upon an initialization failure."""

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = False

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_init = mock_bs.init_volume_attachment
        mock_reserve = mock_bs.reserve_volume

        volume = mock.Mock(attachments=[])
        mock_get.return_value = volume
        mock_init.side_effect = openstack_exc.HttpException("not acceptable")

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.attach_volumes,
                              task,
                              volumes,
                              connector)

        mock_get.assert_called_once_with(volume_id)
        mock_reserve.assert_called_once_with(volume)
        mock_init.assert_called_once_with(volume, connector)

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_attach_volumes_attach_record_failure(
            self, mock_create_meta, mock_is_attached, mock_client):
        """Attach a volume and fail if final record failure occurs"""
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = False

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_init = mock_bs.init_volume_attachment
        mock_reserve = mock_bs.reserve_volume
        mock_attach = mock_bs.attach_volume

        volume = mock.Mock(attachments=[], id='000-003')
        mock_get.return_value = volume
        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}
        mock_attach.side_effect = openstack_exc.HttpException("not acceptable")

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError, cinder.attach_volumes,
                              task, volumes, connector)

        mock_reserve.assert_called_once_with(volume)
        mock_init.assert_called_once_with(volume, connector)
        mock_attach.assert_called_once_with(volume,
                                            self.mount_point,
                                            instance=self.node.instance_uuid)
        mock_get.assert_called_once_with(volume_id)
        mock_is_attached.assert_called_once_with(mock.ANY, volume)

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_attach_volumes_attach_set_meta_failure(
            self, mock_log, mock_create_meta, mock_is_attached,
            mock_client):
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

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_init = mock_bs.init_volume_attachment
        mock_reserve = mock_bs.reserve_volume
        mock_attach = mock_bs.attach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[], id='000-000')
        mock_get.return_value = volume
        mock_init.return_value = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000002',
                'target_portal': '127.0.0.0.1:3260',
                'target_lun': 2}}
        mock_set_meta.side_effect = openstack_exc.HttpException()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            attachments = cinder.attach_volumes(task, volumes, connector)

        self.assertEqual(expected, attachments)
        mock_reserve.assert_called_once_with(volume)
        mock_init.assert_called_once_with(volume, connector)
        mock_attach.assert_called_once_with(volume,
                                            self.mount_point,
                                            instance=self.node.instance_uuid)
        mock_set_meta.assert_called_once_with(volume, bar='baz')
        mock_get.assert_called_once_with(volume_id)
        mock_is_attached.assert_called_once_with(mock.ANY, volume)
        self.assertTrue(mock_log.warning.called)

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes(
            self, mock_create_meta, mock_is_attached, mock_client):
        """Iterate once and detach a volume without issues."""
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]

        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_begin = mock_bs.begin_volume_detaching
        mock_term = mock_bs.terminate_volume_attachment
        mock_detach = mock_bs.detach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_get.return_value = volume

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=False)

        mock_begin.assert_called_once_with(volume)
        mock_term.assert_called_once_with(volume, {'foo': 'bar'})
        mock_detach.assert_called_once_with(volume, 'qux')
        mock_set_meta.assert_called_once_with(volume, bar='baz')

    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_one_detached(
            self, mock_create_meta, mock_client):
        """Iterate with two volumes, one already detached."""
        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id, 'detached']

        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}

        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_begin = mock_bs.begin_volume_detaching
        mock_term = mock_bs.terminate_volume_attachment
        mock_detach = mock_bs.detach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_get.side_effect = [
            volume, mock.Mock(attachments=[])
        ]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=False)

        mock_begin.assert_called_once_with(volume)
        mock_term.assert_called_once_with(volume, {'foo': 'bar'})
        mock_detach.assert_called_once_with(volume, 'qux')
        mock_set_meta.assert_called_once_with(volume, bar='baz')

    def test_detach_volumes_conn_init_failure_bad_request(
            self, mock_client):
        connector = {'foo': 'bar'}
        volumes = ['111111111-0000-0000-0000-000000000003']

        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_client.side_effect = openstack_exc.BadRequestException()
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)

    def test_detach_volumes_vol_not_found(self, mock_client):
        """Raise an error if the volume lookup fails"""
        volumes = ['vol1']
        connector = {'foo': 'bar'}
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_set_meta = mock_bs.set_volume_metadata

        mock_get.side_effect = openstack_exc.NotFoundException()

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

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_begin_detaching_failure(
            self, mock_create_meta, mock_is_attached, mock_client):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_begin = mock_bs.begin_volume_detaching
        mock_term = mock_bs.terminate_volume_attachment
        mock_detach = mock_bs.detach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[])
        mock_get.return_value = volume
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_begin.side_effect = openstack_exc.HttpException("not acceptable")

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)
            mock_is_attached.assert_called_once_with(mock.ANY, volume)
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            mock_term.assert_called_once_with(volume,
                                              {'foo': 'bar'})
            mock_detach.assert_called_once_with(volume, None)
            mock_set_meta.assert_called_once_with(volume, bar='baz')

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_term_failure(
            self, mock_create_meta, mock_is_attached, mock_client):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_begin = mock_bs.begin_volume_detaching
        mock_term = mock_bs.terminate_volume_attachment
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(id=volume_id, attachments=[])
        mock_get.return_value = volume
        mock_term.side_effect = openstack_exc.HttpException("not acceptable")

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector)
            mock_begin.assert_called_once_with(volume)
            mock_term.assert_called_once_with(volume, connector)
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            self.assertFalse(mock_set_meta.called)

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_detach_failure_errors_not_allowed(
            self, mock_create_meta, mock_is_attached, mock_client):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_detach = mock_bs.detach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_get.return_value = volume
        mock_detach.side_effect = openstack_exc.HttpException("not acceptable")

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.StorageError,
                              cinder.detach_volumes,
                              task,
                              volumes,
                              connector,
                              allow_errors=False)
            mock_detach.assert_called_once_with(volume, 'qux')
            self.assertFalse(mock_set_meta.called)

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_detach_failure_errors_allowed(
            self, mock_create_meta, mock_is_attached, mock_client):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_detach = mock_bs.detach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_get.return_value = volume
        mock_set_meta.side_effect = openstack_exc.HttpException()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=True)
            mock_detach.assert_called_once_with(volume, 'qux')
            mock_set_meta.assert_called_once_with(volume, bar='baz')

    @mock.patch.object(cinder, 'is_volume_attached', autospec=True)
    @mock.patch.object(cinder, '_create_metadata_dictionary', autospec=True)
    def test_detach_volumes_detach_meta_failure_errors_not_allowed(
            self, mock_create_meta, mock_is_attached, mock_client):

        volume_id = '111111111-0000-0000-0000-000000000003'
        volumes = [volume_id]
        connector = {'foo': 'bar'}
        mock_create_meta.return_value = {'bar': 'baz'}
        mock_is_attached.return_value = True
        mock_bs = mock_client.return_value
        mock_get = mock_bs.get_volume
        mock_detach = mock_bs.detach_volume
        mock_set_meta = mock_bs.set_volume_metadata

        volume = mock.Mock(attachments=[
            {'server_id': self.node.uuid, 'attachment_id': 'qux'}])
        mock_get.return_value = volume
        mock_set_meta.side_effect = openstack_exc.HttpException()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            cinder.detach_volumes(task, volumes, connector, allow_errors=False)
            mock_detach.assert_called_once_with(volume, 'qux')
            mock_set_meta.assert_called_once_with(volume, bar='baz')
