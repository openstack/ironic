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

"""add inspection_started_at and inspection_finished_at

Revision ID: 1e1d5ace7dc6
Revises: 3ae36a5f5131
Create Date: 2015-02-26 10:46:46.861927

"""

# revision identifiers, used by Alembic.
revision = '1e1d5ace7dc6'
down_revision = '3ae36a5f5131'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('nodes', sa.Column('inspection_started_at',
                                     sa.DateTime(),
                                     nullable=True))
    op.add_column('nodes', sa.Column('inspection_finished_at',
                                     sa.DateTime(),
                                     nullable=True))
