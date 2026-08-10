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

"""add firmware identity fields

Revision ID: 772c0e7e8299
Revises: 16990309ad9d
Create Date: 2026-06-01 14:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '772c0e7e8299'
down_revision = '16990309ad9d'


def upgrade():
    op.add_column('firmware_information',
                  sa.Column('vendor', sa.String(length=255), nullable=True))
    op.add_column('firmware_information',
                  sa.Column('model', sa.String(length=255), nullable=True))
    op.add_column('firmware_information',
                  sa.Column('serial_number', sa.String(length=255),
                            nullable=True))
