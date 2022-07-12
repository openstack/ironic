# Copyright 2016 Hewlett Packard Enterprise Development Company LP.
# Copyright 2016 IBM Corp
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

from oslo_utils import uuidutils

from ironic.common import cinder as cinder_common
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.storage import cinder
from ironic.drivers import utils as driver_utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


class CinderInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(CinderInterfaceTestCase, self).setUp()
        self.config(action_retries=3,
                    action_retry_interval=0,
                    group='cinder')
        self.config(enabled_boot_interfaces=['fake', 'pxe'],
                    enabled_storage_interfaces=['noop', 'cinder'])
        self.interface = cinder.CinderStorage()
        self.node = object_utils.create_test_node(self.context,
                                                  boot_interface='fake',
                                                  storage_interface='cinder')

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test__fail_validation(self, mock_log):
        """Ensure the validate helper logs and raises exceptions."""
        fake_error = 'an error!'
        expected = ("Failed to validate cinder storage interface for node "
                    "%s. an error!" % self.node.uuid)
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface._fail_validation,
                              task,
                              fake_error)
        mock_log.error.assert_called_with(expected)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test__generate_connector_raises_with_insufficient_data(self, mock_log):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.StorageError,
                              self.interface._generate_connector,
                              task)
        self.assertTrue(mock_log.error.called)

    def test__generate_connector_iscsi(self):
        expected = {
            'initiator': 'iqn.address',
            'ip': 'ip.address',
            'host': self.node.uuid,
            'multipath': True}
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='ip',
            connector_id='ip.address', uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            return_value = self.interface._generate_connector(task)
        self.assertDictEqual(expected, return_value)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test__generate_connector_iscsi_and_unknown(self, mock_log):
        """Validate we return and log with valid and invalid connectors."""
        expected = {
            'initiator': 'iqn.address',
            'host': self.node.uuid,
            'multipath': True}
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='foo',
            connector_id='bar', uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            return_value = self.interface._generate_connector(task)
        self.assertDictEqual(expected, return_value)
        self.assertEqual(1, mock_log.warning.call_count)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test__generate_connector_unknown_raises_excption(self, mock_log):
        """Validate an exception is raised with only an invalid connector."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='foo',
            connector_id='bar')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(
                exception.StorageError,
                self.interface._generate_connector,
                task)
        self.assertEqual(1, mock_log.warning.call_count)
        self.assertEqual(1, mock_log.error.call_count)

    def test__generate_connector_single_path(self):
        """Validate an exception is raised with only an invalid connector."""
        expected = {
            'initiator': 'iqn.address',
            'host': self.node.uuid}
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')
        with task_manager.acquire(self.context, self.node.id) as task:
            return_value = self.interface._generate_connector(task)
        self.assertDictEqual(expected, return_value)

    def test__generate_connector_multiple_fc_wwns(self):
        """Validate handling of WWPNs and WWNNs."""
        expected = {
            'wwpns': ['wwpn1', 'wwpn2'],
            'wwnns': ['wwnn3', 'wwnn4'],
            'host': self.node.uuid,
            'multipath': True}
        object_utils.create_test_volume_connector(
            self.context,
            node_id=self.node.id,
            type='wwpn',
            connector_id='wwpn1',
            uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context,
            node_id=self.node.id,
            type='wwpn',
            connector_id='wwpn2',
            uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context,
            node_id=self.node.id,
            type='wwnn',
            connector_id='wwnn3',
            uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context,
            node_id=self.node.id,
            type='wwnn',
            connector_id='wwnn4',
            uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            return_value = self.interface._generate_connector(task)
        self.assertDictEqual(expected, return_value)

    @mock.patch.object(cinder.CinderStorage, '_fail_validation', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_success_no_settings(self, mock_log, mock_fail):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
        self.assertFalse(mock_fail.called)
        self.assertFalse(mock_log.called)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_failure_if_iscsi_boot_no_connectors(self, mock_log):
        valid_types = ', '.join(cinder.VALID_ISCSI_TYPES)
        expected_msg = ("Failed to validate cinder storage interface for node "
                        "%(id)s. In order to enable the 'iscsi_boot' "
                        "capability for the node, an associated "
                        "volume_connector type must be valid for "
                        "iSCSI (%(options)s)." %
                        {'id': self.node.uuid, 'options': valid_types})

        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task, 'iscsi_boot', 'True')
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        mock_log.error.assert_called_once_with(expected_msg)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_failure_if_fc_boot_no_connectors(self, mock_log):
        valid_types = ', '.join(cinder.VALID_FC_TYPES)
        expected_msg = ("Failed to validate cinder storage interface for node "
                        "%(id)s. In order to enable the 'fibre_channel_boot' "
                        "capability for the node, an associated "
                        "volume_connector type must be valid for "
                        "Fibre Channel (%(options)s)." %
                        {'id': self.node.uuid, 'options': valid_types})
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task,
                                             'fibre_channel_boot',
                                             'True')
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        mock_log.error.assert_called_once_with(expected_msg)

    @mock.patch.object(cinder.CinderStorage, '_fail_validation', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_success_iscsi_connector(self, mock_log, mock_fail):
        """Perform validate with only an iSCSI connector in place."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
        self.assertFalse(mock_log.called)
        self.assertFalse(mock_fail.called)

    @mock.patch.object(cinder.CinderStorage, '_fail_validation', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_success_fc_connectors(self, mock_log, mock_fail):
        """Perform validate with only FC connectors in place"""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwpn',
            connector_id='wwpn.address', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwnn',
            connector_id='wwnn.address', uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
        self.assertFalse(mock_log.called)
        self.assertFalse(mock_fail.called)

    @mock.patch.object(cinder.CinderStorage, '_fail_validation', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_success_connectors_and_boot(self, mock_log, mock_fail):
        """Perform validate with volume connectors and boot capabilities."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwpn',
            connector_id='wwpn.address', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwnn',
            connector_id='wwnn.address', uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task,
                                             'fibre_channel_boot',
                                             'True')
            driver_utils.add_node_capability(task, 'iscsi_boot', 'True')
            self.interface.validate(task)
        self.assertFalse(mock_log.called)
        self.assertFalse(mock_fail.called)

    @mock.patch.object(cinder.CinderStorage, '_fail_validation', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_success_iscsi_targets(self, mock_log, mock_fail):
        """Validate success with full iscsi scenario."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task, 'iscsi_boot', 'True')
            self.interface.validate(task)
        self.assertFalse(mock_log.called)
        self.assertFalse(mock_fail.called)

    @mock.patch.object(cinder.CinderStorage, '_fail_validation', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_success_fc_targets(self, mock_log, mock_fail):
        """Validate success with full fc scenario."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwpn',
            connector_id='fc.address', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwnn',
            connector_id='fc.address', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='fibre_channel',
            boot_index=0, volume_id='1234')
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task,
                                             'fibre_channel_boot',
                                             'True')
            self.interface.validate(task)
        self.assertFalse(mock_log.called)
        self.assertFalse(mock_fail.called)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_fails_with_ipxe_not_enabled(self, mock_log):
        """Ensure a validation failure is raised when iPXE not enabled."""
        self.node.boot_interface = 'pxe'
        self.node.save()
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='foo.address')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='2345')
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task, 'iscsi_boot', 'True')
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_fails_when_fc_connectors_unequal(self, mock_log):
        """Validate should fail with only wwnn FC connector in place"""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='wwnn',
            connector_id='wwnn.address')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.StorageError,
                              self.interface.validate,
                              task)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_fail_on_unknown_volume_types(self, mock_log):
        """Ensure exception is raised when connector/target do not match."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='foo.address')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='wetcat',
            boot_index=0, volume_id='1234')
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task, 'iscsi_boot', 'True')
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_fails_iscsi_conn_fc_target(self, mock_log):
        """Validate failure of iSCSI connectors with FC target."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='foo.address')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='fibre_channel',
            boot_index=0, volume_id='1234')
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task, 'iscsi_boot', 'True')
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_validate_fails_fc_conn_iscsi_target(self, mock_log):
        """Validate failure of FC connectors with iSCSI target."""
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='fibre_channel',
            connector_id='foo.address')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')
        with task_manager.acquire(self.context, self.node.id) as task:
            driver_utils.add_node_capability(task,
                                             'fibre_channel_boot',
                                             'True')
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder_common, 'attach_volumes', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_attach_detach_volumes_no_volumes(self, mock_log,
                                              mock_attach, mock_detach):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.attach_volumes(task)
            self.interface.detach_volumes(task)

        self.assertFalse(mock_attach.called)
        self.assertFalse(mock_detach.called)
        self.assertFalse(mock_log.called)

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder_common, 'attach_volumes', autospec=True)
    def test_attach_detach_volumes_fails_without_connectors(self,
                                                            mock_attach,
                                                            mock_detach):
        """Without connectors, attach and detach should fail."""
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.StorageError,
                              self.interface.attach_volumes, task)
            self.assertFalse(mock_attach.called)
            self.assertRaises(exception.StorageError,
                              self.interface.detach_volumes, task)
            self.assertFalse(mock_detach.called)

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder_common, 'attach_volumes', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    @mock.patch.object(objects.volume_target.VolumeTarget, 'list_by_volume_id',
                       autospec=True)
    def test_attach_detach_called_with_target_and_connector(self,
                                                            mock_target_list,
                                                            mock_log,
                                                            mock_attach,
                                                            mock_detach):
        target_uuid = uuidutils.generate_uuid()
        test_volume_target = object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=target_uuid)

        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')
        expected_target_properties = {
            'volume_id': '1234',
            'ironic_volume_uuid': target_uuid,
            'new_property': 'foo'}
        mock_attach.return_value = [{
            'driver_volume_type': 'iscsi',
            'data': expected_target_properties}]
        mock_target_list.return_value = [test_volume_target]
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.attach_volumes(task)
            self.assertFalse(mock_log.called)
            self.assertTrue(mock_attach.called)
            task.volume_targets[0].refresh()
            self.assertEqual(expected_target_properties,
                             task.volume_targets[0]['properties'])
            self.interface.detach_volumes(task)
            self.assertFalse(mock_log.called)
            self.assertTrue(mock_detach.called)

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder_common, 'attach_volumes', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_attach_volumes_failure(self, mock_log, mock_attach, mock_detach):
        """Verify detach is called upon attachment failing."""
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='5678', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')

        mock_attach.side_effect = exception.StorageError('foo')

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.StorageError,
                              self.interface.attach_volumes, task)
            self.assertTrue(mock_attach.called)
            self.assertTrue(mock_detach.called)
        # Replacing the mock to not return an error, should still raise an
        # exception.
        mock_attach.reset_mock()
        mock_detach.reset_mock()

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder_common, 'attach_volumes', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_attach_volumes_failure_no_attach_error(self, mock_log,
                                                    mock_attach, mock_detach):
        """Verify that detach is called on volume/connector mismatch.

        Volume attachment fails if the number of attachments completed
        does not match the number of configured targets.
        """
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='5678', uuid=uuidutils.generate_uuid())
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')

        mock_attach.return_value = {'mock_return'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.StorageError,
                              self.interface.attach_volumes, task)
            self.assertTrue(mock_attach.called)
            self.assertTrue(mock_detach.called)

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_detach_volumes_failure(self, mock_log, mock_detach):
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')

        with task_manager.acquire(self.context, self.node.id) as task:
            # The first attempt should succeed.
            # The second attempt should throw StorageError
            # Third attempt, should log errors but not raise an exception.
            mock_detach.side_effect = [None,
                                       exception.StorageError('bar'),
                                       None]
            # This should generate 1 mock_detach call and succeed
            self.interface.detach_volumes(task)

            task.node.provision_state = states.DELETED
            # This should generate the other 2 moc_detach calls and warn
            self.interface.detach_volumes(task)
            self.assertEqual(3, mock_detach.call_count)
            self.assertEqual(1, mock_log.warning.call_count)

    @mock.patch.object(cinder_common, 'detach_volumes', autospec=True)
    @mock.patch.object(cinder, 'LOG', autospec=True)
    def test_detach_volumes_failure_raises_exception(self,
                                                     mock_log,
                                                     mock_detach):
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='iqn.address')

        with task_manager.acquire(self.context, self.node.id) as task:
            mock_detach.side_effect = exception.StorageError('bar')
            self.assertRaises(exception.StorageError,
                              self.interface.detach_volumes,
                              task)
            # Check that we warn every retry except the last one.
            self.assertEqual(3, mock_log.warning.call_count)
            self.assertEqual(1, mock_log.error.call_count)
            # CONF.cinder.action_retries + 1, number of retries is set to 3.
            self.assertEqual(4, mock_detach.call_count)

    def test_should_write_image(self):
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertFalse(self.interface.should_write_image(task))

        self.node.instance_info = {'image_source': 'fake-value'}
        self.node.save()

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertTrue(self.interface.should_write_image(task))
