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

"""add rescue interface to nodes

Revision ID: 405cfe08f18d
Revises: 868cb606a74a
Create Date: 2017-02-01 16:32:32.098742

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '405cfe08f18d'
down_revision = '868cb606a74a'


def upgrade():
    op.add_column('nodes', sa.Column('rescue_interface',
                                     sa.String(255),
                                     nullable=True))
