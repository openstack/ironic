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

from alembic import op
import sqlalchemy as sa

"""set upper_bound and lower_bound to bigint

Revision ID: 9c0446cb6bc3
Revises: 9f8c7d6e5b4a
Create Date: 2025-10-24 13:30:47.070830

"""

# revision identifiers, used by Alembic.
revision = '9c0446cb6bc3'
down_revision = '9f8c7d6e5b4a'


def upgrade():
    op.alter_column('bios_settings', 'upper_bound', existing_type=sa.Integer(),
                    type_=sa.BigInteger(), existing_nullable=True)
    op.alter_column('bios_settings', 'lower_bound', existing_type=sa.Integer(),
                    type_=sa.BigInteger(), existing_nullable=True)
