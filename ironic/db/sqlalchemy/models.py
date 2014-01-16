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

from sqlalchemy import Boolean, Column, ForeignKey
from sqlalchemy import Integer, Index
from sqlalchemy import schema, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator, VARCHAR

from ironic.openstack.common.db.sqlalchemy import models

sql_opts = [
    cfg.StrOpt('mysql_engine',
               default='InnoDB',
               help='MySQL engine')
]

cfg.CONF.register_opts(sql_opts, 'database')


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
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_chassis0uuid'),
        )
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    extra = Column(JSONEncodedDict)
    description = Column(String(255), nullable=True)


class Conductor(Base):
    """Represents a conductor service entry."""

    __tablename__ = 'conductors'
    __table_args__ = (
        schema.UniqueConstraint('hostname', name='uniq_conductors0hostname'),
        )
    id = Column(Integer, primary_key=True)
    hostname = Column(String(255), nullable=False)
    drivers = Column(JSONEncodedDict)


class Node(Base):
    """Represents a bare metal node."""

    __tablename__ = 'nodes'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='node_uuid_ux'),
        Index('node_instance_uuid', 'instance_uuid'))
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    instance_uuid = Column(String(36), nullable=True)
    chassis_id = Column(Integer, ForeignKey('chassis.id'), nullable=True)
    power_state = Column(String(15), nullable=True)
    target_power_state = Column(String(15), nullable=True)
    provision_state = Column(String(15), nullable=True)
    target_provision_state = Column(String(15), nullable=True)
    last_error = Column(Text, nullable=True)
    properties = Column(JSONEncodedDict)
    driver = Column(String(15))
    driver_info = Column(JSONEncodedDict)
    reservation = Column(String(255), nullable=True)
    maintenance = Column(Boolean, default=False)
    extra = Column(JSONEncodedDict)


class Port(Base):
    """Represents a network port of a bare metal node."""

    __tablename__ = 'ports'
    __table_args__ = (
        schema.UniqueConstraint('address', name='iface_address_ux'),
        schema.UniqueConstraint('uuid', name='port_uuid_ux'))
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    address = Column(String(18))
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    extra = Column(JSONEncodedDict)
