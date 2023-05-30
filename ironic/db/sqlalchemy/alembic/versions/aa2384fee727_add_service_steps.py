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

"""Add service_steps

Revision ID: aa2384fee727
Revises: d163df1bab88
Create Date: 2023-05-25 11:50:05.285602

"""


from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa2384fee727'
down_revision = 'd163df1bab88'


def upgrade():
    op.add_column('nodes', sa.Column('service_step', sa.Text(),
                                     nullable=True))
