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

"""add_standalone_ports_supported_to_portgroup

Revision ID: 60cf717201bc
Revises: c14cef6dfedf
Create Date: 2016-08-25 07:00:56.662645

"""

# revision identifiers, used by Alembic.
revision = '60cf717201bc'
down_revision = 'c14cef6dfedf'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('portgroups', sa.Column('standalone_ports_supported',
                                          sa.Boolean))
