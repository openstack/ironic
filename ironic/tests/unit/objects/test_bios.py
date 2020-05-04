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

import types
from unittest import mock

from ironic.common import context
from ironic.db import api as dbapi
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestBIOSSettingObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestBIOSSettingObject, self).setUp()
        self.ctxt = context.get_admin_context()
        self.bios_setting = db_utils.get_test_bios_setting()
        self.node_id = self.bios_setting['node_id']

    @mock.patch.object(dbapi.IMPL, 'get_bios_setting', autospec=True)
    def test_get(self, mock_get_setting):
        mock_get_setting.return_value = self.bios_setting

        bios_obj = objects.BIOSSetting.get(self.context, self.node_id,
                                           self.bios_setting['name'])

        mock_get_setting.assert_called_once_with(self.node_id,
                                                 self.bios_setting['name'])
        self.assertEqual(self.context, bios_obj._context)
        self.assertEqual(self.bios_setting['node_id'], bios_obj.node_id)
        self.assertEqual(self.bios_setting['name'], bios_obj.name)
        self.assertEqual(self.bios_setting['value'], bios_obj.value)

    @mock.patch.object(dbapi.IMPL, 'get_bios_setting_list', autospec=True)
    def test_get_by_node_id(self, mock_get_setting_list):
        bios_setting2 = db_utils.get_test_bios_setting(name='hyperthread',
                                                       value='enabled')
        mock_get_setting_list.return_value = [self.bios_setting, bios_setting2]
        bios_obj_list = objects.BIOSSettingList.get_by_node_id(
            self.context, self.node_id)

        mock_get_setting_list.assert_called_once_with(self.node_id)
        self.assertEqual(self.context, bios_obj_list._context)
        self.assertEqual(2, len(bios_obj_list))
        self.assertEqual(self.bios_setting['node_id'],
                         bios_obj_list[0].node_id)
        self.assertEqual(self.bios_setting['name'], bios_obj_list[0].name)
        self.assertEqual(self.bios_setting['value'], bios_obj_list[0].value)
        self.assertEqual(bios_setting2['node_id'], bios_obj_list[1].node_id)
        self.assertEqual(bios_setting2['name'], bios_obj_list[1].name)
        self.assertEqual(bios_setting2['value'], bios_obj_list[1].value)

    @mock.patch.object(dbapi.IMPL, 'create_bios_setting_list', autospec=True)
    def test_create(self, mock_create_list):
        fake_call_args = {'node_id': self.bios_setting['node_id'],
                          'name': self.bios_setting['name'],
                          'value': self.bios_setting['value'],
                          'version': self.bios_setting['version']}
        setting = [{'name': self.bios_setting['name'],
                    'value': self.bios_setting['value']}]
        bios_obj = objects.BIOSSetting(context=self.context,
                                       **fake_call_args)
        mock_create_list.return_value = [self.bios_setting]
        mock_create_list.call_args
        bios_obj.create()
        mock_create_list.assert_called_once_with(self.bios_setting['node_id'],
                                                 setting,
                                                 self.bios_setting['version'])
        self.assertEqual(self.bios_setting['node_id'], bios_obj.node_id)
        self.assertEqual(self.bios_setting['name'], bios_obj.name)
        self.assertEqual(self.bios_setting['value'], bios_obj.value)

    @mock.patch.object(dbapi.IMPL, 'update_bios_setting_list', autospec=True)
    def test_save(self, mock_update_list):
        fake_call_args = {'node_id': self.bios_setting['node_id'],
                          'name': self.bios_setting['name'],
                          'value': self.bios_setting['value'],
                          'version': self.bios_setting['version']}
        setting = [{'name': self.bios_setting['name'],
                    'value': self.bios_setting['value']}]
        bios_obj = objects.BIOSSetting(context=self.context,
                                       **fake_call_args)
        mock_update_list.return_value = [self.bios_setting]
        mock_update_list.call_args
        bios_obj.save()
        mock_update_list.assert_called_once_with(self.bios_setting['node_id'],
                                                 setting,
                                                 self.bios_setting['version'])
        self.assertEqual(self.bios_setting['node_id'], bios_obj.node_id)
        self.assertEqual(self.bios_setting['name'], bios_obj.name)
        self.assertEqual(self.bios_setting['value'], bios_obj.value)

    @mock.patch.object(dbapi.IMPL, 'create_bios_setting_list', autospec=True)
    def test_list_create(self, mock_create_list):
        bios_setting2 = db_utils.get_test_bios_setting(name='hyperthread',
                                                       value='enabled')
        settings = db_utils.get_test_bios_setting_setting_list()[:-1]
        mock_create_list.return_value = [self.bios_setting, bios_setting2]
        bios_obj_list = objects.BIOSSettingList.create(
            self.context, self.node_id, settings)

        mock_create_list.assert_called_once_with(self.node_id, settings, '1.0')
        self.assertEqual(self.context, bios_obj_list._context)
        self.assertEqual(2, len(bios_obj_list))
        self.assertEqual(self.bios_setting['node_id'],
                         bios_obj_list[0].node_id)
        self.assertEqual(self.bios_setting['name'], bios_obj_list[0].name)
        self.assertEqual(self.bios_setting['value'], bios_obj_list[0].value)
        self.assertEqual(bios_setting2['node_id'], bios_obj_list[1].node_id)
        self.assertEqual(bios_setting2['name'], bios_obj_list[1].name)
        self.assertEqual(bios_setting2['value'], bios_obj_list[1].value)

    @mock.patch.object(dbapi.IMPL, 'update_bios_setting_list', autospec=True)
    def test_list_save(self, mock_update_list):
        bios_setting2 = db_utils.get_test_bios_setting(name='hyperthread',
                                                       value='enabled')
        settings = db_utils.get_test_bios_setting_setting_list()[:-1]
        mock_update_list.return_value = [self.bios_setting, bios_setting2]
        bios_obj_list = objects.BIOSSettingList.save(
            self.context, self.node_id, settings)

        mock_update_list.assert_called_once_with(self.node_id, settings, '1.0')
        self.assertEqual(self.context, bios_obj_list._context)
        self.assertEqual(2, len(bios_obj_list))
        self.assertEqual(self.bios_setting['node_id'],
                         bios_obj_list[0].node_id)
        self.assertEqual(self.bios_setting['name'], bios_obj_list[0].name)
        self.assertEqual(self.bios_setting['value'], bios_obj_list[0].value)
        self.assertEqual(bios_setting2['node_id'], bios_obj_list[1].node_id)
        self.assertEqual(bios_setting2['name'], bios_obj_list[1].name)
        self.assertEqual(bios_setting2['value'], bios_obj_list[1].value)

    @mock.patch.object(dbapi.IMPL, 'delete_bios_setting_list', autospec=True)
    def test_delete(self, mock_delete):
        objects.BIOSSetting.delete(self.context, self.node_id,
                                   self.bios_setting['name'])
        mock_delete.assert_called_once_with(self.node_id,
                                            [self.bios_setting['name']])

    @mock.patch.object(dbapi.IMPL, 'delete_bios_setting_list', autospec=True)
    def test_list_delete(self, mock_delete):
        bios_setting2 = db_utils.get_test_bios_setting(name='hyperthread')
        name_list = [self.bios_setting['name'], bios_setting2['name']]
        objects.BIOSSettingList.delete(self.context, self.node_id, name_list)
        mock_delete.assert_called_once_with(self.node_id, name_list)

    @mock.patch('ironic.objects.bios.BIOSSettingList.get_by_node_id',
                spec_set=types.FunctionType)
    def test_sync_node_setting_create_and_update(self, mock_get):
        node = obj_utils.create_test_node(self.ctxt)
        bios_obj = [obj_utils.create_test_bios_setting(
            self.ctxt, node_id=node.id)]
        mock_get.return_value = bios_obj
        settings = db_utils.get_test_bios_setting_setting_list()
        settings[0]['value'] = 'off'
        create, update, delete, nochange = (
            objects.BIOSSettingList.sync_node_setting(self.ctxt, node.id,
                                                      settings))

        self.assertEqual(create, settings[1:])
        self.assertEqual(update, [settings[0]])
        self.assertEqual(delete, [])
        self.assertEqual(nochange, [])

    @mock.patch('ironic.objects.bios.BIOSSettingList.get_by_node_id',
                spec_set=types.FunctionType)
    def test_sync_node_setting_delete_nochange(self, mock_get):
        node = obj_utils.create_test_node(self.ctxt)
        bios_obj_1 = obj_utils.create_test_bios_setting(
            self.ctxt, node_id=node.id)
        bios_obj_2 = obj_utils.create_test_bios_setting(
            self.ctxt, node_id=node.id, name='numlock', value='off')
        mock_get.return_value = [bios_obj_1, bios_obj_2]
        settings = db_utils.get_test_bios_setting_setting_list()
        settings[0]['name'] = 'fake-bios-option'
        create, update, delete, nochange = (
            objects.BIOSSettingList.sync_node_setting(self.ctxt, node.id,
                                                      settings))

        expected_delete = [{'name': bios_obj_1.name,
                            'value': bios_obj_1.value}]
        self.assertEqual(create, settings[:2])
        self.assertEqual(update, [])
        self.assertEqual(delete, expected_delete)
        self.assertEqual(nochange, [settings[2]])
