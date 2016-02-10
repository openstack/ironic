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

"""add conductor_affinity and online

Revision ID: 487deb87cc9d
Revises: 3bea56f25597
Create Date: 2014-09-26 16:16:30.988900

"""

# revision identifiers, used by Alembic.
revision = '487deb87cc9d'
down_revision = '3bea56f25597'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        'conductors',
        sa.Column('online', sa.Boolean(), default=True))
    op.add_column(
        'nodes',
        sa.Column('conductor_affinity', sa.Integer(),
                  sa.ForeignKey('conductors.id',
                                name='nodes_conductor_affinity_fk'),
                  nullable=True))
