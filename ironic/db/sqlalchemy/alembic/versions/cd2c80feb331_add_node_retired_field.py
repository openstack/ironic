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

"""add nodes.retired field

Revision ID: cd2c80feb331
Revises: ce6c4b3cf5a2
Create Date: 2020-01-16 12:51:13.866882

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cd2c80feb331'
down_revision = 'ce6c4b3cf5a2'


def upgrade():
    op.add_column('nodes', sa.Column('retired', sa.Boolean(), nullable=True,
                                     server_default=sa.false()))
    op.add_column('nodes', sa.Column('retired_reason', sa.Text(),
                                     nullable=True))
