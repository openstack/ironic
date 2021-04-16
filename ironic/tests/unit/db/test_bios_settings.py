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

"""Tests for manipulating BIOSSetting via the DB API"""

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbBIOSSettingTestCase(base.DbTestCase):

    def setUp(self):
        super(DbBIOSSettingTestCase, self).setUp()
        self.node = db_utils.create_test_node()

    def test_get_bios_setting(self):
        db_utils.create_test_bios_setting(node_id=self.node.id)
        result = self.dbapi.get_bios_setting(self.node.id, 'virtualization')
        self.assertEqual(result['node_id'], self.node.id)
        self.assertEqual(result['name'], 'virtualization')
        self.assertEqual(result['value'], 'on')
        self.assertEqual(result['version'], '1.1')

    def test_get_bios_setting_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_bios_setting,
                          '456',
                          'virtualization')

    def test_get_bios_setting_setting_not_exist(self):
        db_utils.create_test_bios_setting(node_id=self.node.id)
        self.assertRaises(exception.BIOSSettingNotFound,
                          self.dbapi.get_bios_setting,
                          self.node.id, 'bios_name')

    def test_get_bios_setting_list(self):
        db_utils.create_test_bios_setting(node_id=self.node.id)
        result = self.dbapi.get_bios_setting_list(
            node_id=self.node.id)
        self.assertEqual(result[0]['node_id'], self.node.id)
        self.assertEqual(result[0]['name'], 'virtualization')
        self.assertEqual(result[0]['value'], 'on')
        self.assertEqual(result[0]['version'], '1.1')
        self.assertEqual(len(result), 1)

    def test_get_bios_setting_list_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_bios_setting_list,
                          '456')

    def test_create_bios_setting_list(self):
        settings = db_utils.get_test_bios_setting_setting_list()
        result = self.dbapi.create_bios_setting_list(
            self.node.id, settings, '1.1')
        self.assertCountEqual(['virtualization', 'hyperthread', 'numlock'],
                              [setting.name for setting in result])
        self.assertCountEqual(['on', 'enabled', 'off'],
                              [setting.value for setting in result])

    def test_create_bios_setting_list_duplicate(self):
        settings = db_utils.get_test_bios_setting_setting_list()
        self.dbapi.create_bios_setting_list(self.node.id, settings, '1.1')
        self.assertRaises(exception.BIOSSettingAlreadyExists,
                          self.dbapi.create_bios_setting_list,
                          self.node.id, settings, '1.0')

    def test_create_bios_setting_list_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.create_bios_setting_list,
                          '456', [], '1.0')

    def test_update_bios_setting_list(self):
        settings = db_utils.get_test_bios_setting_setting_list()
        self.dbapi.create_bios_setting_list(self.node.id, settings, '1.1')
        settings = [{'name': 'virtualization', 'value': 'off'},
                    {'name': 'hyperthread', 'value': 'disabled'},
                    {'name': 'numlock', 'value': 'on'}]
        result = self.dbapi.update_bios_setting_list(
            self.node.id, settings, '1.1')
        self.assertCountEqual(['off', 'disabled', 'on'],
                              [setting.value for setting in result])

    def test_update_bios_setting_list_setting_not_exist(self):
        settings = db_utils.get_test_bios_setting_setting_list()
        self.dbapi.create_bios_setting_list(self.node.id, settings, '1.1')
        for setting in settings:
            setting['name'] = 'bios_name'
        self.assertRaises(exception.BIOSSettingNotFound,
                          self.dbapi.update_bios_setting_list,
                          self.node.id, settings, '1.0')

    def test_update_bios_setting_list_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.update_bios_setting_list,
                          '456', [], '1.0')

    def test_delete_bios_setting_list(self):
        settings = db_utils.get_test_bios_setting_setting_list()
        self.dbapi.create_bios_setting_list(self.node.id, settings, '1.1')
        name_list = [setting['name'] for setting in settings]
        self.dbapi.delete_bios_setting_list(self.node.id, name_list)
        self.assertRaises(exception.BIOSSettingNotFound,
                          self.dbapi.get_bios_setting,
                          self.node.id, 'virtualization')
        self.assertRaises(exception.BIOSSettingNotFound,
                          self.dbapi.get_bios_setting,
                          self.node.id, 'hyperthread')
        self.assertRaises(exception.BIOSSettingNotFound,
                          self.dbapi.get_bios_setting,
                          self.node.id, 'numlock')

    def test_delete_bios_setting_list_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.delete_bios_setting_list,
                          '456', ['virtualization'])

    def test_delete_bios_setting_list_setting_not_exist(self):
        settings = db_utils.get_test_bios_setting_setting_list()
        self.dbapi.create_bios_setting_list(self.node.id, settings, '1.1')
        self.assertRaises(exception.BIOSSettingListNotFound,
                          self.dbapi.delete_bios_setting_list,
                          self.node.id, ['fake-bios-option'])
