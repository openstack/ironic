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
import contextlib
import fixtures
import os
import subprocess

from alembic import script
import mock
import six.moves.urllib.parse as urlparse
import sqlalchemy
import sqlalchemy.exc

from ironic.db.sqlalchemy import migration
from ironic.openstack.common.db.sqlalchemy import utils as db_utils
from ironic.openstack.common import lockutils
from ironic.openstack.common import log as logging
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


@contextlib.contextmanager
def patch_with_engine(engine):
    with mock.patch(('ironic.db'
                     '.sqlalchemy.api.get_engine')) as patch_migration:
        patch_migration.return_value = engine
        yield


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
    def _walk_versions(self, engine=None, alembic_cfg=None, downgrade=True):
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

            if downgrade:
                for version in versions:
                    self._migrate_down(engine, alembic_cfg, version.revision)

    def _migrate_down(self, engine, config, version, with_data=False):
        try:
            self.migration_api.downgrade(version, config=config)
        except NotImplementedError:
            # NOTE(sirp): some migrations, namely release-level
            # migrations, don't support a downgrade.
            return False

        self.assertEqual(version, self.migration_api.version(config))

        # NOTE(sirp): `version` is what we're downgrading to (i.e. the 'target'
        # version). So if we have any downgrade checks, they need to be run for
        # the previous (higher numbered) migration.
        if with_data:
            post_downgrade = getattr(
                self, "_post_downgrade_%s" % (version), None)
            if post_downgrade:
                post_downgrade(engine)

        return True

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
            LOG.error(_("Failed to migrate to version %(version)s on engine "
                        "%(engine)s") % {'version': version, 'engine': engine})
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

    def test_migrate_down(self):
        self.migration_api.version.return_value = '42'

        self.assertTrue(self._migrate_down(self.engine, self.config, '42'))
        self.migration_api.version.assert_called_with(self.config)

    def test_migrate_down_not_implemented(self):
        self.migration_api.downgrade.side_effect = NotImplementedError
        self.assertFalse(self._migrate_down(self.engine, self.config, '42'))

    def test_migrate_down_with_data(self):
        self._post_downgrade_043 = mock.MagicMock()
        self.migration_api.version.return_value = '043'

        self._migrate_down(self.engine, self.config, '043', True)

        self._post_downgrade_043.assert_called_with(self.engine)

    @mock.patch.object(script, 'ScriptDirectory')
    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    @mock.patch.object(WalkVersionsMixin, '_migrate_down')
    def test_walk_versions_all_default(self, _migrate_up, _migrate_down,
                                       script_directory):
        script_directory.from_config().\
            walk_revisions.return_value = self.versions
        self.migration_api.version.return_value = None

        self._walk_versions(self.engine, self.config)

        self.migration_api.version.assert_called_with(self.config)

        upgraded = [mock.call(self.engine, self.config, v.revision,
                    with_data=True) for v in reversed(self.versions)]
        self.assertEqual(self._migrate_up.call_args_list, upgraded)

        downgraded = [mock.call(self.engine, self.config, v.revision)
                      for v in self.versions]
        self.assertEqual(self._migrate_down.call_args_list, downgraded)

    @mock.patch.object(script, 'ScriptDirectory')
    @mock.patch.object(WalkVersionsMixin, '_migrate_up')
    @mock.patch.object(WalkVersionsMixin, '_migrate_down')
    def test_walk_versions_all_false(self, _migrate_up, _migrate_down,
                                     script_directory):
        script_directory.from_config().\
            walk_revisions.return_value = self.versions
        self.migration_api.version.return_value = None

        self._walk_versions(self.engine, self.config, downgrade=False)

        upgraded = [mock.call(self.engine, self.config, v.revision,
                    with_data=True) for v in reversed(self.versions)]
        self.assertEqual(upgraded, self._migrate_up.call_args_list)


class TestMigrations(BaseMigrationTestCase, WalkVersionsMixin):
    USER = "openstack_citest"
    PASSWD = "openstack_citest"
    DATABASE = "openstack_citest"

    def __init__(self, *args, **kwargs):
        super(TestMigrations, self).__init__(*args, **kwargs)

    def setUp(self):
        super(TestMigrations, self).setUp()
        self.config = migration._alembic_config()
        if self.migration_api is None:
            self.migration_api = migration

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
        self._walk_versions(engine, self.config, downgrade=False)

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
                                       "and TABLE_NAME!='alembic_version'" %
                                       database)
        count = noninnodb.scalar()
        self.assertEqual(0, count, "%d non InnoDB tables created" % count)
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
        self._walk_versions(engine, self.config, downgrade=False)

    def test_walk_versions(self):
        if not len(self.engines.values()):
            self.skipTest("No engines initialized")

        for engine in self.engines.values():
            self._walk_versions(engine, self.config, downgrade=False)

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
        self.assertTrue(isinstance(nodes.c.console_enabled.type,
                                   sqlalchemy.types.Boolean) or
                        isinstance(nodes.c.console_enabled.type,
                                   sqlalchemy.types.Integer))

    def _check_31baaf680d2b(self, engine, data):
        nodes = db_utils.get_table(engine, 'nodes')
        col_names = [column.name for column in nodes.c]
        self.assertIn('instance_info', col_names)
        self.assertIsInstance(nodes.c.instance_info.type,
                              sqlalchemy.types.TEXT)
