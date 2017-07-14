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

"""Add conductor_hardware_interfaces table

Revision ID: 2353895ecfae
Revises: 1a59178ebdf6
Create Date: 2016-12-12 15:17:22.065056

"""

# revision identifiers, used by Alembic.
revision = '2353895ecfae'
down_revision = '1d6951876d68'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('conductor_hardware_interfaces',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('conductor_id', sa.Integer(), nullable=False),
                    sa.Column('hardware_type', sa.String(length=255),
                              nullable=False),
                    sa.Column('interface_type', sa.String(length=16),
                              nullable=False),
                    sa.Column('interface_name', sa.String(length=255),
                              nullable=False),
                    sa.ForeignKeyConstraint(['conductor_id'],
                                            ['conductors.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint(
                        'conductor_id', 'hardware_type',
                        'interface_type', 'interface_name',
                        name='uniq_conductorhardwareinterfaces0'),
                    mysql_charset='utf8',
                    mysql_engine='InnoDB')
