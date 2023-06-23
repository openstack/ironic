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

"""Ironic DB test base class."""

import fixtures
from oslo_config import cfg
from oslo_db.sqlalchemy import enginefacade

from ironic.db import api as dbapi
from ironic.db import sqlalchemy as dbapi_parent
from ironic.db.sqlalchemy import migration
from ironic.db.sqlalchemy import models
from ironic.tests import base


CONF = cfg.CONF

_DB_CACHE = None


class Database(fixtures.Fixture):

    def __init__(self, engine, db_migrate, sql_connection):
        self.sql_connection = sql_connection
        dbapi_parent.LOAD_JOURNAL_MODE = False
        self.engine = engine
        self.engine.dispose()
        conn = self.engine.connect()
        self.setup_sqlite(db_migrate)

        self.post_migrations()
        self._DB = "".join(line for line in conn.connection.iterdump())
        self.engine.dispose()

    def setup_sqlite(self, db_migrate):
        if db_migrate.version():
            return
        models.Base.metadata.create_all(self.engine)
        db_migrate.stamp('head')

    def setUp(self):
        super(Database, self).setUp()

        conn = self.engine.connect()
        conn.connection.executescript(self._DB)
        self.addCleanup(self.engine.dispose)

    def post_migrations(self):
        """Any addition steps that are needed outside of the migrations."""


class DbTestCase(base.TestCase):

    def setUp(self):
        super(DbTestCase, self).setUp()

        self.dbapi = dbapi.get_instance()

        global _DB_CACHE
        if not _DB_CACHE:
            engine = enginefacade.writer.get_engine()
            _DB_CACHE = Database(engine, migration,
                                 sql_connection=CONF.database.connection)
        self.useFixture(_DB_CACHE)
