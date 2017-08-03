# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import mock

from ironic.cmd import dbsync
from ironic.common import context
from ironic.db import migration
from ironic.tests.unit.db import base as db_base


class DbSyncTestCase(db_base.DbTestCase):

    def test_upgrade_and_version(self):
        migration.upgrade('head')
        v = migration.version()
        self.assertTrue(v)


class OnlineMigrationTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OnlineMigrationTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.db_cmds = dbsync.DBCommand()

    def test__check_versions(self):
        with mock.patch.object(self.dbapi, 'check_versions',
                               autospec=True) as mock_check_versions:
            mock_check_versions.return_value = True
            self.db_cmds._check_versions()
            mock_check_versions.assert_called_once_with()

    def test__check_versions_bad(self):
        with mock.patch.object(self.dbapi, 'check_versions',
                               autospec=True) as mock_check_versions:
            mock_check_versions.return_value = False
            exit = self.assertRaises(SystemExit, self.db_cmds._check_versions)
            mock_check_versions.assert_called_once_with()
            self.assertEqual(2, exit.code)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions(self, mock_migrations):
        mock_func = mock.MagicMock(side_effect=((15, 15),), __name__='foo')
        mock_migrations.__iter__.return_value = (mock_func,)
        self.assertTrue(
            self.db_cmds._run_migration_functions(self.context, 50))
        mock_func.assert_called_once_with(self.context, 50)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_none(self, mock_migrations):
        # No migration functions to run
        mock_migrations.__iter__.return_value = ()
        self.assertTrue(
            self.db_cmds._run_migration_functions(self.context, 50))

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_exception(self, mock_migrations):
        # Migration function raises exception
        mock_func = mock.MagicMock(side_effect=TypeError("bar"),
                                   __name__='foo')
        mock_migrations.__iter__.return_value = (mock_func,)
        self.assertRaises(TypeError, self.db_cmds._run_migration_functions,
                          self.context, 50)
        mock_func.assert_called_once_with(self.context, 50)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_2(self, mock_migrations):
        # 2 migration functions, migration completed
        mock_func1 = mock.MagicMock(side_effect=((15, 15),), __name__='func1')
        mock_func2 = mock.MagicMock(side_effect=((20, 20),), __name__='func2')
        mock_migrations.__iter__.return_value = (mock_func1, mock_func2)
        self.assertTrue(
            self.db_cmds._run_migration_functions(self.context, 50))
        mock_func1.assert_called_once_with(self.context, 50)
        mock_func2.assert_called_once_with(self.context, 35)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_2_notdone(self, mock_migrations):
        # 2 migration functions; only first function was run but not completed
        mock_func1 = mock.MagicMock(side_effect=((15, 10),), __name__='func1')
        mock_func2 = mock.MagicMock(side_effect=((20, 0),), __name__='func2')
        mock_migrations.__iter__.return_value = (mock_func1, mock_func2)
        self.assertFalse(
            self.db_cmds._run_migration_functions(self.context, 10))
        mock_func1.assert_called_once_with(self.context, 10)
        self.assertFalse(mock_func2.called)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_2_onedone(self, mock_migrations):
        # 2 migration functions; only first function was run and completed
        mock_func1 = mock.MagicMock(side_effect=((10, 10),), __name__='func1')
        mock_func2 = mock.MagicMock(side_effect=((20, 0),), __name__='func2')
        mock_migrations.__iter__.return_value = (mock_func1, mock_func2)
        self.assertFalse(
            self.db_cmds._run_migration_functions(self.context, 10))
        mock_func1.assert_called_once_with(self.context, 10)
        self.assertFalse(mock_func2.called)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_2_done(self, mock_migrations):
        # 2 migration functions; migrations completed
        mock_func1 = mock.MagicMock(side_effect=((10, 10),), __name__='func1')
        mock_func2 = mock.MagicMock(side_effect=((0, 0),), __name__='func2')
        mock_migrations.__iter__.return_value = (mock_func1, mock_func2)
        self.assertTrue(
            self.db_cmds._run_migration_functions(self.context, 15))
        mock_func1.assert_called_once_with(self.context, 15)
        mock_func2.assert_called_once_with(self.context, 5)

    @mock.patch.object(dbsync, 'ONLINE_MIGRATIONS', autospec=True)
    def test__run_migration_functions_two_calls_done(self, mock_migrations):
        # 2 migration functions; migrations completed after calling twice
        mock_func1 = mock.MagicMock(side_effect=((10, 10), (0, 0)),
                                    __name__='func1')
        mock_func2 = mock.MagicMock(side_effect=((0, 0), (0, 0)),
                                    __name__='func2')
        mock_migrations.__iter__.return_value = (mock_func1, mock_func2)
        self.assertFalse(
            self.db_cmds._run_migration_functions(self.context, 10))
        mock_func1.assert_called_once_with(self.context, 10)
        self.assertFalse(mock_func2.called)
        self.assertTrue(
            self.db_cmds._run_migration_functions(self.context, 10))
        mock_func1.assert_has_calls((mock.call(self.context, 10),) * 2)
        mock_func2.assert_called_once_with(self.context, 10)

    @mock.patch.object(dbsync.DBCommand, '_run_migration_functions',
                       autospec=True)
    def test__run_online_data_migrations(self, mock_functions):
        mock_functions.return_value = True
        exit = self.assertRaises(SystemExit,
                                 self.db_cmds._run_online_data_migrations)
        self.assertEqual(0, exit.code)
        mock_functions.assert_called_once_with(self.db_cmds, mock.ANY, 50)

    @mock.patch.object(dbsync.DBCommand, '_run_migration_functions',
                       autospec=True)
    def test__run_online_data_migrations_batches(self, mock_functions):
        mock_functions.side_effect = (False, True)
        exit = self.assertRaises(SystemExit,
                                 self.db_cmds._run_online_data_migrations)
        self.assertEqual(0, exit.code)
        mock_functions.assert_has_calls(
            (mock.call(self.db_cmds, mock.ANY, 50),) * 2)

    @mock.patch.object(dbsync.DBCommand, '_run_migration_functions',
                       autospec=True)
    def test__run_online_data_migrations_notdone(self, mock_functions):
        mock_functions.return_value = False
        exit = self.assertRaises(SystemExit,
                                 self.db_cmds._run_online_data_migrations,
                                 max_count=30)
        self.assertEqual(1, exit.code)
        mock_functions.assert_called_once_with(self.db_cmds, mock.ANY, 30)

    @mock.patch.object(dbsync.DBCommand, '_run_migration_functions',
                       autospec=True)
    def test__run_online_data_migrations_max_count_neg(self, mock_functions):
        mock_functions.return_value = False
        exit = self.assertRaises(SystemExit,
                                 self.db_cmds._run_online_data_migrations,
                                 max_count=-4)
        self.assertEqual(127, exit.code)
        self.assertFalse(mock_functions.called)

    @mock.patch.object(dbsync.DBCommand, '_run_migration_functions',
                       autospec=True)
    def test__run_online_data_migrations_exception(self, mock_functions):
        mock_functions.side_effect = TypeError("yuck")
        self.assertRaises(TypeError, self.db_cmds._run_online_data_migrations)
        mock_functions.assert_called_once_with(self.db_cmds, mock.ANY, 50)
