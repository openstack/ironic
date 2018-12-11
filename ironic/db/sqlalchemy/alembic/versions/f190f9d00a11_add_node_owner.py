# All Rights Reserved.
#
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
"""add_node_owner

Revision ID: f190f9d00a11
Revises: 93706939026c
Create Date: 2018-11-12 00:33:58.575100

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f190f9d00a11'
down_revision = '93706939026c'


def upgrade():
    op.add_column('nodes', sa.Column('owner', sa.String(255),
                                     nullable=True))
