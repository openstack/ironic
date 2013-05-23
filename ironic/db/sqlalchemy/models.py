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

import json
import urlparse

from oslo.config import cfg

from sqlalchemy import Column, ForeignKey
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator, VARCHAR

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


class JSONEncodedDict(TypeDecorator):
    """Represents an immutable structure as a json-encoded string."""

    impl = VARCHAR

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class IronicBase(models.TimestampMixin,
                 models.ModelBase):

    metadata = None

    def as_dict(self):
        d = {}
        for c in self.__table__.columns:
            d[c.name] = self[c.name]
        return d


Base = declarative_base(cls=IronicBase)


class Chassis(Base):
    """Represents a hardware chassis."""

    __tablename__ = 'chassis'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)


class Node(Base):
    """Represents a bare metal node."""

    __tablename__ = 'nodes'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)
    instance_uuid = Column(String(36), nullable=True, unique=True)
    chassis_id = Column(Integer, ForeignKey('chassis.id'), nullable=True)
    task_start = Column(DateTime, nullable=True)
    task_state = Column(String(15))
    properties = Column(JSONEncodedDict)
    control_driver = Column(String(15))
    control_info = Column(JSONEncodedDict)
    deploy_driver = Column(String(15))
    deploy_info = Column(JSONEncodedDict)
    reservation = Column(String(255), nullable=True)


class Iface(Base):
    """Represents a NIC in a bare metal node."""

    __tablename__ = 'ifaces'
    id = Column(Integer, primary_key=True)
    address = Column(String(18), unique=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    extra = Column(JSONEncodedDict)
