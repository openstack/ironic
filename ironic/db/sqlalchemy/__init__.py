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

from oslo_db.sqlalchemy import enginefacade

# FIXME(stephenfin): we need to remove reliance on autocommit semantics ASAP
# since it's not compatible with SQLAlchemy 2.0
# NOTE(dtantsur): we want sqlite as close to a real database as possible.
enginefacade.configure(sqlite_fk=True, __autocommit=True)
