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

"""add category attribute to portgroup object

Revision ID: 763b2f62d215
Revises: d0821744f9e2
Create Date: 2025-07-23 20:52:17.341663

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '763b2f62d215'
down_revision = 'd0821744f9e2'


def upgrade():
    op.add_column('portgroups', sa.Column('category', sa.String(length=80),
                                          nullable=True))
