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

"""add_logical_name

Revision ID: 3ae36a5f5131
Revises: bb59b63f55a
Create Date: 2014-12-10 14:27:26.323540

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3ae36a5f5131'
down_revision = 'bb59b63f55a'


def upgrade():
    op.add_column('nodes', sa.Column('name', sa.String(length=63),
                  nullable=True))
    op.create_unique_constraint('uniq_nodes0name', 'nodes', ['name'])
