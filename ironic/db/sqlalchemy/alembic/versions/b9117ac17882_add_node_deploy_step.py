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

"""add deploy_step to node

Revision ID: b9117ac17882
Revises: fb3f10dd262e
Create Date: 2018-06-19 22:31:45.668156

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b9117ac17882'
down_revision = 'fb3f10dd262e'


def upgrade():
    op.add_column('nodes', sa.Column('deploy_step', sa.Text(),
                                     nullable=True))
