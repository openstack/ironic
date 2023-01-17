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


from unittest import mock

from oslo_utils import importutils

from ironic.common import context as ironic_context
from ironic.common import exception
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.drivers.modules import inspect_utils as utils
from ironic.drivers.modules import inspector
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')
CONF = inspector.CONF


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


class IntrospectionDataStorageFunctionsTestCase(db_base.DbTestCase):
    fake_inventory_data = {"cpu": "amd"}
    fake_plugin_data = {"disks": [{"name": "/dev/vda"}]}

    def setUp(self):
        super(IntrospectionDataStorageFunctionsTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_store_introspection_data_db(self):
        CONF.set_override('data_backend', 'database',
                          group='inventory')
        fake_introspection_data = {'inventory': self.fake_inventory_data,
                                   **self.fake_plugin_data}
        fake_context = ironic_context.RequestContext()
        utils.store_introspection_data(self.node, fake_introspection_data,
                                       fake_context)
        stored = objects.NodeInventory.get_by_node_id(self.context,
                                                      self.node.id)
        self.assertEqual(self.fake_inventory_data, stored["inventory_data"])
        self.assertEqual(self.fake_plugin_data, stored["plugin_data"])

    @mock.patch.object(utils, '_store_introspection_data_in_swift',
                       autospec=True)
    def test_store_introspection_data_swift(self, mock_store_data):
        CONF.set_override('data_backend', 'swift', group='inventory')
        CONF.set_override(
            'swift_data_container', 'introspection_data',
            group='inventory')
        fake_introspection_data = {
            "inventory": self.fake_inventory_data, **self.fake_plugin_data}
        fake_context = ironic_context.RequestContext()
        utils.store_introspection_data(self.node, fake_introspection_data,
                                       fake_context)
        mock_store_data.assert_called_once_with(
            self.node.uuid, inventory_data=self.fake_inventory_data,
            plugin_data=self.fake_plugin_data)

    def test_store_introspection_data_nostore(self):
        CONF.set_override('data_backend', 'none', group='inventory')
        fake_introspection_data = {
            "inventory": self.fake_inventory_data, **self.fake_plugin_data}
        fake_context = ironic_context.RequestContext()
        ret = utils.store_introspection_data(self.node,
                                             fake_introspection_data,
                                             fake_context)
        self.assertIsNone(ret)

    def test__node_inventory_convert(self):
        required_output = {"inventory": self.fake_inventory_data,
                           "plugin_data": self.fake_plugin_data}
        input_given = {}
        input_given["inventory_data"] = self.fake_inventory_data
        input_given["plugin_data"] = self.fake_plugin_data
        input_given["booom"] = "boom"
        ret = utils._node_inventory_convert(input_given)
        self.assertEqual(required_output, ret)

    @mock.patch.object(utils, '_node_inventory_convert', autospec=True)
    @mock.patch.object(objects, 'NodeInventory', spec_set=True, autospec=True)
    def test_get_introspection_data_db(self, mock_inventory, mock_convert):
        CONF.set_override('data_backend', 'database',
                          group='inventory')
        fake_introspection_data = {'inventory': self.fake_inventory_data,
                                   'plugin_data': self.fake_plugin_data}
        fake_context = ironic_context.RequestContext()
        mock_inventory.get_by_node_id.return_value = fake_introspection_data
        utils.get_introspection_data(self.node, fake_context)
        mock_convert.assert_called_once_with(fake_introspection_data)

    @mock.patch.object(utils, '_get_introspection_data_from_swift',
                       autospec=True)
    def test_get_introspection_data_swift(self, mock_get_data):
        CONF.set_override('data_backend', 'swift', group='inventory')
        CONF.set_override(
            'swift_data_container', 'introspection_data',
            group='inventory')
        fake_context = ironic_context.RequestContext()
        utils.get_introspection_data(self.node, fake_context)
        mock_get_data.assert_called_once_with(
            self.node.uuid)

    def test_get_introspection_data_nostore(self):
        CONF.set_override('data_backend', 'none', group='inventory')
        fake_context = ironic_context.RequestContext()
        self.assertRaises(
            exception.NotFound, utils.get_introspection_data,
            self.node, fake_context)

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test__store_introspection_data_in_swift(self, swift_api_mock):
        container = 'introspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        utils._store_introspection_data_in_swift(
            self.node.uuid, self.fake_inventory_data, self.fake_plugin_data)
        swift_obj_mock = swift_api_mock.return_value
        object_name = 'inspector_data-' + str(self.node.uuid)
        swift_obj_mock.create_object_from_data.assert_has_calls([
            mock.call(object_name + '-inventory', self.fake_inventory_data,
                      container),
            mock.call(object_name + '-plugin', self.fake_plugin_data,
                      container)])

    @mock.patch.object(swift, 'SwiftAPI', autospec=True)
    def test__get_introspection_data_from_swift(self, swift_api_mock):
        container = 'introspection_data'
        CONF.set_override('swift_data_container', container, group='inventory')
        swift_obj_mock = swift_api_mock.return_value
        swift_obj_mock.get_object.side_effect = [
            self.fake_inventory_data,
            self.fake_plugin_data
        ]
        ret = utils._get_introspection_data_from_swift(self.node.uuid)
        req_ret = {"inventory": self.fake_inventory_data,
                   "plugin_data": self.fake_plugin_data}
        self.assertEqual(req_ret, ret)
