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

"""add_node_driver_internal_info

Revision ID: bb59b63f55a
Revises: 5674c57409b9
Create Date: 2015-01-28 14:28:22.212790

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'bb59b63f55a'
down_revision = '5674c57409b9'


def upgrade():
    op.add_column('nodes', sa.Column('driver_internal_info',
                                     sa.Text(),
                                     nullable=True))
