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

"""add_node_history_table

Revision ID: 9ef41f07cb58
Revises: c1846a214450
Create Date: 2020-12-20 17:45:57.278649

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9ef41f07cb58'
down_revision = 'c1846a214450'


def upgrade():
    op.create_table('node_history',
                    sa.Column('version', sa.String(length=15), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('uuid', sa.String(length=36), nullable=False),
                    sa.Column('conductor', sa.String(length=255),
                              nullable=True),
                    sa.Column('event_type', sa.String(length=255),
                              nullable=True),
                    sa.Column('severity', sa.String(length=255),
                              nullable=True),
                    sa.Column('event', sa.Text(), nullable=True),
                    sa.Column('user', sa.String(length=32), nullable=True),
                    sa.Column('node_id', sa.Integer(), nullable=True),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('uuid', name='uniq_history0uuid'),
                    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
                    sa.Index('history_node_id_idx', 'node_id'),
                    sa.Index('history_uuid_idx', 'uuid'),
                    sa.Index('history_conductor_idx', 'conductor'),
                    mysql_ENGINE='InnoDB',
                    mysql_DEFAULT_CHARSET='UTF8')
