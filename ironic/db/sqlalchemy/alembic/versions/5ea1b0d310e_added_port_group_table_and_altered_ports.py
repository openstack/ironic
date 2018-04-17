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

"""Added portgroups table and altered ports

Revision ID: 5ea1b0d310e
Revises: 48d6c242bb9b
Create Date: 2015-06-30 14:14:26.972368

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5ea1b0d310e'
down_revision = '48d6c242bb9b'


def upgrade():
    op.create_table('portgroups',
                    sa.Column('created_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('uuid', sa.String(length=36), nullable=True),
                    sa.Column('name', sa.String(length=255), nullable=True),
                    sa.Column('node_id', sa.Integer(), nullable=True),
                    sa.Column('address', sa.String(length=18), nullable=True),
                    sa.Column('extra', sa.Text(), nullable=True),
                    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('uuid', name='uniq_portgroups0uuid'),
                    sa.UniqueConstraint('address',
                                        name='uniq_portgroups0address'),
                    sa.UniqueConstraint('name', name='uniq_portgroups0name'),
                    mysql_ENGINE='InnoDB',
                    mysql_DEFAULT_CHARSET='UTF8')
    op.add_column(u'ports', sa.Column('local_link_connection', sa.Text(),
                                      nullable=True))
    op.add_column(u'ports', sa.Column('portgroup_id', sa.Integer(),
                                      nullable=True))
    op.add_column(u'ports', sa.Column('pxe_enabled', sa.Boolean(),
                                      default=True))
    op.create_foreign_key('fk_portgroups_ports', 'ports', 'portgroups',
                          ['portgroup_id'], ['id'])
