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

"""Adds indexes to important and commonly matched columns.

Revision ID: ac00b586ab95
Revises: c0455649680c
Create Date: 2021-04-27 20:27:31.469188

"""

from alembic import op
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import utils

# revision identifiers, used by Alembic.
revision = 'ac00b586ab95'
down_revision = 'c0455649680c'


def upgrade():
    engine = enginefacade.reader.get_engine()
    tbl_name = 'nodes'

    indexes = [(['reservation'], 'reservation_idx'),
               (['driver'], 'driver_idx'),
               (['owner'], 'owner_idx'),
               (['lessee'], 'lessee_idx'),
               (['provision_state'], 'provision_state_idx'),
               (['conductor_group'], 'conductor_group_idx'),
               (['resource_class'], 'resource_class_idx')]

    if engine.dialect.name == 'mysql':
        for fields, idx_name in indexes:
            if not utils.index_exists(engine, tbl_name, idx_name):
                op.create_index(idx_name, tbl_name, fields, unique=False)
    else:
        for fields, idx_name in indexes:
            op.create_index(idx_name, tbl_name, fields, unique=False)
