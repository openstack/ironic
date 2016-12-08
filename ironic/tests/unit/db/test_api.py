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

from oslo_utils import uuidutils

from ironic.common import context
from ironic.common import release_mappings
from ironic.db import api as db_api
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


class UpgradingTestCase(base.DbTestCase):

    def setUp(self):
        super(UpgradingTestCase, self).setUp()
        self.dbapi = db_api.get_instance()
        self.object_versions = release_mappings.get_object_versions()

    def test_check_versions_emptyDB(self):
        # nothing in the DB
        self.assertTrue(self.dbapi.check_versions())

    def test_check_versions(self):
        for v in self.object_versions['Node']:
            node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                          version=v)
            node = self.dbapi.get_node_by_id(node.id)
            self.assertEqual(v, node.version)
        self.assertTrue(self.dbapi.check_versions())

    def test_check_versions_node_no_version(self):
        node = utils.create_test_node(version=None)
        node = self.dbapi.get_node_by_id(node.id)
        self.assertIsNone(node.version)
        self.assertFalse(self.dbapi.check_versions())

    def test_check_versions_node_old(self):
        node = utils.create_test_node(version='1.0')
        node = self.dbapi.get_node_by_id(node.id)
        self.assertEqual('1.0', node.version)
        self.assertFalse(self.dbapi.check_versions())


class BackfillVersionTestCase(base.DbTestCase):

    def setUp(self):
        super(BackfillVersionTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
        obj_mapping = release_mappings.RELEASE_MAPPING['ocata']['objects']
        self.node_ver = obj_mapping['Node'][0]
        self.chassis_ver = obj_mapping['Chassis'][0]

    def test_empty_db(self):
        self.assertEqual((0, 0),
                         self.dbapi.backfill_version_column(self.context, 10))

    def test_version_exists(self):
        utils.create_test_node()
        self.assertEqual((0, 0),
                         self.dbapi.backfill_version_column(self.context, 10))

    def test_one_node(self):
        node = utils.create_test_node(version=None)
        self.assertIsNone(node.version)
        node = self.dbapi.get_node_by_uuid(node.uuid)
        self.assertIsNone(node.version)
        self.assertEqual((1, 1),
                         self.dbapi.backfill_version_column(self.context, 10))
        res = self.dbapi.get_node_by_uuid(node.uuid)
        self.assertEqual(self.node_ver, res.version)

    def test_max_count_zero(self):
        orig_node = utils.create_test_node(version=None)
        orig_chassis = utils.create_test_chassis(version=None)
        self.assertIsNone(orig_node.version)
        self.assertIsNone(orig_chassis.version)
        self.assertEqual((2, 2),
                         self.dbapi.backfill_version_column(self.context, 0))
        node = self.dbapi.get_node_by_uuid(orig_node.uuid)
        self.assertEqual(self.node_ver, node.version)
        chassis = self.dbapi.get_chassis_by_uuid(orig_chassis.uuid)
        self.assertEqual(self.chassis_ver, chassis.version)

    def test_no_version_max_count_1(self):
        orig_node = utils.create_test_node(version=None)
        orig_chassis = utils.create_test_chassis(version=None)
        self.assertIsNone(orig_node.version)
        self.assertIsNone(orig_chassis.version)
        self.assertEqual((2, 1),
                         self.dbapi.backfill_version_column(self.context, 1))
        node = self.dbapi.get_node_by_uuid(orig_node.uuid)
        chassis = self.dbapi.get_chassis_by_uuid(orig_chassis.uuid)
        self.assertTrue(node.version is None or chassis.version is None)
        self.assertTrue(node.version == self.node_ver or
                        chassis.version == self.chassis_ver)

    def _create_nodes(self, num_nodes, version=None):
        nodes = []
        for i in range(0, num_nodes):
            node = utils.create_test_node(version=version,
                                          uuid=uuidutils.generate_uuid())
            nodes.append(node.uuid)
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertIsNone(node.version)
        return nodes

    def test_no_version_max_count_2_some_nodes(self):
        nodes = self._create_nodes(5)

        self.assertEqual((5, 2),
                         self.dbapi.backfill_version_column(self.context, 2))
        self.assertEqual((3, 3),
                         self.dbapi.backfill_version_column(self.context, 10))
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(self.node_ver, node.version)

    def test_no_version_max_count_same_nodes(self):
        nodes = self._create_nodes(5)

        self.assertEqual((5, 5),
                         self.dbapi.backfill_version_column(self.context, 5))
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(self.node_ver, node.version)
