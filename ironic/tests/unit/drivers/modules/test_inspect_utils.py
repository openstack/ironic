# Copyright 2018 Red Hat, Inc.
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

import socket
from unittest import mock

from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import context as ironic_context
from ironic.common import exception
from ironic.common import states
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules import inspect_utils as utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')


@mock.patch('time.sleep', lambda sec: None)
class InspectFunctionTestCase(db_base.DbTestCase):

    def setUp(self):
        super(InspectFunctionTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               boot_interface='pxe')

    @mock.patch.object(utils.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch.object(objects, 'Port', spec_set=True, autospec=True)
    def test_create_ports_if_not_exist(self, port_mock, log_mock):
        macs = {'aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb'}
        node_id = self.node.id
        port_dict1 = {'address': 'aa:aa:aa:aa:aa:aa', 'node_id': node_id}
        port_dict2 = {'address': 'bb:bb:bb:bb:bb:bb', 'node_id': node_id}
        port_obj1, port_obj2 = mock.MagicMock(), mock.MagicMock()
        port_mock.side_effect = [port_obj1, port_obj2]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.create_ports_if_not_exist(task, macs)
            self.assertTrue(log_mock.called)
            expected_calls = [mock.call(task.context, **port_dict1),
                              mock.call(task.context, **port_dict2)]
            port_mock.assert_has_calls(expected_calls, any_order=True)
            port_obj1.create.assert_called_once_with()
            port_obj2.create.assert_called_once_with()

    @mock.patch.object(utils.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(utils.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_create_ports_if_not_exist_mac_exception(self,
                                                     create_mock,
                                                     log_mock,
                                                     warn_mock):
        create_mock.side_effect = exception.MACAlreadyExists('f')
        macs = {'aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb',
                'aa:aa:aa:aa:aa:aa:bb:bb'}  # WWN
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.create_ports_if_not_exist(task, macs)
        self.assertEqual(2, log_mock.call_count)
        self.assertEqual(2, create_mock.call_count)
        self.assertEqual(1, warn_mock.call_count)

    @mock.patch.object(utils.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch.object(objects, 'Port', spec_set=True, autospec=True)
    def test_create_ports_if_not_exist_attempts_port_creation_blindly(
            self, port_mock, log_info_mock):
        macs = {'aa:bb:cc:dd:ee:ff', 'aa:bb:aa:aa:aa:aa'}
        node_id = self.node.id
        port_dict1 = {'address': 'aa:bb:cc:dd:ee:ff', 'node_id': node_id}
        port_dict2 = {'address': 'aa:bb:aa:aa:aa:aa', 'node_id': node_id}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.create_ports_if_not_exist(task, macs)
            self.assertTrue(log_info_mock.called)
            expected_calls = [mock.call(task.context, **port_dict1),
                              mock.call(task.context, **port_dict2)]
            port_mock.assert_has_calls(expected_calls, any_order=True)
            self.assertEqual(2, port_mock.return_value.create.call_count)


class SwiftCleanUp(db_base.DbTestCase):

    def setUp(self):
        super(SwiftCleanUp, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_clean_up_swift_entries(self, swift_api_mock):
        CONF.set_override('data_backend', 'swift', group='inventory')
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.clean_up_swift_entries(task)
            object_name = 'inspector_data-' + str(self.node.uuid)
            swift_obj_mock.delete_object.assert_has_calls([
                mock.call(object_name + '-inventory', container),
                mock.call(object_name + '-plugin', container)])

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_clean_up_swift_entries_with_404_exception(self, swift_api_mock):
        CONF.set_override('data_backend', 'swift', group='inventory')
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            swift_obj_mock.delete_object.side_effect = [
                exception.SwiftObjectNotFoundError("not found"),
                exception.SwiftObjectNotFoundError("not found")]
            utils.clean_up_swift_entries(task)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_clean_up_swift_entries_with_fail_exception(self, swift_api_mock):
        CONF.set_override('data_backend', 'swift', group='inventory')
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            swift_obj_mock.delete_object.side_effect = [
                exception.SwiftOperationError("failed"),
                exception.SwiftObjectNotFoundError("not found")]
            self.assertRaises(exception.SwiftObjectStillExists,
                              utils.clean_up_swift_entries, task)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test_clean_up_swift_entries_with_fail_exceptions(self, swift_api_mock):
        CONF.set_override('data_backend', 'swift', group='inventory')
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            swift_obj_mock.delete_object.side_effect = [
                exception.SwiftOperationError("failed"),
                exception.SwiftOperationError("failed")]
            self.assertRaises((exception.SwiftObjectStillExists,
                               exception.SwiftObjectStillExists),
                              utils.clean_up_swift_entries, task)


class IntrospectionDataStorageFunctionsTestCase(db_base.DbTestCase):
    fake_inventory_data = {"cpu": "amd"}
    fake_plugin_data = {"disks": [{"name": "/dev/vda"}]}

    def setUp(self):
        super(IntrospectionDataStorageFunctionsTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_store_inspection_data_db(self):
        CONF.set_override('data_backend', 'database', group='inventory')
        fake_context = ironic_context.RequestContext()
        utils.store_inspection_data(self.node, self.fake_inventory_data,
                                    self.fake_plugin_data, fake_context)
        stored = objects.NodeInventory.get_by_node_id(self.context,
                                                      self.node.id)
        self.assertEqual(self.fake_inventory_data, stored["inventory_data"])
        self.assertEqual(self.fake_plugin_data, stored["plugin_data"])

    @mock.patch.object(utils, '_store_inspection_data_in_swift',
                       autospec=True)
    def test_store_inspection_data_swift(self, mock_store_data):
        CONF.set_override('data_backend', 'swift', group='inventory')
        CONF.set_override(
            'swift_data_container', 'inspection_data',
            group='inventory')
        fake_context = ironic_context.RequestContext()
        utils.store_inspection_data(self.node, self.fake_inventory_data,
                                    self.fake_plugin_data, fake_context)
        mock_store_data.assert_called_once_with(
            self.node.uuid, inventory_data=self.fake_inventory_data,
            plugin_data=self.fake_plugin_data)

    def test_store_inspection_data_nostore(self):
        CONF.set_override('data_backend', 'none', group='inventory')
        fake_context = ironic_context.RequestContext()
        utils.store_inspection_data(self.node, self.fake_inventory_data,
                                    self.fake_plugin_data, fake_context)
        self.assertRaises(exception.NodeInventoryNotFound,
                          objects.NodeInventory.get_by_node_id,
                          self.context, self.node.id)

    def test_get_inspection_data_db(self):
        CONF.set_override('data_backend', 'database', group='inventory')
        obj_utils.create_test_inventory(
            self.context, self.node,
            inventory_data=self.fake_inventory_data,
            plugin_data=self.fake_plugin_data)
        fake_context = ironic_context.RequestContext()
        ret = utils.get_inspection_data(self.node, fake_context)
        fake_inspection_data = {'inventory': self.fake_inventory_data,
                                'plugin_data': self.fake_plugin_data}
        self.assertEqual(ret, fake_inspection_data)

    def test_get_inspection_data_db_exception(self):
        CONF.set_override('data_backend', 'database', group='inventory')
        fake_context = ironic_context.RequestContext()
        self.assertRaises(
            exception.NodeInventoryNotFound, utils.get_inspection_data,
            self.node, fake_context)

    @mock.patch.object(utils, '_get_inspection_data_from_swift', autospec=True)
    def test_get_inspection_data_swift(self, mock_get_data):
        CONF.set_override('data_backend', 'swift', group='inventory')
        CONF.set_override(
            'swift_data_container', 'inspection_data',
            group='inventory')
        fake_context = ironic_context.RequestContext()
        ret = utils.get_inspection_data(self.node, fake_context)
        mock_get_data.assert_called_once_with(self.node.uuid)
        self.assertEqual(mock_get_data.return_value, ret)

    @mock.patch.object(utils, '_get_inspection_data_from_swift', autospec=True)
    def test_get_inspection_data_swift_exception(self, mock_get_data):
        CONF.set_override('data_backend', 'swift', group='inventory')
        CONF.set_override(
            'swift_data_container', 'inspection_data',
            group='inventory')
        fake_context = ironic_context.RequestContext()
        mock_get_data.side_effect = exception.SwiftObjectNotFoundError()
        self.assertRaises(
            exception.NodeInventoryNotFound, utils.get_inspection_data,
            self.node, fake_context)

    def test_get_inspection_data_nostore(self):
        CONF.set_override('data_backend', 'none', group='inventory')
        fake_context = ironic_context.RequestContext()
        self.assertRaises(
            exception.NodeInventoryNotFound, utils.get_inspection_data,
            self.node, fake_context)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test__store_inspection_data_in_swift(self, swift_api_mock):
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        utils._store_inspection_data_in_swift(
            self.node.uuid, self.fake_inventory_data, self.fake_plugin_data)
        swift_obj_mock = swift_api_mock.return_value
        object_name = 'inspector_data-' + str(self.node.uuid)
        swift_obj_mock.create_object_from_data.assert_has_calls([
            mock.call(object_name + '-inventory', self.fake_inventory_data,
                      container),
            mock.call(object_name + '-plugin', self.fake_plugin_data,
                      container)])

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test__get_inspection_data_from_swift(self, swift_api_mock):
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        swift_obj_mock.get_object.side_effect = [
            self.fake_inventory_data,
            self.fake_plugin_data
        ]
        ret = utils._get_inspection_data_from_swift(self.node.uuid)
        req_ret = {"inventory": self.fake_inventory_data,
                   "plugin_data": self.fake_plugin_data}
        self.assertEqual(req_ret, ret)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test__get_inspection_data_from_swift_exception(self, swift_api_mock):
        container = 'inspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        swift_obj_mock.get_object.side_effect = [
            exception.SwiftOperationError,
            self.fake_plugin_data
        ]
        self.assertRaises(exception.SwiftObjectNotFoundError,
                          utils._get_inspection_data_from_swift,
                          self.node.uuid)


class LookupNodeTestCase(db_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.bmc = '192.0.2.1'
        self.node = obj_utils.create_test_node(
            self.context,
            driver_internal_info={utils.LOOKUP_CACHE_FIELD: [self.bmc]},
            provision_state=states.INSPECTWAIT)

        self.macs = ['11:22:33:44:55:66', '12:34:56:78:90:ab']
        self.unknown_mac = '66:55:44:33:22:11'
        self.ports = [
            obj_utils.create_test_port(self.context,
                                       uuid=uuidutils.generate_uuid(),
                                       node_id=self.node.id,
                                       address=addr)
            for addr in self.macs
        ]

        self.bmc2 = '1.2.1.2'
        self.mac2 = '00:11:00:11:00:11'
        self.node2 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver_internal_info={utils.LOOKUP_CACHE_FIELD: [self.bmc2]},
            provision_state=states.INSPECTWAIT)
        obj_utils.create_test_port(self.context,
                                   node_id=self.node2.id,
                                   address=self.mac2)

    def test_no_input(self):
        self.assertRaises(exception.BadRequest, utils.lookup_node,
                          self.context, [], [], None)

    def test_by_macs(self):
        result = utils.lookup_node(self.context, self.macs[::-1], [], None)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_macs_partial(self):
        macs = [self.macs[1], self.unknown_mac]
        result = utils.lookup_node(self.context, macs, [], None)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_mac_not_found(self):
        self.assertRaises(utils.AutoEnrollPossible, utils.lookup_node,
                          self.context, [self.unknown_mac], [], None)

    def test_by_mac_wrong_state(self):
        self.node.provision_state = states.AVAILABLE
        self.node.save()
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, self.macs, [], None)

    def test_conflicting_macs(self):
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, [self.macs[0], self.mac2], [], None)

    def test_by_bmc(self):
        result = utils.lookup_node(self.context, [], ['192.0.2.1'], None)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_bmc_and_mac(self):
        result = utils.lookup_node(
            self.context, [self.macs[0]], [self.bmc], None)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_unknown_bmc_and_mac(self):
        result = utils.lookup_node(
            self.context, [self.unknown_mac], [self.bmc], None)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_bmc_and_mac_and_uuid(self):
        result = utils.lookup_node(
            self.context, [self.macs[0]], [self.bmc], self.node.uuid)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_bmc_not_found(self):
        self.assertRaises(utils.AutoEnrollPossible, utils.lookup_node,
                          self.context, [], ['192.168.1.1'], None)

    def test_by_bmc_and_mac_not_found(self):
        self.assertRaises(utils.AutoEnrollPossible, utils.lookup_node,
                          self.context, [self.unknown_mac],
                          ['192.168.1.1'], None)

    def test_by_bmc_wrong_state(self):
        self.node.provision_state = states.AVAILABLE
        self.node.save()
        # Limitation of auto-discovery: cannot de-duplicate nodes by BMC
        # addresses only. Should not happen too often in reality.
        # If it does happen, auto-discovery will create a duplicate node.
        self.assertRaises(utils.AutoEnrollPossible, utils.lookup_node,
                          self.context, [], [self.bmc], None)

    def test_conflicting_macs_and_bmc(self):
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, self.macs, [self.bmc2], None)

    def test_duplicate_bmc(self):
        # This can happen with Redfish. There is no way to resolve the conflict
        # other than by using MACs.
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver_internal_info={utils.LOOKUP_CACHE_FIELD: [self.bmc]},
            provision_state=states.INSPECTWAIT)
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, [], [self.bmc], None)

    def test_duplicate_bmc_and_unknown_mac(self):
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver_internal_info={utils.LOOKUP_CACHE_FIELD: [self.bmc]},
            provision_state=states.INSPECTWAIT)
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, [self.unknown_mac], [self.bmc], None)

    def test_duplicate_bmc_resolved_by_macs(self):
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver_internal_info={utils.LOOKUP_CACHE_FIELD: [self.bmc]},
            provision_state=states.INSPECTWAIT)
        result = utils.lookup_node(
            self.context, [self.macs[0]], [self.bmc], None)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_uuid(self):
        result = utils.lookup_node(self.context, [], [], self.node.uuid)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_uuid_and_unknown_macs(self):
        result = utils.lookup_node(
            self.context, [self.unknown_mac], [], self.node.uuid)
        self.assertEqual(self.node.uuid, result.uuid)

    def test_by_uuid_not_found(self):
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, [], [], uuidutils.generate_uuid())

    def test_by_uuid_wrong_state(self):
        self.node.provision_state = states.AVAILABLE
        self.node.save()
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, [], [], self.node.uuid)

    def test_conflicting_macs_and_uuid(self):
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, self.macs, [], self.node2.uuid)

    def test_conflicting_bmc_and_uuid(self):
        self.assertRaises(exception.NotFound, utils.lookup_node,
                          self.context, self.macs, [self.bmc], self.node2.uuid)


class GetBMCAddressesTestCase(db_base.DbTestCase):

    def test_localhost_ignored(self):
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'ipmi_address': '127.0.0.1'})
        self.assertEqual(set(), utils._get_bmc_addresses(node))

    def test_localhost_as_url_ignored(self):
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'redfish_address': 'https://localhost/redfish'})
        self.assertEqual(set(), utils._get_bmc_addresses(node))

    def test_normal_ip(self):
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'ipmi_address': '192.0.2.1'})
        self.assertEqual({'192.0.2.1'}, utils._get_bmc_addresses(node))

    def test_normal_ip_as_url(self):
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'redfish_address': 'https://192.0.2.1/redfish'})
        self.assertEqual({'192.0.2.1'}, utils._get_bmc_addresses(node))

    def test_normal_ipv6_as_url(self):
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'redfish_address': 'https://[2001:db8::42]/redfish'})
        self.assertEqual({'2001:db8::42'}, utils._get_bmc_addresses(node))

    @mock.patch.object(socket, 'getaddrinfo', autospec=True)
    def test_resolved_host(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, socket.SOL_TCP,
             '', ('2001:db8::42', None)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.SOL_TCP,
             '', ('192.0.2.1', None)),
        ]
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'ipmi_address': 'example.com'})
        self.assertEqual({'example.com', '192.0.2.1', '2001:db8::42'},
                         utils._get_bmc_addresses(node))
        mock_getaddrinfo.assert_called_once_with(
            'example.com', None, proto=socket.SOL_TCP)

    @mock.patch.object(socket, 'getaddrinfo', autospec=True)
    def test_resolved_host_in_url(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, socket.SOL_TCP,
             '', ('2001:db8::42', None)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.SOL_TCP,
             '', ('192.0.2.1', None)),
        ]
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'redfish_address': 'https://example.com:8080/v1'})
        self.assertEqual({'example.com', '192.0.2.1', '2001:db8::42'},
                         utils._get_bmc_addresses(node))
        mock_getaddrinfo.assert_called_once_with(
            'example.com', None, proto=socket.SOL_TCP)

    def test_redfish_bmc_address_ipv6_brackets_no_scheme(self):
        node = obj_utils.create_test_node(
            self.context,
            driver_info={'redfish_address': '[2001:db8::42]'})
        self.assertEqual({'2001:db8::42'}, utils._get_bmc_addresses(node))


class LookupCacheTestCase(db_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.bmc = '192.0.2.1'
        self.node = obj_utils.create_test_node(
            self.context,
            driver_internal_info={utils.LOOKUP_CACHE_FIELD: [self.bmc]},
            provision_state=states.INSPECTWAIT)

    def test_clear(self):
        result = utils.clear_lookup_addresses(self.node)
        self.assertEqual([self.bmc], result)
        self.assertEqual({}, self.node.driver_internal_info)

    @mock.patch.object(utils, '_get_bmc_addresses', autospec=True)
    def test_new_value(self, mock_get_addr):
        mock_get_addr.return_value = {'192.0.2.42'}
        utils.cache_lookup_addresses(self.node)
        self.assertEqual({utils.LOOKUP_CACHE_FIELD: ['192.0.2.42']},
                         self.node.driver_internal_info)

    @mock.patch.object(utils, '_get_bmc_addresses', autospec=True)
    def test_replace_with_empty(self, mock_get_addr):
        mock_get_addr.return_value = set()
        utils.cache_lookup_addresses(self.node)
        self.assertEqual({}, self.node.driver_internal_info)
