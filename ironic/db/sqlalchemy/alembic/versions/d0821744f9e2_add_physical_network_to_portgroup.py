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

"""add physical_network attribute to portgroup object

Revision ID: d0821744f9e2
Revises: 3ef27505c9fb
Create Date: 2025-07-22 19:17:52.446170

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd0821744f9e2'
down_revision = '3ef27505c9fb'


def upgrade():
    op.add_column('portgroups', sa.Column('physical_network',
                                          sa.String(length=64), nullable=True))
