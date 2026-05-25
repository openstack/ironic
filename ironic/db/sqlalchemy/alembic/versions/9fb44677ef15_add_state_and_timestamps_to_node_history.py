# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from alembic import op
import sqlalchemy as sa

"""add_state_and_timestamps_to_node_history

Revision ID: 9fb44677ef15
Revises: 772c0e7e8299
Create Date: 2026-05-25 15:55:17.779109

"""

# revision identifiers, used by Alembic.
revision = '9fb44677ef15'
down_revision = '772c0e7e8299'


def upgrade():
    op.add_column('node_history',
                  sa.Column('state',
                            sa.String(255),
                            nullable=True))
    op.add_column('node_history',
                  sa.Column('target_provision_state',
                            sa.String(255),
                            nullable=True))
    op.add_column('node_history',
                  sa.Column('duration_seconds',
                            sa.Integer(),
                            nullable=True))
