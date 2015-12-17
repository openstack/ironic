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

"""Nodes add console enabled

Revision ID: 3cb628139ea4
Revises: 21b331f883ef
Create Date: 2014-02-26 11:24:11.318023

"""

# revision identifiers, used by Alembic.
revision = '3cb628139ea4'
down_revision = '21b331f883ef'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('nodes', sa.Column('console_enabled', sa.Boolean))
