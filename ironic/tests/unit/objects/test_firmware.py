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
import types
from unittest import mock


from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestFirmwareComponentObject(db_base.DbTestCase,
                                  obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestFirmwareComponentObject, self).setUp()
        self.firmware_component_dict = db_utils.get_test_firmware_component()

    def test_get_firmware_component(self):
        with mock.patch.object(self.dbapi, 'get_firmware_component',
                               autospec=True) as mock_get_component:
            node_id = self.firmware_component_dict['node_id']
            name = self.firmware_component_dict['component']
            mock_get_component.return_value = self.firmware_component_dict

            fw_component = objects.FirmwareComponent.get(
                self.context, node_id, name)

            mock_get_component.assert_called_once_with(node_id, name)

            self.assertEqual(self.context, fw_component._context)
            self.assertEqual(self.firmware_component_dict['node_id'],
                             fw_component.node_id)
            self.assertEqual(self.firmware_component_dict['component'],
                             fw_component.component)
            self.assertEqual(self.firmware_component_dict['initial_version'],
                             fw_component.initial_version)
            self.assertEqual(self.firmware_component_dict['current_version'],
                             fw_component.current_version)
            self.assertEqual(
                self.firmware_component_dict['last_version_flashed'],
                fw_component.last_version_flashed)

    def test_get_firmware_component_does_not_exist(self):
        fw_cmp_name = "does not exist"
        with mock.patch.object(self.dbapi, 'get_firmware_component',
                               autospec=True) as mock_get_component:
            not_found = exception.FirmwareComponentNotFound(
                node=self.firmware_component_dict['node_id'],
                name=fw_cmp_name)
            mock_get_component.side_effect = not_found

            self.assertRaises(exception.FirmwareComponentNotFound,
                              objects.FirmwareComponent.get, self.context,
                              self.firmware_component_dict['node_id'],
                              fw_cmp_name)

    def test_get_firmware_component_node_does_not_exist(self):
        with mock.patch.object(self.dbapi, 'get_firmware_component',
                               autospec=True) as mock_get_component:
            mock_get_component.side_effect = exception.NodeNotFound(node=404)

            self.assertRaises(exception.NodeNotFound,
                              objects.FirmwareComponent.get, self.context,
                              self.firmware_component_dict['node_id'],
                              self.firmware_component_dict['component'])

    def test_create(self):
        with mock.patch.object(self.dbapi, 'create_firmware_component',
                               autospec=True) as mock_db_create:
            mock_db_create.return_value = self.firmware_component_dict
            new_fw_component = objects.FirmwareComponent(
                self.context, **self.firmware_component_dict)
            new_fw_component.create()

            mock_db_create.assert_called_once_with(
                self.firmware_component_dict)

    def test_save(self):
        node_id = self.firmware_component_dict['node_id']
        name = self.firmware_component_dict['component']
        test_time = datetime.datetime(2000, 1, 1, 0, 0)

        with mock.patch.object(self.dbapi, 'get_firmware_component',
                               autospec=True) as mock_get_fw:
            mock_get_fw.return_value = self.firmware_component_dict
            with mock.patch.object(self.dbapi, 'update_firmware_component',
                                   autospec=True) as mock_update_fw:

                mock_update_fw.return_value = (
                    db_utils.get_test_firmware_component(
                        current_version="v2.0.1",
                        last_version_flashed="v2.0.1",
                        updated_at=test_time)
                )

                fw_cmp = objects.FirmwareComponent.get(
                    self.context, node_id, name)
                fw_cmp.current_version = "v2.0.1"
                fw_cmp.last_version_flashed = "v2.0.1"
                fw_cmp.save()

                mock_get_fw.assert_called_once_with(node_id, name)

                mock_update_fw.assert_called_once_with(
                    node_id, fw_cmp.component,
                    {'current_version': 'v2.0.1',
                     'last_version_flashed': 'v2.0.1',
                     'version': objects.FirmwareComponent.VERSION})

                self.assertEqual(self.context, fw_cmp._context)
                self.assertEqual("v2.0.1", fw_cmp.current_version)
                self.assertEqual("v2.0.1", fw_cmp.last_version_flashed)
                res_updated_at = (fw_cmp.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    @mock.patch(
        'ironic.objects.firmware.FirmwareComponentList.get_by_node_id',
        spec_set=types.FunctionType)
    def test_sync_firmware_components_create_and_update(self, mock_get):
        node = obj_utils.create_test_node(self.context)
        fw_obj = obj_utils.create_test_firmware_component(
            self.context, node_id=node.id)
        mock_get.return_value = [fw_obj]
        components = db_utils.get_test_firmware_component_list()
        components[0]['current_version'] = 'v2.0.0'
        components[0]['last_version_flashed'] = 'v2.0.0'
        create, update, unchanged = (
            objects.FirmwareComponentList.sync_firmware_components(
                self.context, node.id, components))
        self.assertEqual(create, components[1:])
        self.assertEqual(update, [components[0]])
        self.assertEqual(unchanged, [])

    @mock.patch(
        'ironic.objects.firmware.FirmwareComponentList.get_by_node_id',
        spec_set=types.FunctionType)
    def test_sync_firmware_components_nochange(self, mock_get):
        node = obj_utils.create_test_node(self.context)
        fw_obj_1 = obj_utils.create_test_firmware_component(
            self.context, node_id=node.id)
        fw_obj_2 = obj_utils.create_test_firmware_component(
            self.context, node_id=node.id, component='BIOS',
            initial_version='v1.5.0', current_version='v1.5.0')
        mock_get.return_value = [fw_obj_1, fw_obj_2]
        components = db_utils.get_test_firmware_component_list()

        create, update, unchanged = (
            objects.FirmwareComponentList.sync_firmware_components(
                self.context, node.id, components))
        self.assertEqual(create, [])
        self.assertEqual(update, [])
        self.assertEqual(unchanged, components)
