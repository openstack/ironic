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

"""Add provision_updated_at

Revision ID: 21b331f883ef
Revises: 2581ebaf0cb2
Create Date: 2014-02-19 13:45:30.150632

"""

# revision identifiers, used by Alembic.
revision = '21b331f883ef'
down_revision = '2581ebaf0cb2'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('nodes', sa.Column('provision_updated_at', sa.DateTime(),
                  nullable=True))
