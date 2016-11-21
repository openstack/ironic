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

"""Add fields for all interfaces

Revision ID: bcdd431ba0bf
Revises: 60cf717201bc
Create Date: 2016-11-11 16:44:52.823881

"""

# revision identifiers, used by Alembic.
revision = 'bcdd431ba0bf'
down_revision = '60cf717201bc'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('nodes', sa.Column('boot_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('console_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('deploy_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('inspect_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('management_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('power_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('raid_interface',
                                     sa.String(length=255), nullable=True))
    op.add_column('nodes', sa.Column('vendor_interface',
                                     sa.String(length=255), nullable=True))
