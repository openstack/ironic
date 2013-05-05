# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Bare-metal DB test base class."""

from oslo.config import cfg

from ironic import context as ironic_context
from ironic import test
from ironic.db import migration as db_migration
from ironic.openstack.common.db.sqlalchemy import session as db_session

_DB_CACHE = None

CONF = cfg.CONF
CONF.import_opt('sql_connection',
                'ironic.openstack.common.db.sqlalchemy.session')


class Database(test.Database):

    def post_migrations(self):
        pass


class BMDBTestCase(test.TestCase):

    def setUp(self):
        super(BMDBTestCase, self).setUp()
        self.flags(sql_connection='sqlite://')
        global _DB_CACHE
        if not _DB_CACHE:
            _DB_CACHE = Database(db_session, db_migration,
                                 sql_connection=CONF.sql_connection,
                                 sqlite_db=None,
                                 sqlite_clean_db=None)
        self.useFixture(_DB_CACHE)
        self.context = nova_context.get_admin_context()
