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

"""add node tags

Revision ID: 48d6c242bb9b
Revises: 516faf1bb9b1
Create Date: 2015-10-08 10:07:33.779516

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '48d6c242bb9b'
down_revision = '516faf1bb9b1'


def upgrade():
    op.create_table(
        'node_tags',
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('node_id', sa.Integer(), nullable=False,
                  autoincrement=False),
        sa.Column('tag', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
        sa.PrimaryKeyConstraint('node_id', 'tag'),
        mysql_engine='InnoDB',
        mysql_charset='UTF8MB3'
    )
    op.create_index('node_tags_idx', 'node_tags', ['tag'], unique=False)
