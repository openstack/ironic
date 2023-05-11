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

"""Tests for manipulating FirmwareComponent via the DB API"""

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbFirmwareComponentTestCase(base.DbTestCase):

    def setUp(self):
        super(DbFirmwareComponentTestCase, self).setUp()
        self.node = db_utils.create_test_node()

    def test_create_firmware_component(self):
        values = {'node_id': self.node.id}
        fw_cmp = db_utils.create_test_firmware_component(**values)
        self.assertCountEqual('bmc', fw_cmp.component)
        self.assertCountEqual('v1.0.0', fw_cmp.initial_version)

    def test_create_firmware_component_duplicate(self):
        component = db_utils.get_test_firmware_component_list()[0]
        component['node_id'] = self.node.id
        self.dbapi.create_firmware_component(component)
        self.assertRaises(exception.FirmwareComponentAlreadyExists,
                          self.dbapi.create_firmware_component,
                          component)

    def test_get_firmware_component(self):
        values = {'node_id': self.node.id}
        db_utils.create_test_firmware_component(**values)
        result = self.dbapi.get_firmware_component(self.node.id, 'bmc')
        self.assertEqual(result.node_id, self.node.id)
        self.assertEqual(result.component, 'bmc')
        self.assertEqual(result.initial_version, 'v1.0.0')

    def test_get_firmware_component_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_firmware_component,
                          456, 'BIOS')

    def test_get_firmware_component_setting_not_exist(self):
        db_utils.create_test_firmware_component(node_id=self.node.id)
        self.assertRaises(exception.FirmwareComponentNotFound,
                          self.dbapi.get_firmware_component,
                          self.node.id, 'bios_name')

    def test_get_firmware_component_list(self):
        db_utils.create_test_firmware_component(node_id=self.node.id)
        result = self.dbapi.get_firmware_component_list(
            node_id=self.node.id)
        self.assertEqual(result[0]['node_id'], self.node.id)
        self.assertEqual(result[0]['component'], 'bmc')
        self.assertEqual(result[0]['initial_version'], 'v1.0.0')
        self.assertEqual(result[0]['version'], '1.0')
        self.assertEqual(len(result), 1)

    def test_get_firmware_component_list_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_firmware_component_list,
                          4040)

    def test_update_firmware_components(self):
        components = db_utils.get_test_firmware_component_list()
        components[0].update({'node_id': self.node.id})
        components[1].update({'node_id': self.node.id})
        self.dbapi.create_firmware_component(components[0])
        self.dbapi.create_firmware_component(components[1])
        update_components = [
            {'component': 'bmc', 'initial_version': 'v1.0.0',
             'current_version': 'v1.3.0', 'last_version_flashed': 'v1.3.0'},
            {'component': 'BIOS', 'initial_version': 'v1.5.0',
             'current_version': 'v1.5.5', 'last_version_flashed': 'v1.5.5'}
        ]
        bmc_values = update_components[0]
        bios_values = update_components[1]
        bmc = self.dbapi.update_firmware_component(
            self.node.id, bmc_values['component'], bmc_values)
        bios = self.dbapi.update_firmware_component(
            self.node.id, bios_values['component'], bios_values)
        self.assertCountEqual('v1.3.0', bmc.current_version)
        self.assertCountEqual('v1.5.5', bios.current_version)

    def test_update_firmware_component_not_exist(self):
        values = db_utils.get_test_firmware_component_list()[0]
        values['node_id'] = self.node.id
        db_utils.create_test_firmware_component(**values)
        values['component'] = 'nic'
        self.assertRaises(exception.FirmwareComponentNotFound,
                          self.dbapi.update_firmware_component,
                          self.node.id, 'nic', values)

    def test_delete_firmware_component_list(self):
        values = db_utils.get_test_firmware_component_list()[0]
        values['node_id'] = self.node.id
        self.assertRaises(exception.FirmwareComponentNotFound,
                          self.dbapi.get_firmware_component,
                          self.node.id, 'bmc')
        self.dbapi.create_firmware_component(values)

        self.dbapi.destroy_node(self.node.id)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_firmware_component,
                          self.node.id, 'bmc')
