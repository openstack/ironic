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
from typing import List
from urllib import parse as urlparse

from oslo_db import options as db_options
from oslo_db.sqlalchemy import models
from oslo_db.sqlalchemy import types as db_types
from sqlalchemy import Boolean, Column, DateTime, false, Index
from sqlalchemy import ForeignKey, Integer
from sqlalchemy import schema, String, Text
from sqlalchemy import orm
from sqlalchemy.orm import declarative_base

from ironic.common import exception
from ironic.common.i18n import _
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
    conductor_group = Column(String(255), nullable=False, default='',
                             server_default='')


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


class NodeBase(Base):
    """Represents a base bare metal node."""

    __tablename__ = 'nodes'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_nodes0uuid'),
        schema.UniqueConstraint('instance_uuid',
                                name='uniq_nodes0instance_uuid'),
        schema.UniqueConstraint('name', name='uniq_nodes0name'),
        Index('owner_idx', 'owner'),
        Index('lessee_idx', 'lessee'),
        Index('driver_idx', 'driver'),
        Index('provision_state_idx', 'provision_state'),
        Index('reservation_idx', 'reservation'),
        Index('conductor_group_idx', 'conductor_group'),
        Index('resource_class_idx', 'resource_class'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    # NOTE(tenbrae): we store instance_uuid directly on the node so that we can
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
    instance_info = Column(db_types.JsonEncodedDict(mysql_as_long=True))
    properties = Column(db_types.JsonEncodedDict)
    driver = Column(String(255))
    driver_info = Column(db_types.JsonEncodedDict)
    driver_internal_info = Column(db_types.JsonEncodedDict)
    clean_step = Column(db_types.JsonEncodedDict)
    deploy_step = Column(db_types.JsonEncodedDict)
    resource_class = Column(String(80), nullable=True)

    raid_config = Column(db_types.JsonEncodedDict)
    target_raid_config = Column(db_types.JsonEncodedDict)

    # NOTE(tenbrae): this is the host name of the conductor which has
    #             acquired a TaskManager lock on the node.
    #             We should use an INT FK (conductors.id) in the future.
    reservation = Column(String(255), nullable=True)

    # NOTE(tenbrae): this is the id of the last conductor which prepared local
    #             state for the node (eg, a PXE config file).
    #             When affinity and the hash ring's mapping do not match,
    #             this indicates that a conductor should rebuild local state.
    conductor_affinity = Column(Integer,
                                ForeignKey('conductors.id',
                                           name='nodes_conductor_affinity_fk'),
                                nullable=True)
    conductor_group = Column(String(255), nullable=False, default='',
                             server_default='')

    maintenance = Column(Boolean, default=False)
    maintenance_reason = Column(Text, nullable=True)
    fault = Column(String(255), nullable=True)
    console_enabled = Column(Boolean, default=False)
    inspection_finished_at = Column(DateTime, nullable=True)
    inspection_started_at = Column(DateTime, nullable=True)
    extra = Column(db_types.JsonEncodedDict)
    automated_clean = Column(Boolean, nullable=True)
    protected = Column(Boolean, nullable=False, default=False,
                       server_default=false())
    protected_reason = Column(Text, nullable=True)
    owner = Column(String(255), nullable=True)
    lessee = Column(String(255), nullable=True)
    allocation_id = Column(Integer, ForeignKey('allocations.id'),
                           nullable=True)
    description = Column(Text, nullable=True)

    bios_interface = Column(String(255), nullable=True)
    boot_interface = Column(String(255), nullable=True)
    console_interface = Column(String(255), nullable=True)
    deploy_interface = Column(String(255), nullable=True)
    inspect_interface = Column(String(255), nullable=True)
    management_interface = Column(String(255), nullable=True)
    network_interface = Column(String(255), nullable=True)
    raid_interface = Column(String(255), nullable=True)
    rescue_interface = Column(String(255), nullable=True)
    retired = Column(Boolean, nullable=True, default=False,
                     server_default=false())
    retired_reason = Column(Text, nullable=True)
    network_data = Column(db_types.JsonEncodedDict)
    storage_interface = Column(String(255), nullable=True)
    power_interface = Column(String(255), nullable=True)
    vendor_interface = Column(String(255), nullable=True)

    boot_mode = Column(String(16), nullable=True)
    secure_boot = Column(Boolean, nullable=True)


class Node(NodeBase):
    """Represents a bare metal node."""

    # NOTE(TheJulia): The purpose of the delineation between NodeBase and Node
    # is to facilitate a hard delineation for queries where we do not need to
    # populate additional information needlessly which would normally populate
    # from the access of the property. In this case, Traits and Tags.
    # The other reason we do this, is because these are generally "joined"
    # data structures, we cannot de-duplicate node objects with unhashable dict
    # data structures.

    # NOTE(TheJulia): The choice of selectin lazy population is intentional
    # as it causes a subselect to occur, skipping the need for deduplication
    # in general. This puts a slightly higher query load on the DB server, but
    # means *far* less gets shipped over the wire in the end.
    traits: orm.Mapped[List['NodeTrait']] = orm.relationship(  # noqa
        "NodeTrait",
        back_populates="node",
        lazy="selectin")

    tags: orm.Mapped[List['NodeTag']] = orm.relationship(  # noqa
        "NodeTag",
        back_populates="node",
        lazy="selectin")


class Port(Base):
    """Represents a network port of a bare metal node."""

    __tablename__ = 'ports'
    __table_args__ = (
        schema.UniqueConstraint('address', name='uniq_ports0address'),
        schema.UniqueConstraint('uuid', name='uniq_ports0uuid'),
        schema.UniqueConstraint('name', name='uniq_ports0name'),
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
    is_smartnic = Column(Boolean, nullable=True, default=False)
    name = Column(String(255), nullable=True)


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


class NodeTrait(Base):
    """Represents a trait of a bare metal node."""

    __tablename__ = 'node_traits'
    __table_args__ = (
        Index('node_traits_idx', 'trait'),
        table_args())
    node_id = Column(Integer, ForeignKey('nodes.id'),
                     primary_key=True, nullable=False)
    trait = Column(String(255), primary_key=True, nullable=False)
    node = orm.relationship(
        "Node",
        primaryjoin='and_(NodeTrait.node_id == Node.id)',
        foreign_keys=node_id
    )


class BIOSSetting(Base):
    """Represents a bios setting of a bare metal node."""

    __tablename__ = 'bios_settings'
    __table_args__ = (table_args())
    node_id = Column(Integer, ForeignKey('nodes.id'),
                     primary_key=True, nullable=False)
    name = Column(String(255), primary_key=True, nullable=False)
    value = Column(Text, nullable=True)
    attribute_type = Column(String(255), nullable=True)
    allowable_values = Column(db_types.JsonEncodedList, nullable=True)
    lower_bound = Column(Integer, nullable=True)
    max_length = Column(Integer, nullable=True)
    min_length = Column(Integer, nullable=True)
    read_only = Column(Boolean, nullable=True)
    reset_required = Column(Boolean, nullable=True)
    unique = Column(Boolean, nullable=True)
    upper_bound = Column(Integer, nullable=True)


class Allocation(Base):
    """Represents an allocation of a node for deployment."""

    __tablename__ = 'allocations'
    __table_args__ = (
        schema.UniqueConstraint('name', name='uniq_allocations0name'),
        schema.UniqueConstraint('uuid', name='uniq_allocations0uuid'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)
    name = Column(String(255), nullable=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)
    state = Column(String(15), nullable=False)
    owner = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    resource_class = Column(String(80), nullable=True)
    traits = Column(db_types.JsonEncodedList)
    candidate_nodes = Column(db_types.JsonEncodedList)
    extra = Column(db_types.JsonEncodedDict)
    # The last conductor to handle this allocation (internal field).
    conductor_affinity = Column(Integer, ForeignKey('conductors.id'),
                                nullable=True)


class DeployTemplate(Base):
    """Represents a deployment template."""

    __tablename__ = 'deploy_templates'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_deploytemplates0uuid'),
        schema.UniqueConstraint('name', name='uniq_deploytemplates0name'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36))
    name = Column(String(255), nullable=False)
    extra = Column(db_types.JsonEncodedDict)
    steps: orm.Mapped[List['DeployTemplateStep']] = orm.relationship(  # noqa
        "DeployTemplateStep",
        back_populates="deploy_template",
        lazy="selectin")


class DeployTemplateStep(Base):
    """Represents a deployment step in a deployment template."""

    __tablename__ = 'deploy_template_steps'
    __table_args__ = (
        Index('deploy_template_id', 'deploy_template_id'),
        Index('deploy_template_steps_interface_idx', 'interface'),
        Index('deploy_template_steps_step_idx', 'step'),
        table_args())
    id = Column(Integer, primary_key=True)
    deploy_template_id = Column(Integer, ForeignKey('deploy_templates.id'),
                                nullable=False)
    interface = Column(String(255), nullable=False)
    step = Column(String(255), nullable=False)
    args = Column(db_types.JsonEncodedDict, nullable=False)
    priority = Column(Integer, nullable=False)
    deploy_template = orm.relationship(
        "DeployTemplate",
        primaryjoin=(
            'and_(DeployTemplateStep.deploy_template_id == '
            'DeployTemplate.id)'),
        foreign_keys=deploy_template_id
    )


class NodeHistory(Base):
    """Represents a history event of a bare metal node."""

    __tablename__ = 'node_history'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_history0uuid'),
        Index('history_node_id_idx', 'node_id'),
        Index('history_uuid_idx', 'uuid'),
        Index('history_conductor_idx', 'conductor'),
        table_args())
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)
    conductor = Column(String(255), nullable=True)
    event_type = Column(String(255), nullable=True)
    severity = Column(String(255), nullable=True)
    event = Column(Text, nullable=True)
    user = Column(String(32), nullable=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=True)


def get_class(model_name):
    """Returns the model class with the specified name.

    :param model_name: the name of the class
    :returns: the class with the specified name
    :raises: Exception if there is no class associated with the name
    """
    for model in Base.__subclasses__():
        if model.__name__ == model_name:
            return model

    raise exception.IronicException(
        _("Cannot find model with name: %s") % model_name)
