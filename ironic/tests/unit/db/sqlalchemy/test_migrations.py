# Copyright 2010-2011 OpenStack Foundation
# Copyright 2012-2013 IBM Corp.
# All Rights Reserved.
#
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

"""
Tests for database migrations. There are "opportunistic" tests for both mysql
and postgresql in here, which allows testing against these databases in a
properly configured unit test environment.

For the opportunistic testing you need to set up a db named 'openstack_citest'
with user 'openstack_citest' and password 'openstack_citest' on localhost.
The test will then use that db and u/p combo to run the tests.

For postgres on Ubuntu this can be done with the following commands:

::

 sudo -u postgres psql
 postgres=# create user openstack_citest with createdb login password
      'openstack_citest';
 postgres=# create database openstack_citest with owner openstack_citest;

"""

import collections
import contextlib

from alembic import script
import fixtures
import mock
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
from oslo_db.tests.sqlalchemy import base as test_base
from oslo_log import log as logging
from oslo_utils import uuidutils
import sqlalchemy
import sqlalchemy.exc

from ironic.conf import CONF
from ironic.db.sqlalchemy import migration
from ironic.db.sqlalchemy import models
from ironic.tests import base

LOG = logging.getLogger(__name__)

# NOTE(vdrok): This was introduced after migration tests started taking more
# time in gate. Timeout value in seconds for tests performing migrations.
MIGRATIONS_TIMEOUT = 300


def _get_connect_string(backend, user, passwd, database):
    """Get database connection

    Try to get a connection with a very specific set of values, if we get
    these then we'll run the tests, otherwise they are skipped
    """
    if backend == "postgres":
        backend = "postgresql+psycopg2"
    elif backend == "mysql":
        backend = "mysql+mysqldb"
    else:
        raise Exception("Unrecognized backend: '%s'" % backend)

    return ("%(backend)s://%(user)s:%(passwd)s@localhost/%(database)s"
            % {'backend': backend, 'user': user, 'passwd': passwd,
               'database': database})


@contextlib.contextmanager
def patch_with_engine(engine):
    with mock.patch.object(enginefacade.writer,
                           'get_engine') as patch_engine:
        patch_engine.return_value = engine
        yield


class WalkVersionsMixin(object):
    def _walk_versions(self, engine=None, alembic_cfg=None):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        with patch_with_engine(engine):

            script_directory = script.ScriptDirectory.from_config(alembic_cfg)

            self.assertIsNone(self.migration_api.version(alembic_cfg))

            versions = [ver for ver in script_directory.walk_revisions()]

            for version in reversed(versions):
                self._migrate_up(engine, alembic_cfg,
                                 version.revision, with_data=True)

    def _migrate_up(self, engine, config, version, with_data=False):
        """migrate up to a new version of the db.

        We allow for data insertion and post checks at every
        migration version with special _pre_upgrade_### and
        _check_### functions in the main test.
        """
        # NOTE(sdague): try block is here because it's impossible to debug
        # where a failed data migration happens otherwise
        try:
            if with_data:
                data = None
                pre_upgrade = getattr(
                    self, "_pre_upgrade_%s" % version, None)
                if pre_upgrade:
                    data = pre_upgrade(engine)

            self.migration_api.upgrade(version, config=config)
            self.assertEqual(version, self.migration_api.version(config))
            if with_data:
                check = getattr(self, "_check_%s" % version, None)
                if check:
                    check(engine, data)
        except Exception:
            LOG.error("Failed to migrate to version %(version)s on engine "
                      "%(engine)s",
                      {'version': version, 'engine': engine})
            raise


class TestWalkVersions(base.TestCase, WalkVersionsMixin):
    def setUp(self):
        super(TestWalkVersions, self).setUp()
        self.migration_api = mock.MagicMock()
        self.engine = mock.MagicMock()
        self.config = mock.MagicMock()
        self.versions = [mock.Mock(revision='2b2'), mock.Mock(revision='1a1')]

    def test_migrate_up(self):
        self.migration_api.version.return_value = 'dsa123'

        self._migrate_up(self.engine, self.config, 'dsa123')

        self.migration_api.upgrade.assert_called_with('dsa123',
                                                      config=self.config)
        self.migration_api.version.assert_called_with(self.config)

    def test_migrate_up_with_data(self):
        test_value = {"a": 1, "b": 2}
        self.migration_api.version.return_value = '141'
        self._pre_upgrade_141 = mock.MagicMock()
        self._pre_upgrade_141.return_value = test_value
        self._check_141 = mock.MagicMock()

        self._migrate_up(self.engine, self.config, '141', True)

        self._pre_upgrade_141.assert_called_with(self.engine)
        self._check_141.assert_called_with(self.engine, test_value)

    @mock.patch.object(script, 'ScriptDirectory')
    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    def test_walk_versions_all_default(self, _migrate_up, script_directory):
        fc = script_directory.from_config()
        fc.walk_revisions.return_value = self.versions
        self.migration_api.version.return_value = None

        self._walk_versions(self.engine, self.config)

        self.migration_api.version.assert_called_with(self.config)

        upgraded = [mock.call(self.engine, self.config, v.revision,
                    with_data=True) for v in reversed(self.versions)]
        self.assertEqual(self._migrate_up.call_args_list, upgraded)

    @mock.patch.object(script, 'ScriptDirectory')
    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    def test_walk_versions_all_false(self, _migrate_up, script_directory):
        fc = script_directory.from_config()
        fc.walk_revisions.return_value = self.versions
        self.migration_api.version.return_value = None

        self._walk_versions(self.engine, self.config)

        upgraded = [mock.call(self.engine, self.config, v.revision,
                    with_data=True) for v in reversed(self.versions)]
        self.assertEqual(upgraded, self._migrate_up.call_args_list)


class MigrationCheckersMixin(object):

    def setUp(self):
        super(MigrationCheckersMixin, self).setUp()
        self.config = migration._alembic_config()
        self.migration_api = migration
        self.useFixture(fixtures.Timeout(MIGRATIONS_TIMEOUT,
                                         gentle=True))

    def test_walk_versions(self):
        self._walk_versions(self.engine, self.config)

    def _check_21b331f883ef(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('provision_updated_at', col_names)
        self.assertIsInstance(nodes.c.provision_updated_at.type,
                              sqlalchemy.types.DateTime)

    def _check_3cb628139ea4(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]

        self.assertIn('console_enabled', col_names)
        # in some backends bool type is integer
        self.assertIsInstance(nodes.c.console_enabled.type,
                              (sqlalchemy.types.Boolean,
                               sqlalchemy.types.Integer))

    def _check_31baaf680d2b(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('instance_info', col_names)
        self.assertIsInstance(nodes.c.instance_info.type,
                              sqlalchemy.types.TEXT)

    def _check_3bea56f25597(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        instance_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        data = {'driver': 'fake',
                'uuid': uuidutils.generate_uuid(),
                'instance_uuid': instance_uuid}
        nodes.insert().values(data).execute()
        data['uuid'] = uuidutils.generate_uuid()
        self.assertRaises(db_exc.DBDuplicateEntry,
                          nodes.insert().execute, data)

    def _check_487deb87cc9d(self, engine, data):
        conductors = db_utils.get_table(engine, 'conductors')
        column_names = [column.name for column in conductors.c]

        self.assertIn('online', column_names)
        self.assertIsInstance(conductors.c.online.type,
                              (sqlalchemy.types.Boolean,
                               sqlalchemy.types.Integer))
        nodes = db_utils.get_table(engine, 'nodes')
        column_names = [column.name for column in nodes.c]
        self.assertIn('conductor_affinity', column_names)
        self.assertIsInstance(nodes.c.conductor_affinity.type,
                              sqlalchemy.types.Integer)

        data_conductor = {'hostname': 'test_host'}
        conductors.insert().execute(data_conductor)
        conductor = conductors.select(
            conductors.c.hostname ==
            data_conductor['hostname']).execute().first()

        data_node = {'uuid': uuidutils.generate_uuid(),
                     'conductor_affinity': conductor['id']}
        nodes.insert().execute(data_node)
        node = nodes.select(
            nodes.c.uuid == data_node['uuid']).execute().first()
        self.assertEqual(conductor['id'], node['conductor_affinity'])

    def _check_242cc6a923b3(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('maintenance_reason', col_names)
        self.assertIsInstance(nodes.c.maintenance_reason.type,
                              sqlalchemy.types.String)

    def _pre_upgrade_5674c57409b9(self, engine):
        # add some nodes in various states so we can assert that "None"
        # was replaced by "available", and nothing else changed.
        nodes = db_utils.get_table(engine, 'nodes')
        data = [{'uuid': uuidutils.generate_uuid(),
                 'provision_state': 'fake state'},
                {'uuid': uuidutils.generate_uuid(),
                 'provision_state': 'active'},
                {'uuid': uuidutils.generate_uuid(),
                 'provision_state': 'deleting'},
                {'uuid': uuidutils.generate_uuid(),
                 'provision_state': None}]
        nodes.insert().values(data).execute()
        return data

    def _check_5674c57409b9(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        result = engine.execute(nodes.select())

        def _get_state(uuid):
            for row in data:
                if row['uuid'] == uuid:
                    return row['provision_state']

        for row in result:
            old = _get_state(row['uuid'])
            new = row['provision_state']
            if old is None:
                self.assertEqual('available', new)
            else:
                self.assertEqual(old, new)

    def _check_bb59b63f55a(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('driver_internal_info', col_names)
        self.assertIsInstance(nodes.c.driver_internal_info.type,
                              sqlalchemy.types.TEXT)

    def _check_3ae36a5f5131(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        column_names = [column.name for column in nodes.c]
        self.assertIn('name', column_names)
        self.assertIsInstance(nodes.c.name.type,
                              sqlalchemy.types.String)
        data = {'driver': 'fake',
                'uuid': uuidutils.generate_uuid(),
                'name': 'node'
                }
        nodes.insert().values(data).execute()
        data['uuid'] = uuidutils.generate_uuid()
        self.assertRaises(db_exc.DBDuplicateEntry,
                          nodes.insert().execute, data)

    def _check_1e1d5ace7dc6(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        column_names = [column.name for column in nodes.c]
        self.assertIn('inspection_started_at', column_names)
        self.assertIn('inspection_finished_at', column_names)
        self.assertIsInstance(nodes.c.inspection_started_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(nodes.c.inspection_finished_at.type,
                              sqlalchemy.types.DateTime)

    def _check_4f399b21ae71(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('clean_step', col_names)
        self.assertIsInstance(nodes.c.clean_step.type,
                              sqlalchemy.types.String)

    def _check_789acc877671(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('raid_config', col_names)
        self.assertIn('target_raid_config', col_names)
        self.assertIsInstance(nodes.c.raid_config.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(nodes.c.target_raid_config.type,
                              sqlalchemy.types.String)

    def _check_2fb93ffd2af1(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        bigstring = 'a' * 255
        uuid = uuidutils.generate_uuid()
        data = {'uuid': uuid, 'name': bigstring}
        nodes.insert().execute(data)
        node = nodes.select(nodes.c.uuid == uuid).execute().first()
        self.assertEqual(bigstring, node['name'])

    def _check_516faf1bb9b1(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        bigstring = 'a' * 255
        uuid = uuidutils.generate_uuid()
        data = {'uuid': uuid, 'driver': bigstring}
        nodes.insert().execute(data)
        node = nodes.select(nodes.c.uuid == uuid).execute().first()
        self.assertEqual(bigstring, node['driver'])

    def _check_48d6c242bb9b(self, engine, data):
        node_tags = db_utils.get_table(engine, 'node_tags')
        col_names = [column.name for column in node_tags.c]
        self.assertIn('tag', col_names)
        self.assertIsInstance(node_tags.c.tag.type,
                              sqlalchemy.types.String)
        nodes = db_utils.get_table(engine, 'nodes')
        data = {'id': '123', 'name': 'node1'}
        nodes.insert().execute(data)
        data = {'node_id': '123', 'tag': 'tag1'}
        node_tags.insert().execute(data)
        tag = node_tags.select(node_tags.c.node_id == '123').execute().first()
        self.assertEqual('tag1', tag['tag'])

    def _check_5ea1b0d310e(self, engine, data):
        portgroup = db_utils.get_table(engine, 'portgroups')
        col_names = [column.name for column in portgroup.c]
        expected_names = ['created_at', 'updated_at', 'id', 'uuid', 'name',
                          'node_id', 'address', 'extra']
        self.assertEqual(sorted(expected_names), sorted(col_names))

        self.assertIsInstance(portgroup.c.created_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(portgroup.c.updated_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(portgroup.c.id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(portgroup.c.uuid.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(portgroup.c.name.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(portgroup.c.node_id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(portgroup.c.address.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(portgroup.c.extra.type,
                              sqlalchemy.types.TEXT)

        ports = db_utils.get_table(engine, 'ports')
        col_names = [column.name for column in ports.c]
        self.assertIn('pxe_enabled', col_names)
        self.assertIn('portgroup_id', col_names)
        self.assertIn('local_link_connection', col_names)
        self.assertIsInstance(ports.c.portgroup_id.type,
                              sqlalchemy.types.Integer)
        # in some backends bool type is integer
        self.assertIsInstance(ports.c.pxe_enabled.type,
                              (sqlalchemy.types.Boolean,
                               sqlalchemy.types.Integer))

    def _pre_upgrade_f6fdb920c182(self, engine):
        # add some ports.
        ports = db_utils.get_table(engine, 'ports')
        data = [{'uuid': uuidutils.generate_uuid(), 'pxe_enabled': None},
                {'uuid': uuidutils.generate_uuid(), 'pxe_enabled': None}]
        ports.insert().values(data).execute()
        return data

    def _check_f6fdb920c182(self, engine, data):
        ports = db_utils.get_table(engine, 'ports')
        result = engine.execute(ports.select())

        def _was_inserted(uuid):
            for row in data:
                if row['uuid'] == uuid:
                    return True

        for row in result:
            if _was_inserted(row['uuid']):
                self.assertTrue(row['pxe_enabled'])

    def _check_e294876e8028(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('network_interface', col_names)
        self.assertIsInstance(nodes.c.network_interface.type,
                              sqlalchemy.types.String)

    def _check_10b163d4481e(self, engine, data):
        ports = db_utils.get_table(engine, 'ports')
        portgroups = db_utils.get_table(engine, 'portgroups')
        port_col_names = [column.name for column in ports.c]
        portgroup_col_names = [column.name for column in portgroups.c]
        self.assertIn('internal_info', port_col_names)
        self.assertIn('internal_info', portgroup_col_names)
        self.assertIsInstance(ports.c.internal_info.type,
                              sqlalchemy.types.TEXT)
        self.assertIsInstance(portgroups.c.internal_info.type,
                              sqlalchemy.types.TEXT)

    def _check_dd34e1f1303b(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('resource_class', col_names)
        self.assertIsInstance(nodes.c.resource_class.type,
                              sqlalchemy.types.String)

    def _pre_upgrade_c14cef6dfedf(self, engine):
        # add some nodes.
        nodes = db_utils.get_table(engine, 'nodes')
        data = [{'uuid': uuidutils.generate_uuid(),
                 'network_interface': None},
                {'uuid': uuidutils.generate_uuid(),
                 'network_interface': None},
                {'uuid': uuidutils.generate_uuid(),
                 'network_interface': 'neutron'}]
        nodes.insert().values(data).execute()
        return data

    def _check_c14cef6dfedf(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        result = engine.execute(nodes.select())
        counts = collections.defaultdict(int)

        def _was_inserted(uuid):
            for row in data:
                if row['uuid'] == uuid:
                    return True

        for row in result:
            if _was_inserted(row['uuid']):
                counts[row['network_interface']] += 1

        # using default config values, we should have 2 flat and one neutron
        self.assertEqual(2, counts['flat'])
        self.assertEqual(1, counts['neutron'])
        self.assertEqual(0, counts[None])

    def _check_60cf717201bc(self, engine, data):
        portgroups = db_utils.get_table(engine, 'portgroups')
        col_names = [column.name for column in portgroups.c]
        self.assertIn('standalone_ports_supported', col_names)
        self.assertIsInstance(portgroups.c.standalone_ports_supported.type,
                              (sqlalchemy.types.Boolean,
                               sqlalchemy.types.Integer))

    def _check_bcdd431ba0bf(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        added_ifaces = ['boot', 'console', 'deploy', 'inspect',
                        'management', 'power', 'raid', 'vendor']
        for iface in added_ifaces:
            name = '%s_interface' % iface
            self.assertIn(name, col_names)
            self.assertIsInstance(getattr(nodes.c, name).type,
                                  sqlalchemy.types.String)

    def _check_daa1ba02d98(self, engine, data):
        connectors = db_utils.get_table(engine, 'volume_connectors')
        col_names = [column.name for column in connectors.c]
        expected_names = ['created_at', 'updated_at', 'id', 'uuid', 'node_id',
                          'type', 'connector_id', 'extra']
        self.assertEqual(sorted(expected_names), sorted(col_names))

        self.assertIsInstance(connectors.c.created_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(connectors.c.updated_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(connectors.c.id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(connectors.c.uuid.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(connectors.c.node_id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(connectors.c.type.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(connectors.c.connector_id.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(connectors.c.extra.type,
                              sqlalchemy.types.TEXT)

    def _check_1a59178ebdf6(self, engine, data):
        targets = db_utils.get_table(engine, 'volume_targets')
        col_names = [column.name for column in targets.c]
        expected_names = ['created_at', 'updated_at', 'id', 'uuid', 'node_id',
                          'boot_index', 'extra', 'properties', 'volume_type',
                          'volume_id']
        self.assertEqual(sorted(expected_names), sorted(col_names))

        self.assertIsInstance(targets.c.created_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(targets.c.updated_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(targets.c.id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(targets.c.uuid.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(targets.c.node_id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(targets.c.boot_index.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(targets.c.extra.type,
                              sqlalchemy.types.TEXT)
        self.assertIsInstance(targets.c.properties.type,
                              sqlalchemy.types.TEXT)
        self.assertIsInstance(targets.c.volume_type.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(targets.c.volume_id.type,
                              sqlalchemy.types.String)

    def _pre_upgrade_493d8f27f235(self, engine):
        portgroups = db_utils.get_table(engine, 'portgroups')
        data = [{'uuid': uuidutils.generate_uuid()},
                {'uuid': uuidutils.generate_uuid()}]
        portgroups.insert().values(data).execute()
        return data

    def _check_493d8f27f235(self, engine, data):
        portgroups = db_utils.get_table(engine, 'portgroups')
        col_names = [column.name for column in portgroups.c]
        self.assertIn('properties', col_names)
        self.assertIsInstance(portgroups.c.properties.type,
                              sqlalchemy.types.TEXT)
        self.assertIn('mode', col_names)
        self.assertIsInstance(portgroups.c.mode.type,
                              sqlalchemy.types.String)

        result = engine.execute(portgroups.select())
        for row in result:
            self.assertEqual(CONF.default_portgroup_mode, row['mode'])

    def _check_1d6951876d68(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('storage_interface', col_names)
        self.assertIsInstance(nodes.c.storage_interface.type,
                              sqlalchemy.types.String)

    def _check_2353895ecfae(self, engine, data):
        ifaces = db_utils.get_table(engine, 'conductor_hardware_interfaces')
        col_names = [column.name for column in ifaces.c]
        expected_names = ['created_at', 'updated_at', 'id', 'conductor_id',
                          'hardware_type', 'interface_type', 'interface_name']
        self.assertEqual(sorted(expected_names), sorted(col_names))

        self.assertIsInstance(ifaces.c.created_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(ifaces.c.updated_at.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(ifaces.c.id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(ifaces.c.conductor_id.type,
                              sqlalchemy.types.Integer)
        self.assertIsInstance(ifaces.c.hardware_type.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(ifaces.c.interface_type.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(ifaces.c.interface_name.type,
                              sqlalchemy.types.String)

    def _check_dbefd6bdaa2c(self, engine, data):
        ifaces = db_utils.get_table(engine, 'conductor_hardware_interfaces')
        col_names = [column.name for column in ifaces.c]
        self.assertIn('default', col_names)
        self.assertIsInstance(ifaces.c.default.type,
                              (sqlalchemy.types.Boolean,
                               sqlalchemy.types.Integer))

    def _check_3d86a077a3f2(self, engine, data):
        ports = db_utils.get_table(engine, 'ports')
        col_names = [column.name for column in ports.c]
        self.assertIn('physical_network', col_names)
        self.assertIsInstance(ports.c.physical_network.type,
                              sqlalchemy.types.String)

    def _check_868cb606a74a(self, engine, data):
        for table in ['chassis', 'conductors', 'node_tags', 'nodes',
                      'portgroups', 'ports', 'volume_connectors',
                      'volume_targets', 'conductor_hardware_interfaces']:
            table = db_utils.get_table(engine, table)
            col_names = [column.name for column in table.c]
            self.assertIn('version', col_names)
            self.assertIsInstance(table.c.version.type,
                                  sqlalchemy.types.String)

    def test_upgrade_and_version(self):
        with patch_with_engine(self.engine):
            self.migration_api.upgrade('head')
            self.assertIsNotNone(self.migration_api.version())

    def test_create_schema_and_version(self):
        with patch_with_engine(self.engine):
            self.migration_api.create_schema()
            self.assertIsNotNone(self.migration_api.version())

    def test_upgrade_and_create_schema(self):
        with patch_with_engine(self.engine):
            self.migration_api.upgrade('31baaf680d2b')
            self.assertRaises(db_exc.DbMigrationError,
                              self.migration_api.create_schema)

    def test_upgrade_twice(self):
        with patch_with_engine(self.engine):
            self.migration_api.upgrade('31baaf680d2b')
            v1 = self.migration_api.version()
            self.migration_api.upgrade('head')
            v2 = self.migration_api.version()
            self.assertNotEqual(v1, v2)


class TestMigrationsMySQL(MigrationCheckersMixin,
                          WalkVersionsMixin,
                          test_base.MySQLOpportunisticTestCase):
    pass


class TestMigrationsPostgreSQL(MigrationCheckersMixin,
                               WalkVersionsMixin,
                               test_base.PostgreSQLOpportunisticTestCase):
    pass


class ModelsMigrationSyncMixin(object):

    def setUp(self):
        super(ModelsMigrationSyncMixin, self).setUp()
        self.useFixture(fixtures.Timeout(MIGRATIONS_TIMEOUT,
                                         gentle=True))

    def get_metadata(self):
        return models.Base.metadata

    def get_engine(self):
        return self.engine

    def db_sync(self, engine):
        with patch_with_engine(engine):
            migration.upgrade('head')


class ModelsMigrationsSyncMysql(ModelsMigrationSyncMixin,
                                test_migrations.ModelsMigrationsSync,
                                test_base.MySQLOpportunisticTestCase):
    pass


class ModelsMigrationsSyncPostgres(ModelsMigrationSyncMixin,
                                   test_migrations.ModelsMigrationsSync,
                                   test_base.PostgreSQLOpportunisticTestCase):
    pass
