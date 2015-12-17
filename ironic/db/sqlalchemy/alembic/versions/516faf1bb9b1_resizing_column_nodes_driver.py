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

"""Resizing column nodes.driver

Revision ID: 516faf1bb9b1
Revises: 789acc877671
Create Date: 2015-08-05 13:27:31.808919

"""

# revision identifiers, used by Alembic.
revision = '516faf1bb9b1'
down_revision = '789acc877671'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.alter_column('nodes', 'driver',
                    existing_type=sa.String(length=15),
                    type_=sa.String(length=255))
