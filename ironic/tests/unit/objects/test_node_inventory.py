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

from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestNodeInventoryObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestNodeInventoryObject, self).setUp()
        self.fake_inventory = db_utils.get_test_inventory()

    def test_create(self):
        with mock.patch.object(self.dbapi, 'create_node_inventory',
                               autospec=True) as mock_db_create:
            mock_db_create.return_value = self.fake_inventory
            new_inventory = objects.NodeInventory(
                self.context, **self.fake_inventory)
            new_inventory.create()

            mock_db_create.assert_called_once_with(self.fake_inventory)

    def test_destroy(self):
        node_id = self.fake_inventory['node_id']
        with mock.patch.object(self.dbapi, 'get_node_inventory_by_node_id',
                               autospec=True) as mock_get:
            mock_get.return_value = self.fake_inventory
            with mock.patch.object(self.dbapi,
                                   'destroy_node_inventory_by_node_id',
                                   autospec=True) as mock_db_destroy:
                inventory = objects.NodeInventory.get_by_node_id(self.context,
                                                                 node_id)
                inventory.destroy()

                mock_db_destroy.assert_called_once_with(node_id)
