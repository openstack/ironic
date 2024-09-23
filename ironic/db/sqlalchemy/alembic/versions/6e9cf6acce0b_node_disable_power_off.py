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

"""node disable_power_off

Revision ID: 6e9cf6acce0b
Revises: 66bd9c5604d5
Create Date: 2024-09-23 17:54:49.101988

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '6e9cf6acce0b'
down_revision = '66bd9c5604d5'


def upgrade():
    op.add_column('nodes', sa.Column('disable_power_off', sa.Boolean(),
                                     nullable=True, server_default=sa.false()))
