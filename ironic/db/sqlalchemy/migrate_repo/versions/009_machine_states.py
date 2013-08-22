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

from sqlalchemy import Table, Column, MetaData, String


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('nodes', meta, autoload=True)

    # Drop task_* columns
    nodes.c.task_start.drop()
    nodes.c.task_state.drop()

    # Create new states columns
    nodes.create_column(Column('power_state', String(15), nullable=True))
    nodes.create_column(Column('target_power_state', String(15),
                                nullable=True))
    nodes.create_column(Column('provision_state', String(15), nullable=True))
    nodes.create_column(Column('target_provision_state', String(15),
                                nullable=True))


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from version 009 is unsupported.')
