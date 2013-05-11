# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
from sqlalchemy import Table, Column, Index, ForeignKey, MetaData
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text

from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

ENGINE='InnoDB'
CHARSET='utf8'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('nodes', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36)),
        Column('power_info', Text),
        Column('cpu_arch', String(length=10)),
        Column('cpu_num', Integer),
        Column('memory', Integer),
        Column('local_storage_max', Integer),
        Column('task_state', String(length=255)),
        Column('image_path', String(length=255), nullable=True),
        Column('instance_uuid', String(length=255), nullable=True),
        Column('instance_name', String(length=255), nullable=True),
        Column('extra', Text),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        mysql_engine=ENGINE,
        mysql_charset=CHARSET,
    )

    ifaces = Table('ifaces', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=18)),
        Column('node_id', Integer, ForeignKey('nodes.id'),
            nullable=True),
        Column('extra', Text),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        mysql_engine=ENGINE,
        mysql_charset=CHARSET,
    )

    tables = [nodes, ifaces]
    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.Exception(_('Exception while creating table.'))
            raise

    indexes = [
        Index('node_cpu_mem_disk', nodes.c.cpu_num,
                nodes.c.memory, nodes.c.local_storage_max),
        Index('node_instance_uuid', nodes.c.instance_uuid),
    ]

    uniques = [
        UniqueConstraint('uuid', table=nodes,
                            name='node_uuid_ux'),
        UniqueConstraint('address', table=ifaces,
                            name='iface_address_ux'),
    ]

    if migrate_engine.name == 'mysql' or migrate_engine.name == 'postgresql':
        for index in indexes:
            index.create(migrate_engine)
        for index in uniques:
            index.create(migrate_engine)


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from Folsom is unsupported.')
