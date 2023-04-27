# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg
from oslo_db.sqlalchemy import enginefacade
from sqlalchemy.engine import Engine
from sqlalchemy import event

CONF = cfg.CONF

# FIXME(stephenfin): we need to remove reliance on autocommit semantics ASAP
# since it's not compatible with SQLAlchemy 2.0
# NOTE(dtantsur): we want sqlite as close to a real database as possible.
enginefacade.configure(sqlite_fk=True, __autocommit=True)


# NOTE(TheJulia): Setup a listener to trigger the sqlite write-ahead
# log to be utilized to permit concurrent access, which is needed
# as we can get read requests while we are writing via the API
# surface *when* we're using sqlite as the database backend.
@event.listens_for(Engine, "connect")
def _setup_journal_mode(dbapi_connection, connection_record):
    # NOTE(TheJulia): The string may not be loaded in some unit
    # tests so handle whatever the output is as a string so we
    # can lower/compare it and send the appropriate command to
    # the database.
    if 'sqlite' in str(CONF.database.connection).lower():
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
