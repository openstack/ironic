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

from sqlalchemy import Table, Column, String, MetaData


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    ports = Table('ports', meta, autoload=True)

    col = Column('uuid', String(36), unique=True)
    ports.create_column(col, unique_name="port_uuid_ux")


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from version 006 is unsupported.')
