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

"""add bios interface

Revision ID: 2d13bc3d6bba
Revises: 82c315d60161
Create Date: 2017-09-27 14:42:42.107321

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2d13bc3d6bba'
down_revision = '82c315d60161'


def upgrade():
    op.add_column('nodes', sa.Column('bios_interface',
                                     sa.String(length=255), nullable=True))
