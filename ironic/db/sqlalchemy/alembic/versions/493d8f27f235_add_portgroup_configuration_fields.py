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

"""add portgroup configuration fields

Revision ID: 493d8f27f235
Revises: 60cf717201bc
Create Date: 2016-11-15 18:09:31.362613

"""

# revision identifiers, used by Alembic.
revision = '493d8f27f235'
down_revision = '1a59178ebdf6'

from alembic import op
import sqlalchemy as sa
from sqlalchemy import sql

from ironic.conf import CONF


def upgrade():
    op.add_column('portgroups', sa.Column('properties', sa.Text(),
                                          nullable=True))
    op.add_column('portgroups', sa.Column('mode', sa.String(255)))

    portgroups = sql.table('portgroups',
                           sql.column('mode', sa.String(255)))
    op.execute(
        portgroups.update().values({'mode': CONF.default_portgroup_mode}))
