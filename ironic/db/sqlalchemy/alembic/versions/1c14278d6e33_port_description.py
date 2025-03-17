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

"""port description

Revision ID: 1c14278d6e33
Revises: 21c48150dea9
Create Date: 2025-03-17 17:12:27.160796

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1c14278d6e33'
down_revision = '21c48150dea9'


def upgrade():
    op.add_column('ports', sa.Column('description', sa.String(length=255),
                                     nullable=True))
