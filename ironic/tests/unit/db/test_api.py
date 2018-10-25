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
from oslo_utils import uuidutils

from ironic.common import context
from ironic.common import driver_factory
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

    def test_check_versions_conductor(self):
        for v in self.object_versions['Conductor']:
            conductor = utils.create_test_conductor(
                uuid=uuidutils.generate_uuid(), version=v)
            conductor = self.dbapi.get_conductor(conductor.hostname)
            self.assertEqual(v, conductor.version)
        self.assertTrue(self.dbapi.check_versions())

    def test_check_versions_conductor_no_version(self):
        # works in Queens only
        conductor = utils.create_test_conductor(version=None)
        conductor = self.dbapi.get_conductor(conductor.hostname)
        self.assertIsNone(conductor.version)
        self.assertTrue(self.dbapi.check_versions())

    def test_check_versions_conductor_old(self):
        conductor = utils.create_test_conductor(version='1.0')
        conductor = self.dbapi.get_conductor(conductor.hostname)
        self.assertEqual('1.0', conductor.version)
        self.assertFalse(self.dbapi.check_versions())


class BackfillVersionTestCase(base.DbTestCase):

    def setUp(self):
        super(BackfillVersionTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
        obj_mapping = release_mappings.RELEASE_MAPPING['pike']['objects']
        self.conductor_ver = obj_mapping['Conductor'][0]

    def test_empty_db(self):
        self.assertEqual((0, 0),
                         self.dbapi.backfill_version_column(self.context, 10))

    def test_version_exists(self):
        utils.create_test_conductor()
        self.assertEqual((0, 0),
                         self.dbapi.backfill_version_column(self.context, 10))

    def test_one_conductor(self):
        conductors = self._create_conductors(1)
        self.assertEqual((1, 1),
                         self.dbapi.backfill_version_column(self.context, 10))
        res = self.dbapi.get_conductor(conductors[0])
        self.assertEqual(self.conductor_ver, res.version)

    def test_max_count_zero(self):
        conductors = self._create_conductors(2)
        self.assertEqual((2, 2),
                         self.dbapi.backfill_version_column(self.context, 0))
        for hostname in conductors:
            conductor = self.dbapi.get_conductor(hostname)
            self.assertEqual(self.conductor_ver, conductor.version)

    def _create_conductors(self, num, version=None):
        conductors = []
        for i in range(0, num):
            conductor = utils.create_test_conductor(
                version=version,
                hostname='test_name_%d' % i,
                uuid=uuidutils.generate_uuid())
            conductors.append(conductor.hostname)
        for hostname in conductors:
            conductor = self.dbapi.get_conductor(hostname)
            self.assertEqual(version, conductor.version)
        return conductors

    def test_no_version_max_count_2_some_conductors(self):
        conductors = self._create_conductors(5)

        self.assertEqual((5, 2),
                         self.dbapi.backfill_version_column(self.context, 2))
        self.assertEqual((3, 3),
                         self.dbapi.backfill_version_column(self.context, 10))
        for hostname in conductors:
            conductor = self.dbapi.get_conductor(hostname)
            self.assertEqual(self.conductor_ver, conductor.version)

    def test_no_version_max_count_same(self):
        conductors = self._create_conductors(5)

        self.assertEqual((5, 5),
                         self.dbapi.backfill_version_column(self.context, 5))
        for hostname in conductors:
            conductor = self.dbapi.get_conductor(hostname)
            self.assertEqual(self.conductor_ver, conductor.version)


@mock.patch.object(driver_factory, 'calculate_migration_delta', autospec=True)
@mock.patch.object(driver_factory, 'classic_drivers_to_migrate', autospec=True)
class MigrateToHardwareTypesTestCase(base.DbTestCase):

    def setUp(self):
        super(MigrateToHardwareTypesTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
        self.node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                           driver='classic_driver')

    def test_migrate(self, mock_drivers, mock_delta):
        mock_drivers.return_value = {'classic_driver': mock.sentinel.drv1,
                                     'another_driver': mock.sentinel.drv2}
        mock_delta.return_value = {'driver': 'new_driver',
                                   'inspect_interface': 'new_inspect'}
        result = self.dbapi.migrate_to_hardware_types(self.context, 0)
        self.assertEqual((1, 1), result)
        node = self.dbapi.get_node_by_id(self.node.id)
        self.assertEqual('new_driver', node.driver)
        self.assertEqual('new_inspect', node.inspect_interface)

    def test_migrate_unsupported(self, mock_drivers, mock_delta):
        mock_drivers.return_value = {'classic_driver': mock.sentinel.drv1,
                                     'another_driver': mock.sentinel.drv2}
        mock_delta.return_value = None
        result = self.dbapi.migrate_to_hardware_types(self.context, 0)
        self.assertEqual((1, 1), result)
        node = self.dbapi.get_node_by_id(self.node.id)
        self.assertEqual('classic_driver', node.driver)


class UpdateToLatestVersionsTestCase(base.DbTestCase):

    def setUp(self):
        super(UpdateToLatestVersionsTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()

        obj_versions = release_mappings.get_object_versions(
            objects=['Node', 'Chassis'])
        master_objs = release_mappings.RELEASE_MAPPING['master']['objects']
        self.node_ver = master_objs['Node'][0]
        self.chassis_ver = master_objs['Chassis'][0]
        self.node_old_ver = self._get_old_object_version(
            self.node_ver, obj_versions['Node'])
        self.chassis_old_ver = self._get_old_object_version(
            self.chassis_ver, obj_versions['Chassis'])
        self.node_version_same = self.node_old_ver == self.node_ver
        self.chassis_version_same = self.chassis_old_ver == self.chassis_ver
        # number of objects with different versions
        self.num_diff_objs = 2
        if self.node_version_same:
            self.num_diff_objs -= 1
        if self.chassis_version_same:
            self.num_diff_objs -= 1

    def _get_old_object_version(self, latest_version, versions):
        """Return a version that is older (not same) as latest version.

        If there aren't any older versions, return the latest version.
        """
        for v in versions:
            if v != latest_version:
                return v
        return latest_version

    def test_empty_db(self):
        self.assertEqual(
            (0, 0), self.dbapi.update_to_latest_versions(self.context, 10))

    def test_version_exists(self):
        # Node will be in latest version
        utils.create_test_node()
        self.assertEqual(
            (0, 0), self.dbapi.update_to_latest_versions(self.context, 10))

    def test_one_node(self):
        node = utils.create_test_node(version=self.node_old_ver)
        expected = (0, 0) if self.node_version_same else (1, 1)
        self.assertEqual(
            expected, self.dbapi.update_to_latest_versions(self.context, 10))
        res = self.dbapi.get_node_by_uuid(node.uuid)
        self.assertEqual(self.node_ver, res.version)

    def test_max_count_zero(self):
        orig_node = utils.create_test_node(version=self.node_old_ver)
        orig_chassis = utils.create_test_chassis(version=self.chassis_old_ver)
        self.assertEqual((self.num_diff_objs, self.num_diff_objs),
                         self.dbapi.update_to_latest_versions(self.context, 0))
        node = self.dbapi.get_node_by_uuid(orig_node.uuid)
        self.assertEqual(self.node_ver, node.version)
        chassis = self.dbapi.get_chassis_by_uuid(orig_chassis.uuid)
        self.assertEqual(self.chassis_ver, chassis.version)

    def test_old_version_max_count_1(self):
        orig_node = utils.create_test_node(version=self.node_old_ver)
        orig_chassis = utils.create_test_chassis(version=self.chassis_old_ver)
        num_modified = 1 if self.num_diff_objs else 0
        self.assertEqual((self.num_diff_objs, num_modified),
                         self.dbapi.update_to_latest_versions(self.context, 1))
        node = self.dbapi.get_node_by_uuid(orig_node.uuid)
        chassis = self.dbapi.get_chassis_by_uuid(orig_chassis.uuid)
        self.assertTrue(node.version == self.node_old_ver or
                        chassis.version == self.chassis_old_ver)
        self.assertTrue(node.version == self.node_ver or
                        chassis.version == self.chassis_ver)

    def _create_nodes(self, num_nodes):
        version = self.node_old_ver
        nodes = []
        for i in range(0, num_nodes):
            node = utils.create_test_node(version=version,
                                          uuid=uuidutils.generate_uuid())
            nodes.append(node.uuid)
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(version, node.version)
        return nodes

    def test_old_version_max_count_2_some_nodes(self):
        if self.node_version_same:
            # can't test if we don't have diff versions of the node
            return

        nodes = self._create_nodes(5)
        self.assertEqual(
            (5, 2), self.dbapi.update_to_latest_versions(self.context, 2))
        self.assertEqual(
            (3, 3), self.dbapi.update_to_latest_versions(self.context, 10))
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(self.node_ver, node.version)

    def test_old_version_max_count_same_nodes(self):
        if self.node_version_same:
            # can't test if we don't have diff versions of the node
            return

        nodes = self._create_nodes(5)
        self.assertEqual(
            (5, 5), self.dbapi.update_to_latest_versions(self.context, 5))
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(self.node_ver, node.version)
