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

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DBNodeInventoryTestCase(base.DbTestCase):

    def setUp(self):
        super(DBNodeInventoryTestCase, self).setUp()
        self.node = db_utils.create_test_node()
        self.inventory = db_utils.create_test_inventory(
            id=0, node_id=self.node.id,
            inventory_data={"inventory": "test_inventory"},
            plugin_data={"plugin_data": "test_plugin_data"})

    def test_destroy_node_inventory_by_node_id(self):
        self.dbapi.destroy_node_inventory_by_node_id(self.inventory.node_id)
        self.assertRaises(exception.NodeInventoryNotFound,
                          self.dbapi.get_node_inventory_by_node_id,
                          self.node.id)

    def test_get_inventory_by_node_id(self):
        res = self.dbapi.get_node_inventory_by_node_id(self.inventory.node_id)
        self.assertEqual(self.inventory.id, res.id)
