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

"""Set Port.pxe_enabled to True if NULL

Revision ID: f6fdb920c182
Revises: 5ea1b0d310e
Create Date: 2016-02-12 16:53:21.008580

"""

# revision identifiers, used by Alembic.
revision = 'f6fdb920c182'
down_revision = '5ea1b0d310e'

from alembic import op
from sqlalchemy import Boolean, String
from sqlalchemy.sql import table, column, null

port = table('ports',
             column('uuid', String(36)),
             column('pxe_enabled', Boolean()))


def upgrade():
    op.execute(
        port.update().where(
            port.c.pxe_enabled == null()).values(
                {'pxe_enabled': True}))
