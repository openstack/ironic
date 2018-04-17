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

"""add-node-network-interface

Revision ID: e294876e8028
Revises: f6fdb920c182
Create Date: 2016-03-02 14:30:54.402864

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e294876e8028'
down_revision = 'f6fdb920c182'


def upgrade():
    op.add_column('nodes', sa.Column('network_interface', sa.String(255),
                                     nullable=True))
