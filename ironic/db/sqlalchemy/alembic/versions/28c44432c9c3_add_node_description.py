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

"""add node description

Revision ID: 28c44432c9c3
Revises: dd67b91a1981
Create Date: 2019-01-23 13:54:08.850421

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '28c44432c9c3'
down_revision = '9cbeefa3763f'


def upgrade():
    op.add_column('nodes', sa.Column('description', sa.Text(),
                                     nullable=True))
