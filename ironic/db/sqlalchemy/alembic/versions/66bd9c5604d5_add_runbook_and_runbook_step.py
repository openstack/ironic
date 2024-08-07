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

"""Create runbooks and runbook_steps tables

Revision ID: 66bd9c5604d5
Revises: 01f21d5e5195
Create Date: 2024-05-29 19:33:53.268794

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '66bd9c5604d5'
down_revision = '01f21d5e5195'


def upgrade():
    op.create_table(
        'runbooks',
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False,
                  autoincrement=True),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('disable_ramdisk', sa.Boolean, default=False),
        sa.Column('public', sa.Boolean, default=False),
        sa.Column('owner', sa.String(length=255), nullable=True),
        sa.Column('extra', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid', name='uniq_runbooks0uuid'),
        sa.UniqueConstraint('name', name='uniq_runbooks0name'),
        mysql_engine='InnoDB',
        mysql_charset='UTF8MB3'
    )
    op.create_table(
        'runbook_steps',
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False,
                  autoincrement=True),
        sa.Column('runbook_id', sa.Integer(), nullable=False,
                  autoincrement=False),
        sa.Column('interface', sa.String(length=255), nullable=False),
        sa.Column('step', sa.String(length=255), nullable=False),
        sa.Column('args', sa.Text, nullable=False),
        sa.Column('order', sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['runbook_id'],
                                ['runbooks.id']),
        sa.Index('runbook_id', 'runbook_id'),
        sa.Index('runbook_steps_interface_idx', 'interface'),
        sa.Index('runbook_steps_step_idx', 'step'),
        mysql_engine='InnoDB',
        mysql_charset='UTF8MB3'
    )
