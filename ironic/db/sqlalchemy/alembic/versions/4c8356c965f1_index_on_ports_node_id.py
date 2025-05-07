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
"""Add index on ports.node_id

Revision ID: 4c8356c965f1
Revises: 1c14278d6e33
Create Date: 2025-04-29 13:26:23.089464

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '4c8356c965f1'
down_revision = '1c14278d6e33'


def upgrade():
    op.create_index('ports_node_id_idx', 'ports', ['node_id'])
