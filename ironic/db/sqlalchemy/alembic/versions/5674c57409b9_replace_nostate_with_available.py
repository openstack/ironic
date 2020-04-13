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

"""replace NOSTATE with AVAILABLE

Revision ID: 5674c57409b9
Revises: 242cc6a923b3
Create Date: 2015-01-14 16:55:44.718196

"""

from alembic import op
from sqlalchemy import String
from sqlalchemy.sql import table, column, null

# revision identifiers, used by Alembic.
revision = '5674c57409b9'
down_revision = '242cc6a923b3'

node = table('nodes',
             column('uuid', String(36)),
             column('provision_state', String(15)))


# NOTE(tenbrae): We must represent the states as static strings in this
# migration file, rather than import ironic.common.states, because that file
# may change in the future. This migration script must still be able to be
# run with future versions of the code and still produce the same results.
AVAILABLE = 'available'


def upgrade():
    op.execute(
        node.update().where(
            node.c.provision_state == null()).values(
                {'provision_state': op.inline_literal(AVAILABLE)}))
