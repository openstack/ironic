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


"""add is_smartnic port attribute

Revision ID: 9cbeefa3763f
Revises: dd67b91a1981
Create Date: 2019-01-13 09:31:13.336479

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9cbeefa3763f'
down_revision = 'dd67b91a1981'


def upgrade():
    op.add_column('ports', sa.Column('is_smartnic', sa.Boolean(),
                                     default=False))
