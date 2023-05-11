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

"""add firmware information

Revision ID: 163040c5513f
Revises: fe222f476baf
Create Date: 2023-05-11 14:30:46.600582

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '163040c5513f'
down_revision = 'fe222f476baf'


def upgrade():
    op.add_column('nodes', sa.Column('firmware_interface',
                  sa.String(length=255), nullable=True))
    op.create_table(
        'firmware_information',
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('component', sa.String(length=255), nullable=False),
        sa.Column('initial_version', sa.String(length=255), nullable=False),
        sa.Column('current_version', sa.String(length=255), nullable=True),
        sa.Column('last_version_flashed', sa.String(length=255),
                  nullable=True),
        sa.Column('version', sa.String(length=15), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('node_id', 'component',
                            name='uniq_nodecomponent0node_id0component'),
        mysql_ENGINE='InnoDB',
        mysql_DEFAULT_CHARSET='UTF8MB3'
    )
