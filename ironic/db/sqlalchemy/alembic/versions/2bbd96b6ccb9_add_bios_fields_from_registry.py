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

"""Add fields from BIOS registry

Revision ID: 2bbd96b6ccb9
Revises: ac00b586ab95
Create Date: 2021-04-29 08:52:23.938863

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2bbd96b6ccb9'
down_revision = 'ac00b586ab95'


def upgrade():
    op.add_column('bios_settings', sa.Column('attribute_type',
                  sa.String(length=255), nullable=True))
    op.add_column('bios_settings', sa.Column('allowable_values',
                  sa.Text(), nullable=True))
    op.add_column('bios_settings', sa.Column('lower_bound',
                  sa.Integer(), nullable=True))
    op.add_column('bios_settings', sa.Column('max_length',
                  sa.Integer(), nullable=True))
    op.add_column('bios_settings', sa.Column('min_length',
                  sa.Integer(), nullable=True))
    op.add_column('bios_settings', sa.Column('read_only',
                  sa.Boolean(), nullable=True))
    op.add_column('bios_settings', sa.Column('reset_required',
                  sa.Boolean(), nullable=True))
    op.add_column('bios_settings', sa.Column('unique',
                  sa.Boolean(), nullable=True))
    op.add_column('bios_settings', sa.Column('upper_bound',
                  sa.Integer(), nullable=True))
