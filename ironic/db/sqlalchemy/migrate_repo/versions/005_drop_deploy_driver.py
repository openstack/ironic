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

from sqlalchemy import Table, MetaData


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('nodes', meta, autoload=True)

    nodes.c.deploy_driver.drop()
    nodes.c.deploy_info.drop()
    nodes.c.control_driver.alter(name='driver')
    nodes.c.control_info.alter(name='driver_info')


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from version 005 is unsupported.')
