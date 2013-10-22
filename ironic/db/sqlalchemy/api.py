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
from ironic.openstack.common.db.sqlalchemy import utils as db_utils
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


def add_filter_by_many_identities(query, model, values):
    """Adds an identity filter to a query for values list.

    Filters results by ID, if supplied values contain a valid integer.
    Otherwise attempts to filter results by UUID.

    :param query: Initial query to add filter to.
    :param model: Model for filter.
    :param values: Values for filtering results by.
    :return: tuple (Modified query, filter field name).
    """
    if not values:
        raise exception.InvalidIdentity(identity=values)
    value = values[0]
    if utils.is_int_like(value):
        return query.filter(getattr(model, 'id').in_(values)), 'id'
    elif uuidutils.is_uuid_like(value):
        return query.filter(getattr(model, 'uuid').in_(values)), 'uuid'
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


def _check_port_change_forbidden(port, session):
    node_id = port['node_id']
    if node_id is not None:
        query = model_query(models.Node, session=session)
        query = query.filter_by(id=node_id)
        node_ref = query.one()
        if node_ref['reservation'] is not None:
            raise exception.NodeLocked(node=node_id)


def _paginate_query(model, limit=None, marker=None, sort_key=None,
                    sort_dir=None, query=None):
    if not query:
        query = model_query(model)
    sort_keys = ['id']
    if sort_key and sort_key not in sort_keys:
        sort_keys.insert(0, sort_key)
    query = db_utils.paginate_query(query, model, limit, sort_keys,
                                    marker=marker, sort_dir=sort_dir)
    return query.all()


def _check_node_already_locked(query, query_by):
    no_reserv = None
    locked_ref = query.filter(models.Node.reservation != no_reserv).first()
    if locked_ref:
        raise exception.NodeLocked(node=locked_ref[query_by])


def _handle_node_lock_not_found(nodes, query, query_by):
    refs = query.all()
    existing = [ref[query_by] for ref in refs]
    missing = set(nodes) - set(existing)
    raise exception.NodeNotFound(node=missing.pop())


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    @objects.objectify(objects.Node)
    def get_nodes(self, columns):
        pass

    @objects.objectify(objects.Node)
    def get_node_list(self, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir)

    @objects.objectify(objects.Node)
    def get_nodes_by_chassis(self, chassis, limit=None, marker=None,
                             sort_key=None, sort_dir=None):
        query = model_query(models.Node)
        query = add_node_filter_by_chassis(query, chassis)
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir, query)

    @objects.objectify(objects.Node)
    def get_associated_nodes(self):
        query = model_query(models.Node).\
                    filter(models.Node.instance_uuid != None)
        return query.all()

    @objects.objectify(objects.Node)
    def get_unassociated_nodes(self):
        query = model_query(models.Node).\
                    filter(models.Node.instance_uuid == None)
        return query.all()

    @objects.objectify(objects.Node)
    def reserve_nodes(self, tag, nodes):
        # assume nodes does not contain duplicates
        # Ensure consistent sort order so we don't run into deadlocks.
        nodes.sort()
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query, query_by = add_filter_by_many_identities(query, models.Node,
                                                            nodes)
            # Be optimistic and assume we usually get a reservation.
            _check_node_already_locked(query, query_by)
            count = query.update({'reservation': tag},
                                 synchronize_session=False)

            if count != len(nodes):
                # one or more node id not found
                _handle_node_lock_not_found(nodes, query, query_by)

        return query.all()

    def release_nodes(self, tag, nodes):
        # assume nodes does not contain duplicates
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query, query_by = add_filter_by_many_identities(query, models.Node,
                                                            nodes)
            # be optimistic and assume we usually release a reservation
            count = query.filter_by(reservation=tag).\
                       update({'reservation': None}, synchronize_session=False)
            if count != len(nodes):
                # we updated not all nodes
                if len(nodes) != query.count():
                    # one or more node id not found
                    _handle_node_lock_not_found(nodes, query, query_by)
                else:
                    # one or more node had reservation != tag
                    _check_node_already_locked(query, query_by)

    @objects.objectify(objects.Node)
    def create_node(self, values):
        # ensure defaults are present for new nodes
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()
        if not values.get('power_state'):
            values['power_state'] = states.NOSTATE
        if not values.get('provision_state'):
            values['provision_state'] = states.NOSTATE
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
        query = model_query(models.Node).\
                        filter_by(instance_uuid=instance)

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

            try:
                node_ref = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node)
            if node_ref['reservation'] is not None:
                raise exception.NodeLocked(node=node)
            if node_ref['instance_uuid'] is not None:
                raise exception.NodeAssociated(node=node,
                                            instance=node_ref['instance_uuid'])

            # Get node ID, if an UUID was supplied. The ID is
            # required for deleting all ports, attached to the node.
            if uuidutils.is_uuid_like(node):
                node_id = node_ref['id']
            else:
                node_id = node

            port_query = model_query(models.Port, session=session)
            port_query = add_port_filter_by_node(port_query, node_id)
            port_query.delete()

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

    @objects.objectify(objects.Port)
    def get_port_list(self, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir)

    @objects.objectify(objects.Port)
    def get_ports_by_node(self, node, limit=None, marker=None,
                          sort_key=None, sort_dir=None):
        query = model_query(models.Port)
        query = add_port_filter_by_node(query, node)
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir, query)

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
            try:
                ref = query.one()
            except NoResultFound:
                raise exception.PortNotFound(port=port)
            _check_port_change_forbidden(ref, session)

            ref.update(values)

        return ref

    def destroy_port(self, port):
        session = get_session()
        with session.begin():
            query = model_query(models.Port, session=session)
            query = add_port_filter(query, port)

            try:
                ref = query.one()
            except NoResultFound:
                raise exception.PortNotFound(port=port)
            _check_port_change_forbidden(ref, session)

            query.delete()

    @objects.objectify(objects.Chassis)
    def get_chassis(self, chassis):
        query = model_query(models.Chassis)
        query = add_identity_filter(query, chassis)

        try:
            return query.one()
        except NoResultFound:
            raise exception.ChassisNotFound(chassis=chassis)

    @objects.objectify(objects.Chassis)
    def get_chassis_list(self, limit=None, marker=None,
                         sort_key=None, sort_dir=None):
        return _paginate_query(models.Chassis, limit, marker,
                               sort_key, sort_dir)

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
        def chassis_not_empty(session):
            """Checks whether the chassis does not have nodes."""

            query = model_query(models.Node, session=session)
            query = add_node_filter_by_chassis(query, chassis)

            return query.count() != 0

        session = get_session()
        with session.begin():
            if chassis_not_empty(session):
                raise exception.ChassisNotEmpty(chassis=chassis)

            query = model_query(models.Chassis, session=session)
            query = add_identity_filter(query, chassis)

            count = query.delete()
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis)
