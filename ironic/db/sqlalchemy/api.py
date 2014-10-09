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

import collections
import datetime

from oslo.config import cfg
from oslo.db import exception as db_exc
from oslo.db.sqlalchemy import session as db_session
from oslo.db.sqlalchemy import utils as db_utils
from oslo.utils import timeutils
from sqlalchemy.orm.exc import NoResultFound

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.db import api
from ironic.db.sqlalchemy import models
from ironic.openstack.common import log

CONF = cfg.CONF
CONF.import_opt('heartbeat_timeout',
                'ironic.conductor.manager',
                group='conductor')

LOG = log.getLogger(__name__)


_FACADE = None


def _create_facade_lazily():
    global _FACADE
    if _FACADE is None:
        _FACADE = db_session.EngineFacade.from_config(CONF)
    return _FACADE


def get_engine():
    facade = _create_facade_lazily()
    return facade.get_engine()


def get_session(**kwargs):
    facade = _create_facade_lazily()
    return facade.get_session(**kwargs)


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
    elif utils.is_uuid_like(value):
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


def _check_port_change_forbidden(port, session):
    node_id = port['node_id']
    if node_id is not None:
        query = model_query(models.Node, session=session)
        query = query.filter_by(id=node_id)
        node_ref = query.one()
        if node_ref['reservation'] is not None:
            raise exception.NodeLocked(node=node_ref['uuid'],
                                       host=node_ref['reservation'])


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


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    def _add_nodes_filters(self, query, filters):
        if filters is None:
            filters = []

        if 'chassis_uuid' in filters:
            # get_chassis_by_uuid() to raise an exception if the chassis
            # is not found
            chassis_obj = self.get_chassis_by_uuid(filters['chassis_uuid'])
            query = query.filter_by(chassis_id=chassis_obj.id)
        if 'associated' in filters:
            if filters['associated']:
                query = query.filter(models.Node.instance_uuid != None)
            else:
                query = query.filter(models.Node.instance_uuid == None)
        if 'reserved' in filters:
            if filters['reserved']:
                query = query.filter(models.Node.reservation != None)
            else:
                query = query.filter(models.Node.reservation == None)
        if 'maintenance' in filters:
            query = query.filter_by(maintenance=filters['maintenance'])
        if 'driver' in filters:
            query = query.filter_by(driver=filters['driver'])
        if 'provision_state' in filters:
            query = query.filter_by(provision_state=filters['provision_state'])
        if 'provisioned_before' in filters:
            limit = timeutils.utcnow() - datetime.timedelta(
                                         seconds=filters['provisioned_before'])
            query = query.filter(models.Node.provision_updated_at < limit)

        return query

    def get_nodeinfo_list(self, columns=None, filters=None, limit=None,
                          marker=None, sort_key=None, sort_dir=None):
        # list-ify columns default values because it is bad form
        # to include a mutable list in function definitions.
        if columns is None:
            columns = [models.Node.id]
        else:
            columns = [getattr(models.Node, c) for c in columns]

        query = model_query(*columns, base_model=models.Node)
        query = self._add_nodes_filters(query, filters)
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir, query)

    def get_node_list(self, filters=None, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        query = model_query(models.Node)
        query = self._add_nodes_filters(query, filters)
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir, query)

    def reserve_node(self, tag, node_id):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_identity_filter(query, node_id)
            # be optimistic and assume we usually create a reservation
            count = query.filter_by(reservation=None).update(
                        {'reservation': tag}, synchronize_session=False)
            try:
                node = query.one()
                if count != 1:
                    # Nothing updated and node exists. Must already be
                    # locked.
                    raise exception.NodeLocked(node=node_id,
                                               host=node['reservation'])
                return node
            except NoResultFound:
                raise exception.NodeNotFound(node_id)

    def release_node(self, tag, node_id):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_identity_filter(query, node_id)
            # be optimistic and assume we usually release a reservation
            count = query.filter_by(reservation=tag).update(
                        {'reservation': None}, synchronize_session=False)
            try:
                if count != 1:
                    node = query.one()
                    if node['reservation'] is None:
                        raise exception.NodeNotLocked(node=node_id)
                    else:
                        raise exception.NodeLocked(node=node_id,
                                                   host=node['reservation'])
            except NoResultFound:
                raise exception.NodeNotFound(node_id)

    def create_node(self, values):
        # ensure defaults are present for new nodes
        if not values.get('uuid'):
            values['uuid'] = utils.generate_uuid()
        if not values.get('power_state'):
            values['power_state'] = states.NOSTATE
        if not values.get('provision_state'):
            values['provision_state'] = states.NOSTATE

        node = models.Node()
        node.update(values)
        try:
            node.save()
        except db_exc.DBDuplicateEntry as exc:
            if 'instance_uuid' in exc.columns:
                raise exception.InstanceAssociated(
                    instance_uuid=values['instance_uuid'],
                    node=values['uuid'])
            raise exception.NodeAlreadyExists(uuid=values['uuid'])
        return node

    def get_node_by_id(self, node_id):
        query = model_query(models.Node).filter_by(id=node_id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_id)

    def get_node_by_uuid(self, node_uuid):
        query = model_query(models.Node).filter_by(uuid=node_uuid)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_uuid)

    def get_node_by_instance(self, instance):
        if not utils.is_uuid_like(instance):
            raise exception.InvalidUUID(uuid=instance)

        query = (model_query(models.Node)
                 .filter_by(instance_uuid=instance))

        try:
            result = query.one()
        except NoResultFound:
            raise exception.InstanceNotFound(instance=instance)

        return result

    def destroy_node(self, node_id):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_identity_filter(query, node_id)

            try:
                node_ref = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            # Get node ID, if an UUID was supplied. The ID is
            # required for deleting all ports, attached to the node.
            if utils.is_uuid_like(node_id):
                node_id = node_ref['id']

            port_query = model_query(models.Port, session=session)
            port_query = add_port_filter_by_node(port_query, node_id)
            port_query.delete()

            query.delete()

    def update_node(self, node_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Node.")
            raise exception.InvalidParameterValue(err=msg)

        try:
            return self._do_update_node(node_id, values)
        except db_exc.DBDuplicateEntry:
            raise exception.InstanceAssociated(
                instance_uuid=values['instance_uuid'],
                node=node_id)

    def _do_update_node(self, node_id, values):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_identity_filter(query, node_id)
            try:
                ref = query.with_lockmode('update').one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            # Prevent instance_uuid overwriting
            if values.get("instance_uuid") and ref.instance_uuid:
                raise exception.NodeAssociated(node=node_id,
                                instance=ref.instance_uuid)

            if 'provision_state' in values:
                values['provision_updated_at'] = timeutils.utcnow()

            ref.update(values)
        return ref

    def get_port_by_id(self, port_id):
        query = model_query(models.Port).filter_by(id=port_id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port_id)

    def get_port_by_uuid(self, port_uuid):
        query = model_query(models.Port).filter_by(uuid=port_uuid)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port_uuid)

    def get_port_by_address(self, address):
        query = model_query(models.Port).filter_by(address=address)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=address)

    def get_port_list(self, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir)

    def get_ports_by_node_id(self, node_id, limit=None, marker=None,
                             sort_key=None, sort_dir=None):
        query = model_query(models.Port)
        query = query.filter_by(node_id=node_id)
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir, query)

    def create_port(self, values):
        if not values.get('uuid'):
            values['uuid'] = utils.generate_uuid()
        port = models.Port()
        port.update(values)
        try:
            port.save()
        except db_exc.DBDuplicateEntry as exc:
            if 'address' in exc.columns:
                raise exception.MACAlreadyExists(mac=values['address'])
            raise exception.PortAlreadyExists(uuid=values['uuid'])
        return port

    def update_port(self, port_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Port.")
            raise exception.InvalidParameterValue(err=msg)

        session = get_session()
        try:
            with session.begin():
                query = model_query(models.Port, session=session)
                query = add_port_filter(query, port_id)
                ref = query.one()
                ref.update(values)
        except NoResultFound:
            raise exception.PortNotFound(port=port_id)
        except db_exc.DBDuplicateEntry:
            raise exception.MACAlreadyExists(mac=values['address'])
        return ref

    def destroy_port(self, port_id):
        session = get_session()
        with session.begin():
            query = model_query(models.Port, session=session)
            query = add_port_filter(query, port_id)

            try:
                ref = query.one()
            except NoResultFound:
                raise exception.PortNotFound(port=port_id)
            _check_port_change_forbidden(ref, session)

            query.delete()

    def get_chassis_by_id(self, chassis_id):
        query = model_query(models.Chassis).filter_by(id=chassis_id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.ChassisNotFound(chassis=chassis_id)

    def get_chassis_by_uuid(self, chassis_uuid):
        query = model_query(models.Chassis).filter_by(uuid=chassis_uuid)
        try:
            return query.one()
        except NoResultFound:
            raise exception.ChassisNotFound(chassis=chassis_uuid)

    def get_chassis_list(self, limit=None, marker=None,
                         sort_key=None, sort_dir=None):
        return _paginate_query(models.Chassis, limit, marker,
                               sort_key, sort_dir)

    def create_chassis(self, values):
        if not values.get('uuid'):
            values['uuid'] = utils.generate_uuid()
        chassis = models.Chassis()
        chassis.update(values)
        try:
            chassis.save()
        except db_exc.DBDuplicateEntry:
            raise exception.ChassisAlreadyExists(uuid=values['uuid'])
        return chassis

    def update_chassis(self, chassis_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Chassis.")
            raise exception.InvalidParameterValue(err=msg)

        session = get_session()
        with session.begin():
            query = model_query(models.Chassis, session=session)
            query = add_identity_filter(query, chassis_id)

            count = query.update(values)
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis_id)
            ref = query.one()
        return ref

    def destroy_chassis(self, chassis_id):
        def chassis_not_empty(session):
            """Checks whether the chassis does not have nodes."""

            query = model_query(models.Node, session=session)
            query = add_node_filter_by_chassis(query, chassis_id)

            return query.count() != 0

        session = get_session()
        with session.begin():
            if chassis_not_empty(session):
                raise exception.ChassisNotEmpty(chassis=chassis_id)

            query = model_query(models.Chassis, session=session)
            query = add_identity_filter(query, chassis_id)

            count = query.delete()
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis_id)

    def register_conductor(self, values, update_existing=False):
        session = get_session()
        with session.begin():
            query = (model_query(models.Conductor, session=session)
                     .filter_by(hostname=values['hostname']))
            try:
                ref = query.one()
                if ref.online is True and not update_existing:
                    raise exception.ConductorAlreadyRegistered(
                            conductor=values['hostname'])
            except NoResultFound:
                ref = models.Conductor()
            ref.update(values)
            # always set online and updated_at fields when registering
            # a conductor, especially when updating an existing one
            ref.update({'updated_at': timeutils.utcnow(),
                        'online': True})
            ref.save(session)
        return ref

    def get_conductor(self, hostname):
        try:
            return (model_query(models.Conductor)
                    .filter_by(hostname=hostname, online=True)
                    .one())
        except NoResultFound:
            raise exception.ConductorNotFound(conductor=hostname)

    def unregister_conductor(self, hostname):
        session = get_session()
        with session.begin():
            query = (model_query(models.Conductor, session=session)
                     .filter_by(hostname=hostname, online=True))
            count = query.update({'online': False})
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    def touch_conductor(self, hostname):
        session = get_session()
        with session.begin():
            query = (model_query(models.Conductor, session=session)
                     .filter_by(hostname=hostname))
            # since we're not changing any other field, manually set updated_at
            # and since we're heartbeating, make sure that online=True
            count = query.update({'updated_at': timeutils.utcnow(),
                                  'online': True})
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    def get_active_driver_dict(self, interval=None):
        if interval is None:
            interval = CONF.conductor.heartbeat_timeout

        limit = timeutils.utcnow() - datetime.timedelta(seconds=interval)
        result = (model_query(models.Conductor)
                  .filter_by(online=True)
                  .filter(models.Conductor.updated_at >= limit)
                  .all())

        # build mapping of drivers to the set of hosts which support them
        d2c = collections.defaultdict(set)
        for row in result:
            for driver in row['drivers']:
                d2c[driver].add(row['hostname'])
        return d2c
