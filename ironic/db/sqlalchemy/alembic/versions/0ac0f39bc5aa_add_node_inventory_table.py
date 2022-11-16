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


"""add node inventory table

Revision ID: 0ac0f39bc5aa
Revises: 9ef41f07cb58
Create Date: 2022-10-25 17:15:38.181544

"""

from alembic import op
from oslo_db.sqlalchemy import types as db_types
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0ac0f39bc5aa'
down_revision = '9ef41f07cb58'


def upgrade():
    op.create_table('node_inventory',
                    sa.Column('version', sa.String(length=15), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('inventory_data', db_types.JsonEncodedDict(
                        mysql_as_long=True).impl, nullable=True),
                    sa.Column('plugin_data', db_types.JsonEncodedDict(
                        mysql_as_long=True).impl, nullable=True),
                    sa.Column('node_id', sa.Integer(), nullable=True),
                    sa.PrimaryKeyConstraint('id'),
                    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
                    sa.Index('inventory_node_id_idx', 'node_id'),
                    mysql_engine='InnoDB',
                    mysql_charset='UTF8MB3')
