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

"""add conductor_group to nodes/conductors

Revision ID: 664f85c2f622
Revises: fb3f10dd262e
Create Date: 2018-07-02 13:21:54.847245

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '664f85c2f622'
down_revision = 'b9117ac17882'


def upgrade():
    op.add_column('conductors', sa.Column('conductor_group',
                  sa.String(length=255), server_default='', nullable=False))
    op.add_column('nodes', sa.Column('conductor_group', sa.String(length=255),
                  server_default='', nullable=False))
