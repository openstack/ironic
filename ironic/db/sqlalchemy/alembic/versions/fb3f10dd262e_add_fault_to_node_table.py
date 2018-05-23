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

"""add fault to node table

Revision ID: fb3f10dd262e
Revises: 2d13bc3d6bba
Create Date: 2018-03-23 14:10:52.142016

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fb3f10dd262e'
down_revision = '2d13bc3d6bba'


def upgrade():
    op.add_column('nodes', sa.Column('fault', sa.String(length=255),
                                     nullable=True))
