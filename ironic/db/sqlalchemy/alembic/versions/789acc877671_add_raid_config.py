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

"""Add node.raid_config and node.target_raid_config

Revision ID: 789acc877671
Revises: 2fb93ffd2af1
Create Date: 2015-06-26 01:21:46.062311

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '789acc877671'
down_revision = '2fb93ffd2af1'


def upgrade():
    op.add_column('nodes', sa.Column('raid_config', sa.Text(),
                  nullable=True))
    op.add_column('nodes', sa.Column('target_raid_config', sa.Text(),
                  nullable=True))
