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
"""create node.shard

Revision ID: 4dbec778866e
Revises: 0ac0f39bc5aa
Create Date: 2022-11-10 14:20:59.175355

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4dbec778866e'
down_revision = '0ac0f39bc5aa'


def upgrade():
    op.add_column('nodes', sa.Column('shard', sa.String(length=255),
                                     nullable=True))
    op.create_index('shard_idx', 'nodes', ['shard'], unique=False)
