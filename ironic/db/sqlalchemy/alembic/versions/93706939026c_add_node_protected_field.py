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

"""Add Node.protected field

Revision ID: 93706939026c
Revises: d2b036ae9378
Create Date: 2018-10-18 14:55:12.489170

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '93706939026c'
down_revision = 'd2b036ae9378'


def upgrade():
    op.add_column('nodes', sa.Column('protected', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column('nodes', sa.Column('protected_reason', sa.Text(),
                                     nullable=True))
