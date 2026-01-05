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

"""add node health field

Revision ID: 9f8c7d6e5b4a
Revises: 15e9d00367b0
Create Date: 2025-11-11 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9f8c7d6e5b4a'
down_revision = '15e9d00367b0'


def upgrade():
    op.add_column('nodes', sa.Column('health', sa.String(length=32),
                                     nullable=True))
