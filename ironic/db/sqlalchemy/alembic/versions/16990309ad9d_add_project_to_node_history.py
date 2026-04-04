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
"""add project to node_history table

Revision ID: 16990309ad9d
Revises: 2a3b4c5d6e7f
Create Date: 2026-04-04 11:12:09.086869
"""
from alembic import op
import sqlalchemy as sa

# rev identifiers, used by Alembic.
revision = '16990309ad9d'
down_revision = 'e2d316b60d9e'

def upgrade():
    op.add_column('node_history',
                  sa.Column('project', sa.String(length=80), nullable=True))
