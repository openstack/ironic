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

"""Add volume_connectors table

Revision ID: daa1ba02d98
Revises: c14cef6dfedf
Create Date: 2015-11-26 17:19:22.074989

"""

# revision identifiers, used by Alembic.
revision = 'daa1ba02d98'
down_revision = 'bcdd431ba0bf'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('volume_connectors',
                    sa.Column('created_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('uuid', sa.String(length=36), nullable=True),
                    sa.Column('node_id', sa.Integer(), nullable=True),
                    sa.Column('type', sa.String(length=32), nullable=True),
                    sa.Column('connector_id', sa.String(length=255),
                              nullable=True),
                    sa.Column('extra', sa.Text(), nullable=True),
                    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('type', 'connector_id',
                                        name='uniq_volumeconnectors0type0'
                                             'connector_id'),
                    sa.UniqueConstraint('uuid',
                                        name='uniq_volumeconnectors0uuid'),
                    mysql_charset='utf8',
                    mysql_engine='InnoDB')
