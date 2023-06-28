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

"""Add Allocations table

Revision ID: dd67b91a1981
Revises: f190f9d00a11
Create Date: 2018-12-10 15:24:30.555995

"""

from alembic import op
from oslo_db.sqlalchemy import types
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'dd67b91a1981'
down_revision = 'f190f9d00a11'


def upgrade():
    op.create_table(
        'allocations',
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('node_id', sa.Integer(), nullable=True),
        sa.Column('state', sa.String(length=15), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('resource_class', sa.String(length=80), nullable=True),
        sa.Column('traits', types.JsonEncodedList(), nullable=True),
        sa.Column('candidate_nodes', types.JsonEncodedList(), nullable=True),
        sa.Column('extra', types.JsonEncodedDict(), nullable=True),
        sa.Column('conductor_affinity', sa.Integer(), nullable=True),
        # NOTE(TheJulia): Commenting these out to remove the constraints
        # as below we link nodes to allocations on a unique foreign key
        # constraint mapping, and nodes also have the same conductor affinity
        # constraint, which raises an SAWarning error as sqlalchemy cannot
        # sort the data model relationships, and expects this to become an
        # error at some point in the future. As such, since a node is
        # generally a primary object, and allocations are more secondary
        # relationship/association mapping objects, the two commented out
        # lines are redundant. We'll remove the relationships in a migration
        # as well and ignore errors if they are encountered for new installs.
        # sa.ForeignKeyConstraint(['conductor_affinity'], ['conductors.id'], ),
        # sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uniq_allocations0name'),
        sa.UniqueConstraint('uuid', name='uniq_allocations0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='UTF8MB3'

    )
    op.add_column('nodes', sa.Column('allocation_id', sa.Integer(),
                                     nullable=True))
    op.create_foreign_key(None, 'nodes', 'allocations',
                          ['allocation_id'], ['id'])
