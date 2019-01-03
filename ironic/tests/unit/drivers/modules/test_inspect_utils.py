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


import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
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
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
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

    @mock.patch.object(utils.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_create_ports_if_not_exist_mac_exception(self,
                                                     create_mock,
                                                     log_mock):
        create_mock.side_effect = exception.MACAlreadyExists('f')
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.create_ports_if_not_exist(task, macs)
        self.assertEqual(2, log_mock.call_count)

    @mock.patch.object(utils.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch.object(objects, 'Port', spec_set=True, autospec=True)
    def test_create_ports_if_not_exist_attempts_port_creation_blindly(
            self, port_mock, log_info_mock):
        macs = {'aa:bb:cc:dd:ee:ff': sushy.STATE_ENABLED,
                'aa:bb:aa:aa:aa:aa': sushy.STATE_DISABLED}
        node_id = self.node.id
        port_dict1 = {'address': 'aa:bb:cc:dd:ee:ff', 'node_id': node_id}
        port_dict2 = {'address': 'aa:bb:aa:aa:aa:aa', 'node_id': node_id}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.create_ports_if_not_exist(
                task, macs, get_mac_address=lambda x: x[0])
            self.assertTrue(log_info_mock.called)
            expected_calls = [mock.call(task.context, **port_dict1),
                              mock.call(task.context, **port_dict2)]
            port_mock.assert_has_calls(expected_calls, any_order=True)
            self.assertEqual(2, port_mock.return_value.create.call_count)
