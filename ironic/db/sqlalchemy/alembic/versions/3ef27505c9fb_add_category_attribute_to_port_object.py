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

"""add category attribute to port object

Revision ID: 3ef27505c9fb
Revises: e4827561979d
Create Date: 2025-07-21 01:33:47.215396

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3ef27505c9fb'
down_revision = 'e4827561979d'


def upgrade():
    op.add_column('ports', sa.Column('category', sa.String(length=80),
                                     nullable=True))
