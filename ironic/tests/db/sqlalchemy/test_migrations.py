# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Tests for database migrations. This test case reads the configuration
file test_migrations.conf for database connection settings
to use in the tests. For each connection found in the config file,
the test case runs a series of test cases to ensure that migrations work
properly.

There are also "opportunistic" tests for both mysql and postgresql in here,
which allows testing against all 3 databases (sqlite in memory, mysql, pg) in
a properly configured unit test environment.

For the opportunistic testing you need to set up a db named 'openstack_citest'
with user 'openstack_citest' and password 'openstack_citest' on localhost.
The test will then use that db and u/p combo to run the tests.

For postgres on Ubuntu this can be done with the following commands:

sudo -u postgres psql
postgres=# create user openstack_citest with createdb login password
      'openstack_citest';
postgres=# create database openstack_citest with owner openstack_citest;

"""

import ConfigParser
import fixtures
import os
import subprocess
import urlparse

from migrate.versioning import repository
import mock
import sqlalchemy
import sqlalchemy.exc

from ironic.openstack.common.db.sqlalchemy import utils as db_utils
from ironic.openstack.common import lockutils
from ironic.openstack.common import log as logging

import ironic.db.sqlalchemy.migrate_repo
from ironic.tests import base

LOG = logging.getLogger(__name__)


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


def _is_backend_avail(backend, user, passwd, database):
    try:
        connect_uri = _get_connect_string(backend, user, passwd, database)
        engine = sqlalchemy.create_engine(connect_uri)
        connection = engine.connect()
    except Exception:
        # intentionally catch all to handle exceptions even if we don't
        # have any backend code loaded.
        return False
    else:
        connection.close()
        engine.dispose()
        return True


def _have_mysql(user, passwd, database):
    present = os.environ.get('TEST_MYSQL_PRESENT')
    if present is None:
        return _is_backend_avail('mysql', user, passwd, database)
    return present.lower() in ('', 'true')


def _have_postgresql(user, passwd, database):
    present = os.environ.get('TEST_POSTGRESQL_PRESENT')
    if present is None:
        return _is_backend_avail('postgres', user, passwd, database)
    return present.lower() in ('', 'true')


def get_db_connection_info(conn_pieces):
    database = conn_pieces.path.strip('/')
    loc_pieces = conn_pieces.netloc.split('@')
    host = loc_pieces[1]

    auth_pieces = loc_pieces[0].split(':')
    user = auth_pieces[0]
    password = ""
    if len(auth_pieces) > 1:
        password = auth_pieces[1].strip()

    return (user, password, database, host)


class BaseMigrationTestCase(base.TestCase):
    """Base class fort testing of migration utils."""

    def __init__(self, *args, **kwargs):
        super(BaseMigrationTestCase, self).__init__(*args, **kwargs)

        self.DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                                'test_migrations.conf')
        # Test machines can set the TEST_MIGRATIONS_CONF variable
        # to override the location of the config file for migration testing
        self.CONFIG_FILE_PATH = os.environ.get('TEST_MIGRATIONS_CONF',
                                               self.DEFAULT_CONFIG_FILE)
        self.test_databases = {}
        self.migration_api = None

    def setUp(self):
        super(BaseMigrationTestCase, self).setUp()

        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug(_('config_path is %s') % self.CONFIG_FILE_PATH)
        if os.path.exists(self.CONFIG_FILE_PATH):
            cp = ConfigParser.RawConfigParser()
            try:
                cp.read(self.CONFIG_FILE_PATH)
                defaults = cp.defaults()
                for key, value in defaults.items():
                    self.test_databases[key] = value
            except ConfigParser.ParsingError as e:
                self.fail("Failed to read test_migrations.conf config "
                          "file. Got error: %s" % e)
        else:
            self.fail("Failed to find test_migrations.conf config "
                      "file.")

        self.engines = {}
        for key, value in self.test_databases.items():
            self.engines[key] = sqlalchemy.create_engine(value)

        # We start each test case with a completely blank slate.
        self.temp_dir = self.useFixture(fixtures.TempDir())
        self._reset_databases()

        # We also want to clean up, eg. in case of a failing test
        self.addCleanup(self._reset_databases)

    def execute_cmd(self, cmd=None):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, shell=True)
        output = proc.communicate()[0]
        LOG.debug(output)
        self.assertEqual(0, proc.returncode,
                         "Failed to run: %s\n%s" % (cmd, output))

    def _reset_pg(self, conn_pieces):
        @lockutils.synchronized('pgadmin', 'tests-', external=True,
                                lock_path=self.temp_dir.path)
        def _reset_pg_inner():
            (user, password, database, host) = \
                get_db_connection_info(conn_pieces)

            os.environ['PGPASSWORD'] = password
            os.environ['PGUSER'] = user
            # note(boris-42): We must create and drop database, we can't
            # drop database which we have connected to, so for such
            # operations there is a special database template1.
            sqlcmd = ("psql -w -U %(user)s -h %(host)s -c"
                      " '%(sql)s' -d template1")

            sql = ("drop database if exists %s;") % database
            droptable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
            self.execute_cmd(droptable)

            sql = ("create database %s;") % database
            createtable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
            self.execute_cmd(createtable)

            os.unsetenv('PGPASSWORD')
            os.unsetenv('PGUSER')

        _reset_pg_inner()

    def _reset_databases(self):
        for key, engine in self.engines.items():
            conn_string = self.test_databases[key]
            conn_pieces = urlparse.urlparse(conn_string)
            engine.dispose()
            if conn_string.startswith('sqlite'):
                # We can just delete the SQLite database, which is
                # the easiest and cleanest solution
                db_path = conn_pieces.path.strip('/')
                if os.path.exists(db_path):
                    os.unlink(db_path)
                # No need to recreate the SQLite DB. SQLite will
                # create it for us if it's not there...
            elif conn_string.startswith('mysql'):
                # We can execute the MySQL client to destroy and re-create
                # the MYSQL database, which is easier and less error-prone
                # than using SQLAlchemy to do this via MetaData...trust me.
                (user, password, database, host) = \
                    get_db_connection_info(conn_pieces)
                sql = ("drop database if exists %(database)s; "
                       "create database %(database)s;") % \
                       {'database': database}
                cmd = ("mysql -u \"%(user)s\" -p\"%(password)s\" -h %(host)s "
                       "-e \"%(sql)s\"") % {'user': user, 'password': password,
                       'host': host, 'sql': sql}
                self.execute_cmd(cmd)
            elif conn_string.startswith('postgresql'):
                self._reset_pg(conn_pieces)


class WalkVersionsMixin(object):
    def _walk_versions(self, engine=None, snake_walk=False, downgrade=True):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        self.migration_api.version_control(engine, self.REPOSITORY,
                                           self.INIT_VERSION)
        self.assertEqual(self.INIT_VERSION,
                         self.migration_api.db_version(engine,
                                                       self.REPOSITORY))

        LOG.debug(_('latest version is %s') % self.REPOSITORY.latest)
        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)

        for version in versions:
            # upgrade -> downgrade -> upgrade
            self._migrate_up(engine, version, with_data=True)
            if snake_walk:
                downgraded = self._migrate_down(
                    engine, version - 1, with_data=True)
                if downgraded:
                    self._migrate_up(engine, version)

        if downgrade:
            # Now walk it back down to 0 from the latest, testing
            # the downgrade paths.
            for version in reversed(versions):
                # downgrade -> upgrade -> downgrade
                downgraded = self._migrate_down(engine, version - 1)

                if snake_walk and downgraded:
                    self._migrate_up(engine, version)
                    self._migrate_down(engine, version - 1)

    def _migrate_down(self, engine, version, with_data=False):
        try:
            self.migration_api.downgrade(engine, self.REPOSITORY, version)
        except NotImplementedError:
            # NOTE(sirp): some migrations, namely release-level
            # migrations, don't support a downgrade.
            return False

        self.assertEqual(
            version, self.migration_api.db_version(engine, self.REPOSITORY))

        # NOTE(sirp): `version` is what we're downgrading to (i.e. the 'target'
        # version). So if we have any downgrade checks, they need to be run for
        # the previous (higher numbered) migration.
        if with_data:
            post_downgrade = getattr(
                self, "_post_downgrade_%03d" % (version + 1), None)
            if post_downgrade:
                post_downgrade(engine)

        return True

    def _migrate_up(self, engine, version, with_data=False):
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
                    self, "_pre_upgrade_%03d" % version, None)
                if pre_upgrade:
                    data = pre_upgrade(engine)

            self.migration_api.upgrade(engine, self.REPOSITORY, version)
            self.assertEqual(version,
                             self.migration_api.db_version(engine,
                                                           self.REPOSITORY))
            if with_data:
                check = getattr(self, "_check_%03d" % version, None)
                if check:
                    check(engine, data)
        except Exception:
            LOG.error(_("Failed to migrate to version %(version)s on engine "
                        "%(engine)s") % {'version': version, 'engine': engine})
            raise


class TestWalkVersions(base.TestCase, WalkVersionsMixin):
    def setUp(self):
        super(TestWalkVersions, self).setUp()
        self.migration_api = mock.MagicMock()
        self.engine = mock.MagicMock()
        self.REPOSITORY = mock.MagicMock()
        self.INIT_VERSION = 4

    def test_migrate_up(self):
        self.migration_api.db_version.return_value = 141

        self._migrate_up(self.engine, 141)

        self.migration_api.upgrade.assert_called_with(
            self.engine, self.REPOSITORY, 141)
        self.migration_api.db_version.assert_called_with(
            self.engine, self.REPOSITORY)

    def test_migrate_up_with_data(self):
        test_value = {"a": 1, "b": 2}
        self.migration_api.db_version.return_value = 141
        self._pre_upgrade_141 = mock.MagicMock()
        self._pre_upgrade_141.return_value = test_value
        self._check_141 = mock.MagicMock()

        self._migrate_up(self.engine, 141, True)

        self._pre_upgrade_141.assert_called_with(self.engine)
        self._check_141.assert_called_with(self.engine, test_value)

    def test_migrate_down(self):
        self.migration_api.db_version.return_value = 42

        self.assertTrue(self._migrate_down(self.engine, 42))
        self.migration_api.db_version.assert_called_with(
            self.engine, self.REPOSITORY)

    def test_migrate_down_not_implemented(self):
        self.migration_api.downgrade.side_effect = NotImplementedError
        self.assertFalse(self._migrate_down(self.engine, 42))

    def test_migrate_down_with_data(self):
        self._post_downgrade_043 = mock.MagicMock()
        self.migration_api.db_version.return_value = 42

        self._migrate_down(self.engine, 42, True)

        self._post_downgrade_043.assert_called_with(self.engine)

    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    @mock.patch.object(WalkVersionsMixin, '_migrate_down')
    def test_walk_versions_all_default(self, _migrate_up, _migrate_down):
        self.REPOSITORY.latest = 20
        self.migration_api.db_version.return_value = self.INIT_VERSION

        self._walk_versions()

        self.migration_api.version_control.assert_called_with(
            None, self.REPOSITORY, self.INIT_VERSION)
        self.migration_api.db_version.assert_called_with(
            None, self.REPOSITORY)

        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)
        upgraded = [mock.call(None, v, with_data=True) for v in versions]
        self.assertEqual(self._migrate_up.call_args_list, upgraded)

        downgraded = [mock.call(None, v - 1) for v in reversed(versions)]
        self.assertEqual(self._migrate_down.call_args_list, downgraded)

    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    @mock.patch.object(WalkVersionsMixin, '_migrate_down')
    def test_walk_versions_all_true(self, _migrate_up, _migrate_down):
        self.REPOSITORY.latest = 20
        self.migration_api.db_version.return_value = self.INIT_VERSION

        self._walk_versions(self.engine, snake_walk=True, downgrade=True)

        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)
        upgraded = []
        for v in versions:
            upgraded.append(mock.call(self.engine, v, with_data=True))
            upgraded.append(mock.call(self.engine, v))
        upgraded.extend(
            [mock.call(self.engine, v) for v in reversed(versions)]
        )
        self.assertEqual(upgraded, self._migrate_up.call_args_list)

        downgraded_1 = [
            mock.call(self.engine, v - 1, with_data=True) for v in versions
        ]
        downgraded_2 = []
        for v in reversed(versions):
            downgraded_2.append(mock.call(self.engine, v - 1))
            downgraded_2.append(mock.call(self.engine, v - 1))
        downgraded = downgraded_1 + downgraded_2
        self.assertEqual(self._migrate_down.call_args_list, downgraded)

    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    @mock.patch.object(WalkVersionsMixin, '_migrate_down')
    def test_walk_versions_true_false(self, _migrate_up, _migrate_down):
        self.REPOSITORY.latest = 20
        self.migration_api.db_version.return_value = self.INIT_VERSION

        self._walk_versions(self.engine, snake_walk=True, downgrade=False)

        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)

        upgraded = []
        for v in versions:
            upgraded.append(mock.call(self.engine, v, with_data=True))
            upgraded.append(mock.call(self.engine, v))
        self.assertEqual(upgraded, self._migrate_up.call_args_list)

        downgraded = [
            mock.call(self.engine, v - 1, with_data=True) for v in versions
        ]
        self.assertEqual(self._migrate_down.call_args_list, downgraded)

    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    @mock.patch.object(WalkVersionsMixin, '_migrate_down')
    def test_walk_versions_all_false(self, _migrate_up, _migrate_down):
        self.REPOSITORY.latest = 20
        self.migration_api.db_version.return_value = self.INIT_VERSION

        self._walk_versions(self.engine, snake_walk=False, downgrade=False)

        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)

        upgraded = [
            mock.call(self.engine, v, with_data=True) for v in versions
        ]
        self.assertEqual(upgraded, self._migrate_up.call_args_list)


class TestMigrations(BaseMigrationTestCase, WalkVersionsMixin):
    USER = "openstack_citest"
    PASSWD = "openstack_citest"
    DATABASE = "openstack_citest"

    def __init__(self, *args, **kwargs):
        super(TestMigrations, self).__init__(*args, **kwargs)

        self.MIGRATE_FILE = ironic.db.sqlalchemy.migrate_repo.__file__
        self.REPOSITORY = repository.Repository(
                        os.path.abspath(os.path.dirname(self.MIGRATE_FILE)))

    def setUp(self):
        super(TestMigrations, self).setUp()

        self.migration = __import__('ironic.db.migration',
                globals(), locals(), ['INIT_VERSION'], -1)
        self.INIT_VERSION = self.migration.INIT_VERSION
        if self.migration_api is None:
            temp = __import__('ironic.db.sqlalchemy.migration',
                    globals(), locals(), ['versioning_api'], -1)
            self.migration_api = temp.versioning_api

    def _test_mysql_opportunistically(self):
        # Test that table creation on mysql only builds InnoDB tables
        if not _have_mysql(self.USER, self.PASSWD, self.DATABASE):
            self.skipTest("mysql not available")
        # add this to the global lists to make reset work with it, it's removed
        # automatically during Cleanup so no need to clean it up here.
        connect_string = _get_connect_string("mysql", self.USER, self.PASSWD,
                self.DATABASE)
        (user, password, database, host) = \
                get_db_connection_info(urlparse.urlparse(connect_string))
        engine = sqlalchemy.create_engine(connect_string)
        self.engines[database] = engine
        self.test_databases[database] = connect_string

        # build a fully populated mysql database with all the tables
        self._reset_databases()
        self._walk_versions(engine, False, False)

        connection = engine.connect()
        # sanity check
        total = connection.execute("SELECT count(*) "
                                   "from information_schema.TABLES "
                                   "where TABLE_SCHEMA='%s'" % database)
        self.assertTrue(total.scalar() > 0, "No tables found. Wrong schema?")

        noninnodb = connection.execute("SELECT count(*) "
                                       "from information_schema.TABLES "
                                       "where TABLE_SCHEMA='%s' "
                                       "and ENGINE!='InnoDB' "
                                       "and TABLE_NAME!='migrate_version'" %
                                       database)
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)
        connection.close()

    def _test_postgresql_opportunistically(self):
        # Test postgresql database migration walk
        if not _have_postgresql(self.USER, self.PASSWD, self.DATABASE):
            self.skipTest("postgresql not available")
        # add this to the global lists to make reset work with it, it's removed
        # automatically during Cleanup so no need to clean it up here.
        connect_string = _get_connect_string("postgres", self.USER,
                self.PASSWD, self.DATABASE)
        engine = sqlalchemy.create_engine(connect_string)
        (user, password, database, host) = \
                get_db_connection_info(urlparse.urlparse(connect_string))
        self.engines[database] = engine
        self.test_databases[database] = connect_string

        # build a fully populated postgresql database with all the tables
        self._reset_databases()
        self._walk_versions(engine, False, False)

    def test_walk_versions(self):
        for engine in self.engines.values():
            self._walk_versions(engine, snake_walk=False, downgrade=False)

    def test_mysql_opportunistically(self):
        self._test_mysql_opportunistically()

    def test_mysql_connect_fail(self):
        """Test that we can trigger a mysql connection failure

        Test that we can fail gracefully to ensure we don't break people
        without mysql
        """
        if _is_backend_avail('mysql', "openstack_cifail", self.PASSWD,
                             self.DATABASE):
            self.fail("Shouldn't have connected")

    def test_postgresql_opportunistically(self):
        self._test_postgresql_opportunistically()

    def test_postgresql_connect_fail(self):
        """Test that we can trigger a postgres connection failure

        Test that we can fail gracefully to ensure we don't break people
        without postgres
        """
        if _is_backend_avail('postgres', "openstack_cifail", self.PASSWD,
                             self.DATABASE):
            self.fail("Shouldn't have connected")

    def _check_001(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        nodes_col = {
            'id': 'Integer', 'uuid': 'String', 'power_info': 'Text',
            'cpu_arch': 'String', 'cpu_num': 'Integer', 'memory': 'Integer',
            'local_storage_max': 'Integer', 'task_state': 'String',
            'image_path': 'String', 'instance_uuid': 'String',
            'instance_name': 'String', 'extra': 'Text',
            'created_at': 'DateTime', 'updated_at': 'DateTime'
        }
        for col, coltype in nodes_col.items():
            self.assertTrue(isinstance(nodes.c[col].type,
                                       getattr(sqlalchemy.types, coltype)))

        ifaces = db_utils.get_table(engine, 'ifaces')
        ifaces_col = {
            'id': 'Integer', 'address': 'String', 'node_id': 'Integer',
            'extra': 'Text', 'created_at': 'DateTime', 'updated_at': 'DateTime'
        }
        for col, coltype in ifaces_col.items():
            self.assertTrue(isinstance(ifaces.c[col].type,
                                       getattr(sqlalchemy.types, coltype)))

        fkey, = ifaces.c.node_id.foreign_keys
        self.assertEqual(nodes.c.id.name, fkey.column.name)
        self.assertEqual(fkey.column.table.name, 'nodes')

    def _check_002(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        new_col = {
            'chassis_id': 'Integer', 'task_start': 'DateTime',
            'properties': 'Text', 'control_driver': 'String',
            'control_info': 'Text', 'deploy_driver': 'String',
            'deploy_info': 'Text', 'reservation': 'String'
        }
        for col, coltype in new_col.items():
            self.assertTrue(isinstance(nodes.c[col].type,
                                       getattr(sqlalchemy.types, coltype)))

        deleted_cols = ['power_info', 'cpu_arch', 'cpu_num', 'memory',
                        'local_storage_max', 'image_path', 'instance_name']
        for column in nodes.c:
            self.assertFalse(column.name in deleted_cols)

    def _check_003(self, engine, data):
        chassis = db_utils.get_table(engine, 'chassis')
        self.assertTrue(isinstance(chassis.c.id.type,
                                   sqlalchemy.types.Integer))
        self.assertTrue(isinstance(chassis.c.uuid.type,
                                   sqlalchemy.types.String))

    def _check_004(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(), 'ports'))
        self.assertFalse(engine.dialect.has_table(engine.connect(), 'ifaces'))

    def _check_005(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertFalse('deploy_driver' in col_names)
        self.assertFalse('deploy_info' in col_names)
        self.assertTrue('driver' in col_names)
        self.assertTrue('driver_info' in col_names)

    def _check_006(self, engine, data):
        ports = db_utils.get_table(engine, 'ports')
        self.assertTrue(isinstance(ports.c.uuid.type, sqlalchemy.types.String))

        nodes = db_utils.get_table(engine, 'nodes')
        nodes_data = {
             'id': 1, 'uuid': 'uuu-111', 'driver': 'driver1',
             'driver_info': 'info1', 'task_state': 'state1',
             'extra': 'extra1'
            }
        nodes.insert().values(nodes_data).execute()

        ports_data = {
                'address': 'address0', 'node_id': 1, 'uuid': 'uuu-222',
                'extra': 'extra2'
            }
        ports.insert().values(ports_data).execute()
        self.assertRaises(
            sqlalchemy.exc.IntegrityError,
            ports.insert().execute,
            {'address': 'address1', 'node_id': 1, 'uuid': 'uuu-222',
             'extra': 'extra3'})

    def _check_007(self, engine, data):
        chassis = db_utils.get_table(engine, 'chassis')
        new_col = {'extra': 'Text', 'created_at': 'DateTime',
                   'updated_at': 'DateTime'}
        for col, coltype in new_col.items():
            self.assertTrue(isinstance(chassis.c[col].type,
                                       getattr(sqlalchemy.types, coltype)))

    def _check_008(self, engine, data):
        chassis = db_utils.get_table(engine, 'chassis')
        self.assertTrue(isinstance(chassis.c.description.type,
                                   sqlalchemy.types.String))

    def _check_009(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]

        self.assertFalse('task_start' in col_names)
        self.assertFalse('task_state' in col_names)

        new_col = {'power_state': 'String',
                   'target_power_state': 'String',
                   'provision_state': 'String',
                   'target_provision_state': 'String'}
        for col, coltype in new_col.items():
            self.assertTrue(isinstance(nodes.c[col].type,
                                       getattr(sqlalchemy.types, coltype)))

    def _check_010(self, engine, data):
        insp = sqlalchemy.engine.reflection.Inspector.from_engine(engine)
        f_keys = insp.get_foreign_keys('nodes')
        self.assertEqual(len(f_keys), 1)
        f_key = f_keys[0]
        self.assertEqual(f_key['referred_table'], 'chassis')
        self.assertEqual(f_key['referred_columns'], ['id'])
        self.assertEqual(f_key['constrained_columns'], ['chassis_id'])

    def _check_011(self, engine, data):
        chassis = db_utils.get_table(engine, 'chassis')
        chassis_data = {'uuid': 'uuu-111-222', 'extra': 'extra1'}
        chassis.insert().values(chassis_data).execute()
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          chassis.insert().execute,
                          {'uuid': 'uuu-111-222', 'extra': 'extra2'})

    def _check_012(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 'conductors'))
        conductor = db_utils.get_table(engine, 'conductors')
        conductor_data = {'hostname': 'test-host'}
        conductor.insert().values(conductor_data).execute()
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          conductor.insert().execute,
                          conductor_data)

        # NOTE(deva): different backends raise different error here.
        if isinstance(engine.dialect,
                sqlalchemy.dialects.sqlite.pysqlite.SQLiteDialect_pysqlite):
            self.assertRaises(sqlalchemy.exc.IntegrityError,
                          conductor.insert().execute,
                          {'hostname': None})
        if isinstance(engine.dialect,
                sqlalchemy.dialects.mysql.pymysql.MySQLDialect_pymysql):
            self.assertRaises(sqlalchemy.exc.OperationalError,
                          conductor.insert().execute,
                          {'hostname': None})
        # FIXME: add check for postgres

    def _pre_upgrade_013(self, engine):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = set(column.name for column in nodes.c)

        self.assertFalse('last_error' in col_names)
        return col_names

    def _check_013(self, engine, col_names_pre):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = set(column.name for column in nodes.c)

        # didn't lose any columns in the migration
        self.assertEqual(col_names_pre, col_names.intersection(col_names_pre))

        # only added one 'last_error' column
        self.assertEqual(len(col_names_pre), len(col_names) - 1)
        self.assertTrue(isinstance(nodes.c['last_error'].type,
                                   getattr(sqlalchemy.types, 'Text')))

    def _check_014(self, engine, data):
        if engine.name == 'sqlite':
            ports = db_utils.get_table(engine, 'ports')
            ports_data = {'address': 'BB:BB:AA:AA:AA:AA', 'extra': 'extra1'}
            ports.insert().values(ports_data).execute()
            self.assertRaises(sqlalchemy.exc.IntegrityError,
                              ports.insert().execute,
                              {'address': 'BB:BB:AA:AA:AA:AA',
                               'extra': 'extra2'})
            # test recreate old UC
            ports_data = {
                          'address': 'BB:BB:AA:AA:AA:BB',
                          'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c781',
                          'extra': 'extra2'}
            ports.insert().values(ports_data).execute()
            self.assertRaises(sqlalchemy.exc.IntegrityError,
                              ports.insert().execute,
                              {'address': 'CC:BB:AA:AA:AA:CC',
                               'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c781',
                               'extra': 'extra3'})

    def _check_015(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]

        self.assertIn('maintenance', col_names)
        # in some backends bool type is integer
        self.assertTrue(isinstance(nodes.c.maintenance.type,
                                   sqlalchemy.types.Boolean) or
                        isinstance(nodes.c.maintenance.type,
                                   sqlalchemy.types.Integer))
