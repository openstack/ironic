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

import random
from unittest import mock

from oslo_config import cfg
from oslo_db.sqlalchemy import utils as db_utils
from oslo_utils import uuidutils
import sqlalchemy as sa

from ironic.common import context
from ironic.common import exception
from ironic.common import release_mappings
from ironic.common import states
from ironic.db import api as db_api
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


CONF = cfg.CONF


class UpgradingTestCase(base.DbTestCase):

    def setUp(self):
        super(UpgradingTestCase, self).setUp()
        self.dbapi = db_api.get_instance()
        self.object_versions = release_mappings.get_object_versions()

    def test_check_versions_emptyDB(self):
        # nothing in the DB
        self.assertTrue(self.dbapi.check_versions())

    @mock.patch.object(db_utils, 'column_exists', autospec=True)
    def test_check_versions_missing_version_columns(self, column_exists):
        column_exists.return_value = False
        self.assertRaises(exception.DatabaseVersionTooOld,
                          self.dbapi.check_versions)

    @mock.patch.object(release_mappings, 'get_object_versions', autospec=True)
    @mock.patch.object(db_utils, 'column_exists', autospec=True)
    def test_check_versions_handles_missing_table(
            self, column_exists, mock_release_mappings):
        column_exists.side_effect = sa.exc.NoSuchTableError('meow')
        mock_release_mappings.return_value = {'Node': {'1.0'}}
        self.assertTrue(
            self.dbapi.check_versions(permit_initial_version=True))
        self.assertEqual(1, column_exists.call_count)

    @mock.patch.object(release_mappings, 'get_object_versions', autospec=True)
    @mock.patch.object(db_utils, 'column_exists', autospec=True)
    def test_check_versions_handles_missing_table_with_multiple_versions(
            self, column_exists, mock_release_mappings):
        # When an object was introduced at 1.0 and later bumped to 1.1,
        # the table may still be missing during an upgrade from an older
        # release. This should be handled gracefully as long as 1.0 is
        # in the supported versions set.
        column_exists.side_effect = sa.exc.NoSuchTableError('meow')
        mock_release_mappings.return_value = {'Node': {'1.0', '1.1'}}
        self.assertTrue(
            self.dbapi.check_versions(permit_initial_version=True))
        self.assertEqual(1, column_exists.call_count)

    @mock.patch.object(release_mappings, 'get_object_versions', autospec=True)
    @mock.patch.object(db_utils, 'column_exists', autospec=True)
    def test_check_versions_raises_missing_table(
            self, column_exists, mock_release_mappings):
        # A table that was never at version 1.0 should not be missing.
        column_exists.side_effect = sa.exc.NoSuchTableError('meow')
        mock_release_mappings.return_value = {'Node': {'1.5', '1.6'}}
        self.assertRaises(sa.exc.NoSuchTableError, self.dbapi.check_versions)
        self.assertEqual(1, column_exists.call_count)

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

    def test_check_versions_ignore_node(self):
        node = utils.create_test_node(version=None)
        node = self.dbapi.get_node_by_id(node.id)
        self.assertIsNone(node.version)
        self.assertTrue(self.dbapi.check_versions(ignore_models=['Node']))

    def test_check_versions_node_old(self):
        node = utils.create_test_node(version='1.0')
        node = self.dbapi.get_node_by_id(node.id)
        self.assertEqual('1.0', node.version)
        self.assertFalse(self.dbapi.check_versions())

    def test_check_versions_conductor(self):
        for v in self.object_versions['Conductor']:
            # NOTE(jroll) conductor model doesn't have a uuid :(
            conductor = utils.create_test_conductor(
                hostname=uuidutils.generate_uuid(), version=v,
                id=random.randint(1, 1000000))
            conductor = self.dbapi.get_conductor(conductor.hostname)
            self.assertEqual(v, conductor.version)
        self.assertTrue(self.dbapi.check_versions())

    def test_check_versions_conductor_old(self):
        conductor = utils.create_test_conductor(version='1.0')
        conductor = self.dbapi.get_conductor(conductor.hostname)
        self.assertEqual('1.0', conductor.version)
        self.assertFalse(self.dbapi.check_versions())


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
        self.assertTrue(node.version == self.node_old_ver
                        or chassis.version == self.chassis_old_ver)
        self.assertTrue(node.version == self.node_ver
                        or chassis.version == self.chassis_ver)

    def _create_nodes(self, num_nodes):
        version = self.node_old_ver
        nodes = []
        for i in range(0, num_nodes):
            node = utils.create_test_node(version=version,
                                          uuid=uuidutils.generate_uuid())
            # Create entries on the tables so we force field upgrades
            utils.create_test_node_trait(node_id=node.id, trait='foo',
                                         version='0.0')
            utils.create_test_bios_setting(node_id=node.id, version='1.0')

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
        # Check/migrate 2, 10 remain.
        self.assertEqual(
            (10, 2), self.dbapi.update_to_latest_versions(self.context, 2))
        # Check/migrate 10, 8 migrated, 8 remain.
        self.assertEqual(
            (8, 8), self.dbapi.update_to_latest_versions(self.context, 10))
        # Just make sure it is still 0, 0 in case more things are added.
        self.assertEqual(
            (0, 0), self.dbapi.update_to_latest_versions(self.context, 10))
        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(self.node_ver, node.version)

    def test_old_version_max_count_same_nodes(self):
        if self.node_version_same:
            # can't test if we don't have diff versions of the node
            return
        vm_count = 5
        nodes = self._create_nodes(vm_count)
        # NOTE(TheJulia): Under current testing, 5 node will result in 10
        # records implicitly needing to be migrated.
        migrate_count = vm_count * 2
        self.assertEqual(
            (migrate_count, migrate_count),
            self.dbapi.update_to_latest_versions(self.context,
                                                 migrate_count))
        self.assertEqual(
            (0, 0), self.dbapi.update_to_latest_versions(self.context,
                                                         migrate_count))

        for uuid in nodes:
            node = self.dbapi.get_node_by_uuid(uuid)
            self.assertEqual(self.node_ver, node.version)


class MigrateToBuiltinInspectionTestCase(base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
        CONF.set_override('enabled_inspect_interfaces', 'agent,no-inspect')

        for _ in range(3):
            utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                   inspect_interface='inspector')
        for _ in range(2):
            utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                   inspect_interface='agent')
        utils.create_test_node(uuid=uuidutils.generate_uuid(),
                               inspect_interface='no-inspect')

    def _check(self, migrated, left):
        current = sorted(x[0] for x in self.dbapi.get_nodeinfo_list(
            columns=['inspect_interface']))
        self.assertEqual(['agent'] * migrated + ['inspector'] * left
                         + ['no-inspect'], current)

    def test_migrate_all(self):
        total, migrated = self.dbapi.migrate_to_builtin_inspection(
            self.context, 0)
        self.assertEqual(3, total)
        self.assertEqual(3, migrated)
        self._check(5, 0)

    def test_cannot_migrate(self):
        CONF.set_override('enabled_inspect_interfaces', 'inspector,no-inspect')
        total, migrated = self.dbapi.migrate_to_builtin_inspection(
            self.context, 0)
        self.assertEqual(0, total)
        self.assertEqual(0, migrated)
        self._check(2, 3)

    def test_cannot_migrate_some(self):
        for state in [states.INSPECTING, states.INSPECTWAIT,
                      states.INSPECTFAIL]:
            utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                   inspect_interface='inspector',
                                   provision_state=state)
        total, migrated = self.dbapi.migrate_to_builtin_inspection(
            self.context, 0)
        self.assertEqual(6, total)
        self.assertEqual(3, migrated)
        self._check(5, 3)

    def test_migrate_with_limit(self):
        total, migrated = self.dbapi.migrate_to_builtin_inspection(
            self.context, 2)
        self.assertEqual(3, total)
        self.assertEqual(2, migrated)
        self._check(4, 1)


class MigrateRunbookNamesToTraitsTestCase(base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()

        # Create test runbooks without traits (simulating pre-migration state)
        self.runbook1 = utils.create_test_runbook(
            name='CUSTOM_FIRMWARE_UPDATE',
            uuid=uuidutils.generate_uuid())
        self.runbook2 = utils.create_test_runbook(
            name='CUSTOM_BIOS_CONFIG',
            uuid=uuidutils.generate_uuid())
        self.runbook3 = utils.create_test_runbook(
            name='HW_CPU_X86_VMX',
            uuid=uuidutils.generate_uuid())

    def _check_traits_migrated(self, runbook_id, expected_trait):
        """Helper to verify a runbook has the expected trait."""
        traits = self.dbapi.get_runbook_traits_by_runbook_id(runbook_id)
        self.assertEqual(1, len(traits))
        self.assertEqual(expected_trait, traits[0].trait)

    def test_migrate_all_runbooks(self):
        """Test migrating all runbooks without limits."""
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 0)

        self.assertEqual(3, total)
        self.assertEqual(3, migrated)

        # Verify all runbooks got their traits
        self._check_traits_migrated(self.runbook1['id'],
                                    'CUSTOM_FIRMWARE_UPDATE')
        self._check_traits_migrated(self.runbook2['id'], 'CUSTOM_BIOS_CONFIG')
        self._check_traits_migrated(self.runbook3['id'], 'HW_CPU_X86_VMX')

    def test_migrate_with_limit(self):
        """Test migrating with a limit on number of runbooks."""
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 2)

        self.assertEqual(3, total)
        self.assertEqual(2, migrated)

        # Should have 2 runbooks with traits and 1 without
        all_traits = []
        runbook_ids = [self.runbook1['id'], self.runbook2['id'],
                       self.runbook3['id']]
        for runbook_id in runbook_ids:
            traits = self.dbapi.get_runbook_traits_by_runbook_id(runbook_id)
            all_traits.append(len(traits))

        # Should have exactly 2 runbooks with traits (1 trait each) and 1
        # without
        self.assertEqual([0, 1, 1], sorted(all_traits))

    def test_migrate_already_migrated(self):
        """Test that already migrated runbooks are not migrated again."""
        # First migration
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 0)
        self.assertEqual(3, total)
        self.assertEqual(3, migrated)

        # Second migration should find nothing to do
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 0)
        self.assertEqual(0, total)
        self.assertEqual(0, migrated)

    def test_migrate_partial_then_complete(self):
        """Test completing migration after partial migration."""
        # Partial migration
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 1)
        self.assertEqual(3, total)
        self.assertEqual(1, migrated)

        # Complete the migration
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 0)
        self.assertEqual(2, total)  # 2 remaining
        self.assertEqual(2, migrated)

        # Verify all are now migrated
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 0)
        self.assertEqual(0, total)
        self.assertEqual(0, migrated)

    def test_migrate_mixed_runbooks(self):
        """Test migration with mix of migrated and unmigrated runbooks."""
        # Manually add traits to one runbook (simulate partially migrated
        # state)
        self.dbapi.add_runbook_trait(
            self.runbook1['id'], 'MANUAL_TRAIT', '1.0')

        # Now migrate - should only migrate the 2 without traits
        total, migrated = self.dbapi.migrate_runbook_names_to_traits(
            self.context, 0)
        self.assertEqual(2, total)
        self.assertEqual(2, migrated)

        # Verify the manually added trait wasn't touched
        traits = self.dbapi.get_runbook_traits_by_runbook_id(
            self.runbook1['id'])
        self.assertEqual(1, len(traits))
        self.assertEqual('MANUAL_TRAIT', traits[0].trait)
