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

"""Add inspection rules

Revision ID: 21c48150dea9
Revises: 66bd9c5604d5
Create Date: 2024-08-14 14:13:24.462303

"""

from alembic import op
from oslo_db.sqlalchemy import types
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '21c48150dea9'
down_revision = '6e9cf6acce0b'


def upgrade():
    op.create_table(
        'inspection_rules',
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False,
                  autoincrement=True),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, default=0),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('scope', sa.String(255), nullable=True),
        sa.Column('sensitive', sa.Boolean(), default=False),
        sa.Column('phase', sa.String(16), nullable=True),
        sa.Column('conditions', types.JsonEncodedList(mysql_as_long=True),
                  nullable=True),
        sa.Column('actions', types.JsonEncodedList(mysql_as_long=True),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid', name='uniq_inspection_rules0uuid'),
        sa.Index('inspection_rule_scope_idx', 'scope'),
        sa.Index('inspection_rule_phase_idx', 'phase'),
        mysql_ENGINE='InnoDB',
        mysql_DEFAULT_CHARSET='UTF8'
    )
