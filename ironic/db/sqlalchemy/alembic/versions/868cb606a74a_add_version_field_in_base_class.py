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

"""add version field in base class

Revision ID: 868cb606a74a
Revises: 3d86a077a3f2
Create Date: 2016-12-15 12:31:31.629237

"""

# revision identifiers, used by Alembic.
revision = '868cb606a74a'
down_revision = '3d86a077a3f2'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # NOTE(rloo): In db.sqlalchemy.models, we added the 'version' column
    #             to IronicBase class. All inherited classes/tables have
    #             this new column.
    op.add_column('chassis',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('conductors',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('node_tags',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('nodes',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('portgroups',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('ports',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('volume_connectors',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('volume_targets',
                  sa.Column('version', sa.String(length=15), nullable=True))
    op.add_column('conductor_hardware_interfaces',
                  sa.Column('version', sa.String(length=15), nullable=True))
