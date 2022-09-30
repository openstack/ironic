# Copyright (c) 2018 NEC, Corp.
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

from unittest import mock

from oslo_db import sqlalchemy
from oslo_upgradecheck.upgradecheck import Code

from ironic.cmd import dbsync
from ironic.cmd import status
from ironic.tests.unit.db import base as db_base


class TestUpgradeChecks(db_base.DbTestCase):

    def setUp(self):
        super(TestUpgradeChecks, self).setUp()
        self.cmd = status.Checks()

    def test__check_obj_versions(self):
        check_result = self.cmd._check_obj_versions()
        self.assertEqual(Code.SUCCESS, check_result.code)

    @mock.patch.object(dbsync.DBCommand, 'check_obj_versions', autospec=True)
    def test__check_obj_versions_bad(self, mock_check):
        msg = 'This is bad'
        mock_check.return_value = msg
        check_result = self.cmd._check_obj_versions()
        self.assertEqual(Code.FAILURE, check_result.code)
        self.assertEqual(msg, check_result.details)

    def test__check_allocations_table_ok(self):
        check_result = self.cmd._check_allocations_table()
        self.assertEqual(Code.SUCCESS,
                         check_result.code)

    @mock.patch.object(sqlalchemy.enginefacade.reader,
                       'get_engine', autospec=True)
    def test__check_allocations_table_latin1(self, mock_reader):
        mock_engine = mock.Mock()
        mock_res = mock.Mock()
        mock_res.all.return_value = (
            '... ENGINE=InnoDB DEFAULT CHARSET=latin1',
        )
        mock_engine.url = '..mysql..'
        mock_engine.execute.return_value = mock_res
        mock_reader.return_value = mock_engine
        check_result = self.cmd._check_allocations_table()
        self.assertEqual(Code.WARNING,
                         check_result.code)
        expected_msg = ('The Allocations table is is not using UTF8 '
                        'encoding. This is corrected in later versions '
                        'of Ironic, where the table character set schema '
                        'is automatically migrated. Continued use of a '
                        'non-UTF8 character set may produce unexpected '
                        'results.')
        self.assertEqual(expected_msg, check_result.details)

    @mock.patch.object(sqlalchemy.enginefacade.reader,
                       'get_engine', autospec=True)
    def test__check_allocations_table_myiasm(self, mock_reader):
        mock_engine = mock.Mock()
        mock_res = mock.Mock()
        mock_engine.url = '..mysql..'
        mock_res.all.return_value = (
            '... ENGINE=MyIASM DEFAULT CHARSET=utf8',
        )
        mock_engine.execute.return_value = mock_res
        mock_reader.return_value = mock_engine
        check_result = self.cmd._check_allocations_table()
        self.assertEqual(Code.WARNING,
                         check_result.code)
        expected_msg = ('The engine used by MySQL for the allocations '
                        'table is not the intended engine for the Ironic '
                        'database tables to use. This may have been a '
                        'result of an error with the table creation schema. '
                        'This may require Database Administrator '
                        'intervention and downtime to dump, modify the '
                        'table engine to utilize InnoDB, and reload the '
                        'allocations table to utilize the InnoDB engine.')
        self.assertEqual(expected_msg, check_result.details)

    @mock.patch.object(sqlalchemy.enginefacade.reader,
                       'get_engine', autospec=True)
    def test__check_allocations_table_myiasm_both(self, mock_reader):
        mock_engine = mock.Mock()
        mock_res = mock.Mock()
        mock_engine.url = '..mysql..'
        mock_res.all.return_value = (
            '... ENGINE=MyIASM DEFAULT CHARSET=latin1',
        )
        mock_engine.execute.return_value = mock_res
        mock_reader.return_value = mock_engine
        check_result = self.cmd._check_allocations_table()
        self.assertEqual(Code.WARNING,
                         check_result.code)
        expected_msg = ('The Allocations table is is not using UTF8 '
                        'encoding. This is corrected in later versions '
                        'of Ironic, where the table character set schema '
                        'is automatically migrated. Continued use of a '
                        'non-UTF8 character set may produce unexpected '
                        'results. Additionally: '
                        'The engine used by MySQL for the allocations '
                        'table is not the intended engine for the Ironic '
                        'database tables to use. This may have been a '
                        'result of an error with the table creation schema. '
                        'This may require Database Administrator '
                        'intervention and downtime to dump, modify the '
                        'table engine to utilize InnoDB, and reload the '
                        'allocations table to utilize the InnoDB engine.')
        self.assertEqual(expected_msg, check_result.details)
