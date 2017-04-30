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

"""add port physical network

Revision ID: 3d86a077a3f2
Revises: dbefd6bdaa2c
Create Date: 2017-04-30 17:11:49.384851

"""

# revision identifiers, used by Alembic.
revision = '3d86a077a3f2'
down_revision = 'dbefd6bdaa2c'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('ports', sa.Column('physical_network',
                                     sa.String(64),
                                     nullable=True))
