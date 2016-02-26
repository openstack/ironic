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

"""Add volume_targets table

Revision ID: 1a59178ebdf6
Revises: daa1ba02d98
Create Date: 2016-02-25 11:25:29.836535

"""

# revision identifiers, used by Alembic.
revision = '1a59178ebdf6'
down_revision = 'daa1ba02d98'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('volume_targets',
                    sa.Column('created_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('uuid', sa.String(length=36), nullable=True),
                    sa.Column('node_id', sa.Integer(), nullable=True),
                    sa.Column('volume_type', sa.String(length=64),
                              nullable=True),
                    sa.Column('properties', sa.Text(), nullable=True),
                    sa.Column('boot_index', sa.Integer(), nullable=True),
                    sa.Column('volume_id',
                              sa.String(length=36), nullable=True),
                    sa.Column('extra', sa.Text(), nullable=True),
                    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('node_id', 'boot_index',
                                        name='uniq_volumetargets0node_id0'
                                             'boot_index'),
                    sa.UniqueConstraint('uuid',
                                        name='uniq_volumetargets0uuid'),
                    mysql_charset='utf8',
                    mysql_engine='InnoDB')
