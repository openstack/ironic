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

"""increase-node-name-length

Revision ID: 2fb93ffd2af1
Revises: 4f399b21ae71
Create Date: 2015-03-18 17:08:11.470791

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '2fb93ffd2af1'
down_revision = '4f399b21ae71'


def upgrade():
    op.alter_column('nodes', 'name',
                    existing_type=mysql.VARCHAR(length=63),
                    type_=sa.String(length=255),
                    existing_nullable=True)
