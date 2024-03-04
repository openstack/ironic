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

"""increase-length-of-user-column

Revision ID: 01f21d5e5195
Revises: aa2384fee727
Create Date: 2024-03-05 11:02:08.996894

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '01f21d5e5195'
down_revision = 'aa2384fee727'


def upgrade():
    op.alter_column('node_history', 'user',
                    existing_type=sa.String(length=32),
                    type_=sa.String(length=64),
                    existing_nullable=True)
