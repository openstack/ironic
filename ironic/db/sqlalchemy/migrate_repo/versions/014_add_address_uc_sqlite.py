# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        meta = MetaData(bind=migrate_engine)
        ports = Table('ports', meta, autoload=True)

        uniques = (
            UniqueConstraint('address', table=ports, name='iface_address_ux'),
            # NOTE(yuriyz): this migration can drop first UC in 'ports' table
            # for sqlite backend (sqlalchemy-migrate bug), recreate it
            UniqueConstraint('uuid', table=ports, name='port_uuid_ux')
            )

        for uc in uniques:
            uc.create()


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from version 014 is unsupported.')
