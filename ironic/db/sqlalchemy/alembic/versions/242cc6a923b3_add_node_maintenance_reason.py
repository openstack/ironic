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

"""Add Node.maintenance_reason

Revision ID: 242cc6a923b3
Revises: 487deb87cc9d
Create Date: 2014-10-15 23:00:43.164061

"""

# revision identifiers, used by Alembic.
revision = '242cc6a923b3'
down_revision = '487deb87cc9d'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('nodes', sa.Column('maintenance_reason',
                                     sa.Text(),
                                     nullable=True))
