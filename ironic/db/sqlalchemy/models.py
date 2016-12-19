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

from os import path

from oslo_db import options as db_options
from oslo_db.sqlalchemy import models
from oslo_db.sqlalchemy import types as db_types
import six.moves.urllib.parse as urlparse
from sqlalchemy import Boolean, Column, DateTime, Index
from sqlalchemy import ForeignKey, Integer
from sqlalchemy import schema, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import orm

from ironic.conf import CONF

_DEFAULT_SQL_CONNECTION = 'sqlite:///' + path.join('$state_path',
                                                   'ironic.sqlite')


db_options.set_defaults(CONF, connection=_DEFAULT_SQL_CONNECTION)


def table_args():
    engine_name = urlparse.urlparse(CONF.database.connection).scheme
    if engine_name == 'mysql':
        return {'mysql_engine': CONF.database.mysql_engine,
                'mysql_charset': "utf8"}
    return None


class IronicBase(models.TimestampMixin,
                 models.ModelBase):

    metadata = None

    version = Column(String(15), nullable=True)

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
        table_args()
    )
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    extra = Column(db_types.JsonEncodedDict)
    description = Column(String(255), nullable=True)


class Conductor(Base):
    """Represents a conductor service entry."""

    __tablename__ = 'conductors'
    __table_args__ = (
        schema.UniqueConstraint('hostname', name='uniq_conductors0hostname'),
        table_args()
    )
    id = Column(Integer, primary_key=True)
    hostname = Column(String(255), nullable=False)
    drivers = Column(db_types.JsonEncodedList)
    online = Column(Boolean, default=True)


class ConductorHardwareInterfaces(Base):
    """Internal table used to track what is loaded on each conductor."""

    __tablename__ = 'conductor_hardware_interfaces'
    __table_args__ = (
        schema.UniqueConstraint(
            'conductor_id',
            'hardware_type',
            'interface_type',
            'interface_name',
            name='uniq_conductorhardwareinterfaces0'),
        table_args())
    id = Column(Integer, primary_key=True)
    conductor_id = Column(Integer, ForeignKey('conductors.id'), nullable=False)
    hardware_type = Column(String(255), nullable=False)
    interface_type = Column(String(16), nullable=False)
    interface_name = Column(String(255), nullable=False)
    default = Column(Boolean, default=False, nullable=False)


class Node(Base):
    """Represents a bare metal node."""

    __tablename__ = 'nodes'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_nodes0uuid'),
        schema.UniqueConstraint('instance_uuid',
                                name='uniq_nodes0instance_uuid'),
        schema.UniqueConstraint('name', name='uniq_nodes0name'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    # NOTE(deva): we store instance_uuid directly on the node so that we can
    #             filter on it more efficiently, even though it is
    #             user-settable, and would otherwise be in node.properties.
    instance_uuid = Column(String(36), nullable=True)
    name = Column(String(255), nullable=True)
    chassis_id = Column(Integer, ForeignKey('chassis.id'), nullable=True)
    power_state = Column(String(15), nullable=True)
    target_power_state = Column(String(15), nullable=True)
    provision_state = Column(String(15), nullable=True)
    target_provision_state = Column(String(15), nullable=True)
    provision_updated_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    instance_info = Column(db_types.JsonEncodedDict)
    properties = Column(db_types.JsonEncodedDict)
    driver = Column(String(255))
    driver_info = Column(db_types.JsonEncodedDict)
    driver_internal_info = Column(db_types.JsonEncodedDict)
    clean_step = Column(db_types.JsonEncodedDict)
    resource_class = Column(String(80), nullable=True)

    raid_config = Column(db_types.JsonEncodedDict)
    target_raid_config = Column(db_types.JsonEncodedDict)

    # NOTE(deva): this is the host name of the conductor which has
    #             acquired a TaskManager lock on the node.
    #             We should use an INT FK (conductors.id) in the future.
    reservation = Column(String(255), nullable=True)

    # NOTE(deva): this is the id of the last conductor which prepared local
    #             state for the node (eg, a PXE config file).
    #             When affinity and the hash ring's mapping do not match,
    #             this indicates that a conductor should rebuild local state.
    conductor_affinity = Column(Integer,
                                ForeignKey('conductors.id',
                                           name='nodes_conductor_affinity_fk'),
                                nullable=True)

    maintenance = Column(Boolean, default=False)
    maintenance_reason = Column(Text, nullable=True)
    console_enabled = Column(Boolean, default=False)
    inspection_finished_at = Column(DateTime, nullable=True)
    inspection_started_at = Column(DateTime, nullable=True)
    extra = Column(db_types.JsonEncodedDict)

    boot_interface = Column(String(255), nullable=True)
    console_interface = Column(String(255), nullable=True)
    deploy_interface = Column(String(255), nullable=True)
    inspect_interface = Column(String(255), nullable=True)
    management_interface = Column(String(255), nullable=True)
    network_interface = Column(String(255), nullable=True)
    raid_interface = Column(String(255), nullable=True)
    storage_interface = Column(String(255), nullable=True)
    power_interface = Column(String(255), nullable=True)
    vendor_interface = Column(String(255), nullable=True)


class Port(Base):
    """Represents a network port of a bare metal node."""

    __tablename__ = 'ports'
    __table_args__ = (
        schema.UniqueConstraint('address', name='uniq_ports0address'),
        schema.UniqueConstraint('uuid', name='uniq_ports0uuid'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    address = Column(String(18))
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    extra = Column(db_types.JsonEncodedDict)
    local_link_connection = Column(db_types.JsonEncodedDict)
    portgroup_id = Column(Integer, ForeignKey('portgroups.id'), nullable=True)
    pxe_enabled = Column(Boolean, default=True)
    internal_info = Column(db_types.JsonEncodedDict)
    physical_network = Column(String(64), nullable=True)


class Portgroup(Base):
    """Represents a group of network ports of a bare metal node."""

    __tablename__ = 'portgroups'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_portgroups0uuid'),
        schema.UniqueConstraint('address', name='uniq_portgroups0address'),
        schema.UniqueConstraint('name', name='uniq_portgroups0name'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    name = Column(String(255), nullable=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    address = Column(String(18))
    extra = Column(db_types.JsonEncodedDict)
    internal_info = Column(db_types.JsonEncodedDict)
    standalone_ports_supported = Column(Boolean, default=True)
    mode = Column(String(255))
    properties = Column(db_types.JsonEncodedDict)


class NodeTag(Base):
    """Represents a tag of a bare metal node."""

    __tablename__ = 'node_tags'
    __table_args__ = (
        Index('node_tags_idx', 'tag'),
        table_args())
    node_id = Column(Integer, ForeignKey('nodes.id'),
                     primary_key=True, nullable=False)
    tag = Column(String(255), primary_key=True, nullable=False)

    node = orm.relationship(
        "Node",
        backref='tags',
        primaryjoin='and_(NodeTag.node_id == Node.id)',
        foreign_keys=node_id
    )


class VolumeConnector(Base):
    """Represents a volume connector of a bare metal node."""

    __tablename__ = 'volume_connectors'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_volumeconnectors0uuid'),
        schema.UniqueConstraint(
            'type',
            'connector_id',
            name='uniq_volumeconnectors0type0connector_id'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    type = Column(String(32))
    connector_id = Column(String(255))
    extra = Column(db_types.JsonEncodedDict)


class VolumeTarget(Base):
    """Represents a volume target of a bare metal node."""

    __tablename__ = 'volume_targets'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_volumetargets0uuid'),
        schema.UniqueConstraint('node_id',
                                'boot_index',
                                name='uniq_volumetargets0node_id0boot_index'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    volume_type = Column(String(64))
    properties = Column(db_types.JsonEncodedDict)
    boot_index = Column(Integer)
    volume_id = Column(String(36))
    extra = Column(db_types.JsonEncodedDict)
