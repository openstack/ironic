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

"""
SQLAlchemy models for baremetal data.
"""

import urlparse

from oslo.config import cfg

from sqlalchemy import Table, Column, Index, ForeignKey
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

from ironic.openstack.common.db.sqlalchemy import models

sql_opts = [
    cfg.StrOpt('mysql_engine',
               default='InnoDB',
               help='MySQL engine')
]

cfg.CONF.register_opts(sql_opts)


def table_args():
    engine_name = urlparse.urlparse(cfg.CONF.database_connection).scheme
    if engine_name == 'mysql':
        return {'mysql_engine': cfg.CONF.mysql_engine,
                'mysql_charset': "utf8"}
    return None

class IronicBase(models.TimestampMixin,
                 models.ModelBase):
    metadata = None


Base = declarative_base(cls=IronicBase)


class Node(Base):
    """Represents a bare metal node."""

    __tablename__ = 'nodes'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)
    power_info = Column(Text)
    cpu_arch = Column(String(10))
    cpu_num = Column(Integer)
    memory = Column(Integer)
    local_storage_max = Column(Integer)
    task_state = Column(String(255))
    image_path = Column(String(255), nullable=True)
    instance_uuid = Column(String(36), nullable=True, unique=True)
    instance_name = Column(String(255), nullable=True)
    extra = Column(Text)


class Iface(Base):
    """Represents a NIC in a bare metal node."""

    __tablename__ = 'ifaces'
    id = Column(Integer, primary_key=True)
    address = Column(String(18), unique=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    extra = Column(Text)
