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

"""add port portgroup internal info

Revision ID: 10b163d4481e
Revises: e294876e8028
Create Date: 2016-07-06 17:43:55.846837

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '10b163d4481e'
down_revision = 'e294876e8028'


def upgrade():
    op.add_column('ports', sa.Column('internal_info',
                                     sa.Text(),
                                     nullable=True))
    op.add_column('portgroups', sa.Column('internal_info',
                                          sa.Text(),
                                          nullable=True))
