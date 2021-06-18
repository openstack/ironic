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

"""add boot_mode and secure_boot

Revision ID: c1846a214450
Revises: 2bbd96b6ccb9
Create Date: 2021-06-21 15:57:37.330442

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c1846a214450'
down_revision = '2bbd96b6ccb9'


def upgrade():
    op.add_column('nodes', sa.Column('boot_mode',
                  sa.String(length=16), nullable=True))
    op.add_column('nodes', sa.Column('secure_boot',
                  sa.Boolean(), nullable=True))
