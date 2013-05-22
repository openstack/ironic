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


from sqlalchemy import Table, Column, MetaData
from sqlalchemy import DateTime, Integer, String, Text

from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

ENGINE = 'InnoDB'
CHARSET = 'utf8'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    nodes = Table('nodes', meta, autoload=True)

    chassis_id = Column('chassis_id', Integer, nullable=True)
    task_start = Column('task_start', DateTime, nullable=True)
    properties = Column('properties', Text)
    control_driver = Column('control_driver', String(15))
    control_info = Column('control_info', Text)
    deploy_driver = Column('deploy_driver', String(15))
    deploy_info = Column('deploy_info', Text)
    reservation = Column('reservation', String(255), nullable=True)

    new_cols = [chassis_id, task_start, properties, reservation,
                control_driver, control_info, deploy_driver, deploy_info]
    cols_to_delete = ['power_info', 'cpu_arch', 'cpu_num', 'memory',
                      'local_storage_max', 'image_path', 'instance_name']

    for col in cols_to_delete:
        getattr(nodes.c, col).drop()

    for col in new_cols:
        nodes.create_column(col)

    task_state = getattr(nodes.c, 'task_state')
    task_state.alter(String(15))


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from version 002 is unsupported.')
