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
import os
from unittest import mock

from oslo_config import cfg
from oslo_utils import timeutils

from ironic.common import exception
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import fake
from ironic.drivers import utils as driver_utils
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class UtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(UtilsTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_get_node_mac_addresses(self):
        ports = []
        ports.append(
            obj_utils.create_test_port(
                self.context,
                address='aa:bb:cc:dd:ee:ff',
                uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53',
                node_id=self.node.id)
        )
        ports.append(
            obj_utils.create_test_port(
                self.context,
                address='dd:ee:ff:aa:bb:cc',
                uuid='4fc26c0b-03f2-4d2e-ae87-c02d7f33c234',
                node_id=self.node.id)
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            node_macs = driver_utils.get_node_mac_addresses(task)
        self.assertEqual(sorted([p.address for p in ports]), sorted(node_macs))

    def test_get_node_capability(self):
        properties = {'capabilities': 'cap1:value1, cap2: value2'}
        self.node.properties = properties
        expected = 'value1'
        expected2 = 'value2'

        result = driver_utils.get_node_capability(self.node, 'cap1')
        result2 = driver_utils.get_node_capability(self.node, 'cap2')
        self.assertEqual(expected, result)
        self.assertEqual(expected2, result2)

    def test_get_node_capability_returns_none(self):
        properties = {'capabilities': 'cap1:value1,cap2:value2'}
        self.node.properties = properties

        result = driver_utils.get_node_capability(self.node, 'capX')
        self.assertIsNone(result)

    def test_add_node_capability(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = ''
            driver_utils.add_node_capability(task, 'boot_mode', 'bios')
            self.assertEqual('boot_mode:bios',
                             task.node.properties['capabilities'])

    def test_add_node_capability_append(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b,c:d'
            driver_utils.add_node_capability(task, 'boot_mode', 'bios')
            self.assertEqual('a:b,c:d,boot_mode:bios',
                             task.node.properties['capabilities'])

    def test_add_node_capability_append_duplicate(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b,c:d'
            driver_utils.add_node_capability(task, 'a', 'b')
            self.assertEqual('a:b,c:d,a:b',
                             task.node.properties['capabilities'])

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_ensure_next_boot_device(self, node_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['persistent_boot_device'] = 'pxe'
            driver_utils.ensure_next_boot_device(
                task,
                {'force_boot_device': True}
            )
            node_set_boot_device_mock.assert_called_once_with(task, 'pxe')

    def test_ensure_next_boot_device_clears_is_next_boot_persistent(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['persistent_boot_device'] = 'pxe'
            task.node.driver_internal_info['is_next_boot_persistent'] = False
            driver_utils.ensure_next_boot_device(
                task,
                {'force_boot_device': True}
            )
            task.node.refresh()
            self.assertNotIn('is_next_boot_persistent',
                             task.node.driver_internal_info)

    def test_force_persistent_boot_true(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ipmi_force_boot_device'] = True
            ret = driver_utils.force_persistent_boot(task, 'pxe', True)
            self.assertIsNone(ret)
            task.node.refresh()
            self.assertIn(('persistent_boot_device', 'pxe'),
                          task.node.driver_internal_info.items())
            self.assertNotIn('is_next_boot_persistent',
                             task.node.driver_internal_info)

    def test_force_persistent_boot_false(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = driver_utils.force_persistent_boot(task, 'pxe', False)
            self.assertIsNone(ret)
            task.node.refresh()
            self.assertIs(
                False,
                task.node.driver_internal_info['is_next_boot_persistent'])

    def test_capabilities_to_dict(self):
        capabilities_more_than_one_item = 'a:b,c:d'
        capabilities_exactly_one_item = 'e:f'

        # Testing empty capabilities
        self.assertEqual(
            {},
            driver_utils.capabilities_to_dict('')
        )
        self.assertEqual(
            {'e': 'f'},
            driver_utils.capabilities_to_dict(capabilities_exactly_one_item)
        )
        self.assertEqual(
            {'a': 'b', 'c': 'd'},
            driver_utils.capabilities_to_dict(capabilities_more_than_one_item)
        )

    def test_capabilities_to_dict_with_only_key_or_value_fail(self):
        capabilities_only_key_or_value = 'xpto'
        exc = self.assertRaises(
            exception.InvalidParameterValue,
            driver_utils.capabilities_to_dict,
            capabilities_only_key_or_value
        )
        self.assertEqual('Malformed capabilities value: xpto', str(exc))

    def test_capabilities_to_dict_with_invalid_character_fail(self):
        for test_capabilities in ('xpto:a,', ',xpto:a'):
            exc = self.assertRaises(
                exception.InvalidParameterValue,
                driver_utils.capabilities_to_dict,
                test_capabilities
            )
            self.assertEqual('Malformed capabilities value: ', str(exc))

    def test_capabilities_to_dict_with_incorrect_format_fail(self):
        for test_capabilities in (':xpto,', 'xpto:,', ':,'):
            exc = self.assertRaises(
                exception.InvalidParameterValue,
                driver_utils.capabilities_to_dict,
                test_capabilities
            )
            self.assertEqual('Malformed capabilities value: ', str(exc))

    def test_capabilities_not_string(self):
        capabilities_already_dict = {'a': 'b'}
        capabilities_something_else = 42

        exc = self.assertRaises(
            exception.InvalidParameterValue,
            driver_utils.capabilities_to_dict,
            capabilities_already_dict
        )
        self.assertEqual("Value of 'capabilities' must be string. Got "
                         + str(dict), str(exc))

        exc = self.assertRaises(
            exception.InvalidParameterValue,
            driver_utils.capabilities_to_dict,
            capabilities_something_else
        )
        self.assertEqual("Value of 'capabilities' must be string. Got "
                         + str(int), str(exc))

    def test_normalize_mac_string(self):
        mac_raw = "0A:1B-2C-3D:4F"
        mac_clean = driver_utils.normalize_mac(mac_raw)
        self.assertEqual("0a1b2c3d4f", mac_clean)

    def test_normalize_mac_unicode(self):
        mac_raw = u"0A:1B-2C-3D:4F"
        mac_clean = driver_utils.normalize_mac(mac_raw)
        self.assertEqual("0a1b2c3d4f", mac_clean)


class UtilsRamdiskLogsTestCase(tests_base.TestCase):

    def setUp(self):
        super(UtilsRamdiskLogsTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_ramdisk_logs_file_name(self, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime(2000, 1, 1, 0, 0)
        name = driver_utils.get_ramdisk_logs_file_name(self.node)
        expected_name = ('1be26c0b-03f2-4d2e-ae87-c02d7f33c123_'
                         '2000-01-01-00-00-00.tar.gz')
        self.assertEqual(expected_name, name)

        # with instance_info
        instance_uuid = '7a5641ba-d264-424a-a9d7-e2a293ca482b'
        node2 = obj_utils.get_test_node(
            self.context, instance_uuid=instance_uuid)
        name = driver_utils.get_ramdisk_logs_file_name(node2)
        expected_name = ('1be26c0b-03f2-4d2e-ae87-c02d7f33c123_'
                         + instance_uuid + '_2000-01-01-00-00-00.tar.gz')
        self.assertEqual(expected_name, name)

        # with name
        node_name = 'foo'
        node3 = obj_utils.get_test_node(self.context, name=node_name)
        name = driver_utils.get_ramdisk_logs_file_name(node3)
        expected_name = ('1be26c0b-03f2-4d2e-ae87-c02d7f33c123_'
                         + node_name + '_2000-01-01-00-00-00.tar.gz')
        self.assertJsonEqual(expected_name, name)

    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    @mock.patch.object(agent_client.AgentClient,
                       'collect_system_logs', autospec=True)
    def test_collect_ramdisk_logs(self, mock_collect, mock_store):
        logs = 'Gary the Snail'
        mock_collect.return_value = {'command_result': {'system_logs': logs}}
        driver_utils.collect_ramdisk_logs(self.node)
        mock_store.assert_called_once_with(self.node, logs, label=None)

    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    @mock.patch.object(agent_client.AgentClient,
                       'collect_system_logs', autospec=True)
    def test_collect_ramdisk_logs_with_label(self, mock_collect, mock_store):
        logs = 'Gary the Snail'
        mock_collect.return_value = {'command_result': {'system_logs': logs}}
        driver_utils.collect_ramdisk_logs(self.node, label='logs')
        mock_store.assert_called_once_with(self.node, logs, label='logs')

    @mock.patch.object(driver_utils.LOG, 'error', autospec=True)
    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    @mock.patch.object(agent_client.AgentClient,
                       'collect_system_logs', autospec=True)
    def test_collect_ramdisk_logs_IPA_command_fail(
            self, mock_collect, mock_store, mock_log):
        error_str = 'MR. KRABS! I WANNA GO TO BED!'
        mock_collect.return_value = {'faultstring': error_str}
        driver_utils.collect_ramdisk_logs(self.node)
        # assert store was never invoked
        self.assertFalse(mock_store.called)
        mock_log.assert_called_once_with(
            mock.ANY, {'node': self.node.uuid, 'error': error_str})

    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    @mock.patch.object(agent_client.AgentClient,
                       'collect_system_logs', autospec=True)
    def test_collect_ramdisk_logs_storage_command_fail(
            self, mock_collect, mock_store):
        mock_collect.side_effect = exception.IronicException('boom')
        self.assertIsNone(driver_utils.collect_ramdisk_logs(self.node))
        self.assertFalse(mock_store.called)

    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    @mock.patch.object(agent_client.AgentClient,
                       'collect_system_logs', autospec=True)
    def _collect_ramdisk_logs_storage_fail(
            self, expected_exception, mock_collect, mock_store):
        mock_store.side_effect = expected_exception
        logs = 'Gary the Snail'
        mock_collect.return_value = {'command_result': {'system_logs': logs}}
        driver_utils.collect_ramdisk_logs(self.node)
        mock_store.assert_called_once_with(self.node, logs, label=None)

    @mock.patch.object(driver_utils.LOG, 'exception', autospec=True)
    def test_collect_ramdisk_logs_storage_fail_fs(self, mock_log):
        error = IOError('boom')
        self._collect_ramdisk_logs_storage_fail(error)
        mock_log.assert_called_once_with(
            mock.ANY, {'node': self.node.uuid, 'error': error})
        self.assertIn('file-system', mock_log.call_args[0][0])

    @mock.patch.object(driver_utils.LOG, 'error', autospec=True)
    def test_collect_ramdisk_logs_storage_fail_swift(self, mock_log):
        error = exception.SwiftOperationError('boom')
        self._collect_ramdisk_logs_storage_fail(error)
        mock_log.assert_called_once_with(
            mock.ANY, {'node': self.node.uuid, 'error': error})
        self.assertIn('Swift', mock_log.call_args[0][0])

    @mock.patch.object(driver_utils.LOG, 'exception', autospec=True)
    def test_collect_ramdisk_logs_storage_fail_unkown(self, mock_log):
        error = Exception('boom')
        self._collect_ramdisk_logs_storage_fail(error)
        mock_log.assert_called_once_with(
            mock.ANY, {'node': self.node.uuid, 'error': error})
        self.assertIn('Unknown error', mock_log.call_args[0][0])

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    @mock.patch.object(driver_utils,
                       'get_ramdisk_logs_file_name', autospec=True)
    def test_store_ramdisk_logs_swift(self, mock_logs_name, mock_swift):
        container_name = 'ironic_test_container'
        file_name = 'ironic_test_file.tar.gz'
        b64str = 'ZW5jb2RlZHN0cmluZw==\n'

        cfg.CONF.set_override('deploy_logs_storage_backend', 'swift', 'agent')
        cfg.CONF.set_override(
            'deploy_logs_swift_container', container_name, 'agent')
        cfg.CONF.set_override('deploy_logs_swift_days_to_expire', 1, 'agent')

        mock_logs_name.return_value = file_name
        driver_utils.store_ramdisk_logs(self.node, b64str)

        mock_swift.return_value.create_object.assert_called_once_with(
            container_name, file_name, mock.ANY,
            object_headers={'X-Delete-After': '86400'})
        mock_logs_name.assert_called_once_with(self.node, label=None)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(driver_utils,
                       'get_ramdisk_logs_file_name', autospec=True)
    def test_store_ramdisk_logs_local(self, mock_logs_name, mock_makedirs):
        file_name = 'ironic_test_file.tar.gz'
        b64str = 'ZW5jb2RlZHN0cmluZw==\n'
        log_path = '/foo/bar'

        cfg.CONF.set_override('deploy_logs_local_path', log_path, 'agent')
        mock_logs_name.return_value = file_name

        with mock.patch.object(driver_utils, 'open', new=mock.mock_open(),
                               create=True) as mock_open:
            driver_utils.store_ramdisk_logs(self.node, b64str)

            expected_path = os.path.join(log_path, file_name)
            mock_open.assert_called_once_with(expected_path, 'wb')

        mock_makedirs.assert_called_once_with(log_path)
        mock_logs_name.assert_called_once_with(self.node, label=None)


class MixinVendorInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(MixinVendorInterfaceTestCase, self).setUp()
        self.a = fake.FakeVendorA()
        self.b = fake.FakeVendorB()
        self.mapping = {'first_method': self.a,
                        'second_method': self.b,
                        'third_method_sync': self.b,
                        'fourth_method_shared_lock': self.b}
        self.vendor = driver_utils.MixinVendorInterface(self.mapping)
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')

    def test_vendor_interface_get_properties(self):
        expected = {'A1': 'A1 description. Required.',
                    'A2': 'A2 description. Optional.',
                    'B1': 'B1 description. Required.',
                    'B2': 'B2 description. Required.'}
        props = self.vendor.get_properties()
        self.assertEqual(expected, props)

    @mock.patch.object(fake.FakeVendorA, 'validate', autospec=True)
    def test_vendor_interface_validate_valid_methods(self,
                                                     mock_fakea_validate):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.vendor.validate(task, method='first_method')
            mock_fakea_validate.assert_called_once_with(
                self.vendor.mapping['first_method'],
                task, method='first_method')

    def test_vendor_interface_validate_bad_method(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.vendor.validate,
                              task, method='fake_method')
