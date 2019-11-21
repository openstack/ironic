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
"""add allocation owner

Revision ID: ce6c4b3cf5a2
Revises: 1e15e7122cc9
Create Date: 2019-11-21 20:46:09.106592

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ce6c4b3cf5a2'
down_revision = '1e15e7122cc9'


def upgrade():
    op.add_column('allocations', sa.Column('owner', sa.String(255),
                                           nullable=True))
