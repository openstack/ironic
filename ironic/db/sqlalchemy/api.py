# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""SQLAlchemy storage backend."""

from oslo.config import cfg

# TODO(deva): import MultipleResultsFound and handle it appropriately
from sqlalchemy.orm.exc import NoResultFound

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.db import api
from ironic.db.sqlalchemy import models
from ironic import objects
from ironic.openstack.common.db.sqlalchemy import session as db_session
from ironic.openstack.common import log
from ironic.openstack.common import uuidutils

CONF = cfg.CONF
CONF.import_opt('connection',
                'ironic.openstack.common.db.sqlalchemy.session',
                group='database')

LOG = log.getLogger(__name__)

get_engine = db_session.get_engine
get_session = db_session.get_session


def get_backend():
    """The backend is this module itself."""
    return Connection()


def model_query(model, *args, **kwargs):
    """Query helper for simpler session usage.

    :param session: if present, the session to use
    """

    session = kwargs.get('session') or get_session()
    query = session.query(model, *args)
    return query


def add_identity_filter(query, value):
    """Adds an identity filter to a query.

    Filters results by ID, if supplied value is a valid integer.
    Otherwise attempts to filter results by UUID.

    :param query: Initial query to add filter to.
    :param value: Value for filtering results by.
    :return: Modified query.
    """
    if utils.is_int_like(value):
        return query.filter_by(id=value)
    elif uuidutils.is_uuid_like(value):
        return query.filter_by(uuid=value)
    else:
        raise exception.InvalidIdentity(identity=value)


def add_port_filter(query, value):
    """Adds a port-specific filter to a query.

    Filters results by address, if supplied value is a valid MAC
    address. Otherwise attempts to filter results by identity.

    :param query: Initial query to add filter to.
    :param value: Value for filtering results by.
    :return: Modified query.
    """
    if utils.is_valid_mac(value):
        return query.filter_by(address=value)
    else:
        return add_identity_filter(query, value)


def add_port_filter_by_node(query, value):
    if utils.is_int_like(value):
        return query.filter_by(node_id=value)
    else:
        query = query.join(models.Node,
                models.Port.node_id == models.Node.id)
        return query.filter(models.Node.uuid == value)


def add_node_filter_by_chassis(query, value):
    if utils.is_int_like(value):
        return query.filter_by(chassis_id=value)
    else:
        query = query.join(models.Chassis,
                models.Node.chassis_id == models.Chassis.id)
        return query.filter(models.Chassis.uuid == value)


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    @objects.objectify(objects.Node)
    def get_nodes(self, columns):
        pass

    def get_node_list(self):
        query = model_query(models.Node.uuid)
        return [i[0] for i in query.all()]

    @objects.objectify(objects.Node)
    def get_nodes_by_chassis(self, chassis):
        query = model_query(models.Node)
        query = add_node_filter_by_chassis(query, chassis)

        return query.all()

    @objects.objectify(objects.Node)
    def get_associated_nodes(self):
        pass

    @objects.objectify(objects.Node)
    def get_unassociated_nodes(self):
        pass

    @objects.objectify(objects.Node)
    def reserve_nodes(self, tag, nodes):
        # Ensure consistent sort order so we don't run into deadlocks.
        nodes.sort()

        result = []
        session = get_session()
        with session.begin():
            # TODO(deva): Optimize this by trying to reserve all the nodes
            #             at once, and fall back to reserving one at a time
            #             only if needed to determine the cause of an error.
            for node in nodes:
                query = model_query(models.Node, session=session)
                query = add_identity_filter(query, node)

                # Be optimistic and assume we usually get a reservation.
                count = query.filter_by(reservation=None).\
                            update({'reservation': tag})

                if count != 1:
                    try:
                        ref = query.one()
                    except NoResultFound:
                        raise exception.NodeNotFound(node=node)
                    else:
                        raise exception.NodeLocked(node=node)
                ref = query.one()
                result.append(ref)

        return result

    def release_nodes(self, tag, nodes):
        session = get_session()
        with session.begin():
            # TODO(deva): Optimize this by trying to release all the nodes
            #             at once, and fall back to releasing one at a time
            #             only if needed to determine the cause of an error.
            for node in nodes:
                query = model_query(models.Node, session=session)
                query = add_identity_filter(query, node)

                # be optimistic and assume we usually release a reservation
                count = query.filter_by(reservation=tag).\
                            update({'reservation': None})

                if count != 1:
                    try:
                        ref = query.one()
                    except NoResultFound:
                        raise exception.NodeNotFound(node=node)
                    else:
                        if ref['reservation'] is not None:
                            raise exception.NodeLocked(node=node)

    @objects.objectify(objects.Node)
    def create_node(self, values):
        # ensure defaults are present for new nodes
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()
        if not values.get('task_state'):
            values['task_state'] = states.NOSTATE
        if not values.get('properties'):
            values['properties'] = '{}'
        if not values.get('extra'):
            values['extra'] = '{}'
        if not values.get('driver_info'):
            values['driver_info'] = '{}'

        node = models.Node()
        node.update(values)
        node.save()
        return node

    @objects.objectify(objects.Node)
    def get_node(self, node):
        query = model_query(models.Node)
        query = add_identity_filter(query, node)

        try:
            result = query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node)

        return result

    @objects.objectify(objects.Node)
    def get_node_by_instance(self, instance):
        query = model_query(models.Node)
        if uuidutils.is_uuid_like(instance):
            query = query.filter_by(instance_uuid=instance)
        else:
            query = query.filter_by(instance_name=instance)

        try:
            result = query.one()
        except NoResultFound:
            raise exception.InstanceNotFound(instance=instance)

        return result

    def destroy_node(self, node):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_identity_filter(query, node)

            # Get node ID, if an UUID was supplied. The ID is
            # required for deleting all ports, attached to the node.
            if uuidutils.is_uuid_like(node):
                try:
                    node_id = query.one()['id']
                except NoResultFound:
                    raise exception.NodeNotFound(node=node)
            else:
                node_id = node

            count = query.delete()
            if count != 1:
                raise exception.NodeNotFound(node=node)

            query = model_query(models.Port, session=session)
            query = add_port_filter_by_node(query, node_id)
            query.delete()

    @objects.objectify(objects.Node)
    def update_node(self, node, values):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_identity_filter(query, node)

            count = query.update(values, synchronize_session='fetch')
            if count != 1:
                raise exception.NodeNotFound(node=node)
            ref = query.one()
        return ref

    @objects.objectify(objects.Port)
    def get_port(self, port):
        query = model_query(models.Port)
        query = add_port_filter(query, port)

        try:
            result = query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port)

        return result

    @objects.objectify(objects.Port)
    def get_port_by_vif(self, vif):
        pass

    def get_port_list(self):
        query = model_query(models.Port.uuid)
        return [i[0] for i in query.all()]

    @objects.objectify(objects.Port)
    def get_ports_by_node(self, node):
        query = model_query(models.Port)
        query = add_port_filter_by_node(query, node)

        return query.all()

    @objects.objectify(objects.Port)
    def create_port(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()
        if not values.get('extra'):
            values['extra'] = '{}'
        port = models.Port()
        port.update(values)
        port.save()
        return port

    @objects.objectify(objects.Port)
    def update_port(self, port, values):
        session = get_session()
        with session.begin():
            query = model_query(models.Port, session=session)
            query = add_port_filter(query, port)

            count = query.update(values)
            if count != 1:
                raise exception.PortNotFound(port=port)
            ref = query.one()
        return ref

    def destroy_port(self, port):
        session = get_session()
        with session.begin():
            query = model_query(models.Port, session=session)
            query = add_port_filter(query, port)

            count = query.delete()
            if count != 1:
                raise exception.PortNotFound(port=port)

    @objects.objectify(objects.Chassis)
    def get_chassis(self, chassis):
        query = model_query(models.Chassis)
        query = add_identity_filter(query, chassis)

        try:
            return query.one()
        except NoResultFound:
            raise exception.ChassisNotFound(chassis=chassis)

    def get_chassis_list(self):
        query = model_query(models.Chassis.uuid)
        return [i[0] for i in query.all()]

    @objects.objectify(objects.Chassis)
    def create_chassis(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()
        if not values.get('extra'):
            values['extra'] = '{}'
        chassis = models.Chassis()
        chassis.update(values)
        chassis.save()
        return chassis

    @objects.objectify(objects.Chassis)
    def update_chassis(self, chassis, values):
        session = get_session()
        with session.begin():
            query = model_query(models.Chassis, session=session)
            query = add_identity_filter(query, chassis)

            count = query.update(values)
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis)
            ref = query.one()
        return ref

    def destroy_chassis(self, chassis):
        session = get_session()
        with session.begin():
            query = model_query(models.Chassis, session=session)
            query = add_identity_filter(query, chassis)

            count = query.delete()
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis)
