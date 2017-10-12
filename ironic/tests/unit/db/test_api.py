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
from testtools import matchers

from ironic.common import context
from ironic.common import driver_factory
from ironic.common import exception
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

    def test_check_versions_conductor_old(self):
        conductor = utils.create_test_conductor(version='1.0')
        conductor = self.dbapi.get_conductor(conductor.hostname)
        self.assertEqual('1.0', conductor.version)
        self.assertFalse(self.dbapi.check_versions())


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


class GetNotVersionsTestCase(base.DbTestCase):

    def setUp(self):
        super(GetNotVersionsTestCase, self).setUp()
        self.dbapi = db_api.get_instance()

    def test_get_not_versions(self):
        versions = ['1.1', '1.2', '1.3']
        node_uuids = []
        for v in versions:
            node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                          version=v)
            node_uuids.append(node.uuid)
        self.assertEqual([], self.dbapi.get_not_versions('Node', versions))

        res = self.dbapi.get_not_versions('Node', ['2.0'])
        self.assertThat(res, matchers.HasLength(len(node_uuids)))
        res_uuids = [n.uuid for n in res]
        self.assertEqual(node_uuids, res_uuids)

        res = self.dbapi.get_not_versions('Node', versions[1:])
        self.assertThat(res, matchers.HasLength(1))
        self.assertEqual(node_uuids[0], res[0].uuid)

    def test_get_not_versions_null(self):
        node = utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      version=None)
        node = self.dbapi.get_node_by_id(node.id)
        self.assertIsNone(node.version)
        res = self.dbapi.get_not_versions('Node', ['1.6'])
        self.assertThat(res, matchers.HasLength(1))
        self.assertEqual(node.uuid, res[0].uuid)

    def test_get_not_versions_no_model(self):
        utils.create_test_node(uuid=uuidutils.generate_uuid(), version='1.4')
        self.assertRaises(exception.IronicException,
                          self.dbapi.get_not_versions, 'NotExist', ['1.6'])
