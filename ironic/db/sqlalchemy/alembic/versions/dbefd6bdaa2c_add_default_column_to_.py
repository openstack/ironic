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

"""Add default column to ConductorHardwareInterfaces

Revision ID: dbefd6bdaa2c
Revises: 2353895ecfae
Create Date: 2017-01-17 15:28:04.653738

"""

# revision identifiers, used by Alembic.
revision = 'dbefd6bdaa2c'
down_revision = '2353895ecfae'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('conductor_hardware_interfaces', sa.Column('default',
                                                             sa.Boolean,
                                                             nullable=False,
                                                             default=False))
