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
from sqlalchemy import MetaData, Table, Column, Integer, String, Text, DateTime

from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

ENGINE = 'InnoDB'
CHARSET = 'utf8'


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    conductor = Table('conductors', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('hostname', String(length=255), nullable=False),
        Column('drivers', Text),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        mysql_engine=ENGINE,
        mysql_charset=CHARSET,
    )

    try:
        conductor.create()
    except Exception:
        LOG.info(repr(conductor))
        LOG.exception(_('Exception while creating table.'))
        raise

    uc = UniqueConstraint('hostname',
                          table=conductor,
                          name='uniq_conductors0hostname')
    uc.create()


def downgrade(migrate_engine):
    raise NotImplementedError(_('Downgrade from version 012 is unsupported.'))
