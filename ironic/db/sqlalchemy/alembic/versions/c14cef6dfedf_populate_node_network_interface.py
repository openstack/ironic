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

"""Populate node.network_interface

Revision ID: c14cef6dfedf
Revises: dd34e1f1303b
Create Date: 2016-08-01 14:05:24.197314

"""

from alembic import op
from sqlalchemy import String
from sqlalchemy.sql import table, column, null

from ironic.conf import CONF

# revision identifiers, used by Alembic.
revision = 'c14cef6dfedf'
down_revision = 'dd34e1f1303b'


node = table('nodes',
             column('uuid', String(36)),
             column('network_interface', String(255)))


def upgrade():
    network_iface = (CONF.default_network_interface
                     or ('flat' if CONF.dhcp.dhcp_provider == 'neutron'
                         else 'noop'))
    op.execute(
        node.update().where(
            node.c.network_interface == null()).values(
                {'network_interface': network_iface}))
