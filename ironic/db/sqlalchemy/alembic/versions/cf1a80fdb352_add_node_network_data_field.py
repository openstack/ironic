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

"""Add nodes.network_data field

Revision ID: cf1a80fdb352
Revises: b2ad35726bb0
Create Date: 2020-03-20 22:41:14.163881

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cf1a80fdb352'
down_revision = 'b2ad35726bb0'


def upgrade():
    op.add_column('nodes', sa.Column('network_data', sa.Text(),
                                     nullable=True))
