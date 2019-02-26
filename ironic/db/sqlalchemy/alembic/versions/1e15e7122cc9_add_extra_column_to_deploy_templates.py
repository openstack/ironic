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

"""add extra column to deploy_templates

Revision ID: 1e15e7122cc9
Revises: 2aac7e0872f6
Create Date: 2019-02-26 15:08:18.419157

"""

# revision identifiers, used by Alembic.
revision = '1e15e7122cc9'
down_revision = '2aac7e0872f6'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('deploy_templates',
                  sa.Column('extra', sa.Text(), nullable=True))
