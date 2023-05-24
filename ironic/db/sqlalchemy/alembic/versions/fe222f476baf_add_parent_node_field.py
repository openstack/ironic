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


from alembic import op
import sqlalchemy as sa


"""add parent_node field

Revision ID: fe222f476baf
Revises: 4dbec778866e
Create Date: 2023-04-10 11:59:29.633401

"""

# revision identifiers, used by Alembic.
revision = 'fe222f476baf'
down_revision = '4dbec778866e'


def upgrade():
    op.add_column('nodes', sa.Column('parent_node', sa.String(length=36),
                                     nullable=True))
    op.create_index(
        'parent_node_idx', 'nodes', ['parent_node'], unique=False)
