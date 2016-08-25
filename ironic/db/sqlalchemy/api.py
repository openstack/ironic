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
import threading

from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import utils as db_utils
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import joinedload
from sqlalchemy import sql

from ironic.common import exception
from ironic.common.i18n import _, _LW
from ironic.common import states
from ironic.common import utils
from ironic.conf import CONF
from ironic.db import api
from ironic.db.sqlalchemy import models


LOG = log.getLogger(__name__)


_CONTEXT = threading.local()


def get_backend():
    """The backend is this module itself."""
    return Connection()


def _session_for_read():
    return enginefacade.reader.using(_CONTEXT)


def _session_for_write():
    return enginefacade.writer.using(_CONTEXT)


def _get_node_query_with_tags():
    return model_query(models.Node).options(joinedload('tags'))


def model_query(model, *args, **kwargs):
    """Query helper for simpler session usage.

    :param session: if present, the session to use
    """

    with _session_for_read() as session:
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
    if strutils.is_int_like(value):
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
    if strutils.is_int_like(value):
        return query.filter_by(node_id=value)
    else:
        query = query.join(models.Node,
                           models.Port.node_id == models.Node.id)
        return query.filter(models.Node.uuid == value)


def add_portgroup_filter(query, value):
    """Adds a portgroup-specific filter to a query.

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


def add_portgroup_filter_by_node(query, value):
    if strutils.is_int_like(value):
        return query.filter_by(node_id=value)
    else:
        query = query.join(models.Node,
                           models.Portgroup.node_id == models.Node.id)
        return query.filter(models.Node.uuid == value)


def add_port_filter_by_portgroup(query, value):
    if strutils.is_int_like(value):
        return query.filter_by(portgroup_id=value)
    else:
        query = query.join(models.Portgroup,
                           models.Port.portgroup_id == models.Portgroup.id)
        return query.filter(models.Portgroup.uuid == value)


def add_node_filter_by_chassis(query, value):
    if strutils.is_int_like(value):
        return query.filter_by(chassis_id=value)
    else:
        query = query.join(models.Chassis,
                           models.Node.chassis_id == models.Chassis.id)
        return query.filter(models.Chassis.uuid == value)


def _paginate_query(model, limit=None, marker=None, sort_key=None,
                    sort_dir=None, query=None):
    if not query:
        query = model_query(model)
    sort_keys = ['id']
    if sort_key and sort_key not in sort_keys:
        sort_keys.insert(0, sort_key)
    try:
        query = db_utils.paginate_query(query, model, limit, sort_keys,
                                        marker=marker, sort_dir=sort_dir)
    except db_exc.InvalidSortKey:
        raise exception.InvalidParameterValue(
            _('The sort_key value "%(key)s" is an invalid field for sorting')
            % {'key': sort_key})
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
                query = query.filter(models.Node.instance_uuid != sql.null())
            else:
                query = query.filter(models.Node.instance_uuid == sql.null())
        if 'reserved' in filters:
            if filters['reserved']:
                query = query.filter(models.Node.reservation != sql.null())
            else:
                query = query.filter(models.Node.reservation == sql.null())
        if 'reserved_by_any_of' in filters:
            query = query.filter(models.Node.reservation.in_(
                filters['reserved_by_any_of']))
        if 'maintenance' in filters:
            query = query.filter_by(maintenance=filters['maintenance'])
        if 'driver' in filters:
            query = query.filter_by(driver=filters['driver'])
        if 'resource_class' in filters:
            query = query.filter_by(resource_class=filters['resource_class'])
        if 'provision_state' in filters:
            query = query.filter_by(provision_state=filters['provision_state'])
        if 'provisioned_before' in filters:
            limit = (timeutils.utcnow() -
                     datetime.timedelta(seconds=filters['provisioned_before']))
            query = query.filter(models.Node.provision_updated_at < limit)
        if 'inspection_started_before' in filters:
            limit = ((timeutils.utcnow()) -
                     (datetime.timedelta(
                         seconds=filters['inspection_started_before'])))
            query = query.filter(models.Node.inspection_started_at < limit)
        if 'console_enabled' in filters:
            query = query.filter_by(console_enabled=filters['console_enabled'])

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
        query = _get_node_query_with_tags()
        query = self._add_nodes_filters(query, filters)
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir, query)

    def reserve_node(self, tag, node_id):
        with _session_for_write():
            query = _get_node_query_with_tags()
            query = add_identity_filter(query, node_id)
            # be optimistic and assume we usually create a reservation
            count = query.filter_by(reservation=None).update(
                {'reservation': tag}, synchronize_session=False)
            try:
                node = query.one()
                if count != 1:
                    # Nothing updated and node exists. Must already be
                    # locked.
                    raise exception.NodeLocked(node=node.uuid,
                                               host=node['reservation'])
                return node
            except NoResultFound:
                raise exception.NodeNotFound(node_id)

    def release_node(self, tag, node_id):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)
            # be optimistic and assume we usually release a reservation
            count = query.filter_by(reservation=tag).update(
                {'reservation': None}, synchronize_session=False)
            try:
                if count != 1:
                    node = query.one()
                    if node['reservation'] is None:
                        raise exception.NodeNotLocked(node=node.uuid)
                    else:
                        raise exception.NodeLocked(node=node.uuid,
                                                   host=node['reservation'])
            except NoResultFound:
                raise exception.NodeNotFound(node_id)

    def create_node(self, values):
        # ensure defaults are present for new nodes
        if 'uuid' not in values:
            values['uuid'] = uuidutils.generate_uuid()
        if 'power_state' not in values:
            values['power_state'] = states.NOSTATE
        if 'provision_state' not in values:
            values['provision_state'] = states.ENROLL

        # TODO(zhenguo): Support creating node with tags
        if 'tags' in values:
            msg = _("Cannot create node with tags.")
            raise exception.InvalidParameterValue(err=msg)

        node = models.Node()
        node.update(values)
        with _session_for_write() as session:
            try:
                session.add(node)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'name' in exc.columns:
                    raise exception.DuplicateName(name=values['name'])
                elif 'instance_uuid' in exc.columns:
                    raise exception.InstanceAssociated(
                        instance_uuid=values['instance_uuid'],
                        node=values['uuid'])
                raise exception.NodeAlreadyExists(uuid=values['uuid'])
            # Set tags to [] for new created node
            node['tags'] = []
            return node

    def get_node_by_id(self, node_id):
        query = _get_node_query_with_tags()
        query = query.filter_by(id=node_id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_id)

    def get_node_by_uuid(self, node_uuid):
        query = _get_node_query_with_tags()
        query = query.filter_by(uuid=node_uuid)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_uuid)

    def get_node_by_name(self, node_name):
        query = _get_node_query_with_tags()
        query = query.filter_by(name=node_name)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_name)

    def get_node_by_instance(self, instance):
        if not uuidutils.is_uuid_like(instance):
            raise exception.InvalidUUID(uuid=instance)

        query = _get_node_query_with_tags()
        query = query.filter_by(instance_uuid=instance)

        try:
            result = query.one()
        except NoResultFound:
            raise exception.InstanceNotFound(instance=instance)

        return result

    def destroy_node(self, node_id):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)

            try:
                node_ref = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            # Get node ID, if an UUID was supplied. The ID is
            # required for deleting all ports, attached to the node.
            if uuidutils.is_uuid_like(node_id):
                node_id = node_ref['id']

            port_query = model_query(models.Port)
            port_query = add_port_filter_by_node(port_query, node_id)
            port_query.delete()

            portgroup_query = model_query(models.Portgroup)
            portgroup_query = add_portgroup_filter_by_node(portgroup_query,
                                                           node_id)
            portgroup_query.delete()

            # Delete all tags attached to the node
            tag_query = model_query(models.NodeTag).filter_by(node_id=node_id)
            tag_query.delete()

            query.delete()

    def update_node(self, node_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Node.")
            raise exception.InvalidParameterValue(err=msg)

        try:
            return self._do_update_node(node_id, values)
        except db_exc.DBDuplicateEntry as e:
            if 'name' in e.columns:
                raise exception.DuplicateName(name=values['name'])
            elif 'uuid' in e.columns:
                raise exception.NodeAlreadyExists(uuid=values['uuid'])
            elif 'instance_uuid' in e.columns:
                raise exception.InstanceAssociated(
                    instance_uuid=values['instance_uuid'],
                    node=node_id)
            else:
                raise

    def _do_update_node(self, node_id, values):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)
            try:
                ref = query.with_lockmode('update').one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            # Prevent instance_uuid overwriting
            if values.get("instance_uuid") and ref.instance_uuid:
                raise exception.NodeAssociated(
                    node=ref.uuid, instance=ref.instance_uuid)

            if 'provision_state' in values:
                values['provision_updated_at'] = timeutils.utcnow()
                if values['provision_state'] == states.INSPECTING:
                    values['inspection_started_at'] = timeutils.utcnow()
                    values['inspection_finished_at'] = None
                elif (ref.provision_state == states.INSPECTING and
                      values['provision_state'] == states.MANAGEABLE):
                    values['inspection_finished_at'] = timeutils.utcnow()
                    values['inspection_started_at'] = None
                elif (ref.provision_state == states.INSPECTING and
                      values['provision_state'] == states.INSPECTFAIL):
                    values['inspection_started_at'] = None

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

    def get_ports_by_portgroup_id(self, portgroup_id, limit=None, marker=None,
                                  sort_key=None, sort_dir=None):
        query = model_query(models.Port)
        query = query.filter_by(portgroup_id=portgroup_id)
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir, query)

    def create_port(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()

        port = models.Port()
        port.update(values)
        with _session_for_write() as session:
            try:
                session.add(port)
                session.flush()
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

        try:
            with _session_for_write() as session:
                query = model_query(models.Port)
                query = add_port_filter(query, port_id)
                ref = query.one()
                ref.update(values)
                session.flush()
        except NoResultFound:
            raise exception.PortNotFound(port=port_id)
        except db_exc.DBDuplicateEntry:
            raise exception.MACAlreadyExists(mac=values['address'])
        return ref

    def destroy_port(self, port_id):
        with _session_for_write():
            query = model_query(models.Port)
            query = add_port_filter(query, port_id)
            count = query.delete()
            if count == 0:
                raise exception.PortNotFound(port=port_id)

    def get_portgroup_by_id(self, portgroup_id):
        query = model_query(models.Portgroup).filter_by(id=portgroup_id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=portgroup_id)

    def get_portgroup_by_uuid(self, portgroup_uuid):
        query = model_query(models.Portgroup).filter_by(uuid=portgroup_uuid)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=portgroup_uuid)

    def get_portgroup_by_address(self, address):
        query = model_query(models.Portgroup).filter_by(address=address)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=address)

    def get_portgroup_by_name(self, name):
        query = model_query(models.Portgroup).filter_by(name=name)
        try:
            return query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=name)

    def get_portgroup_list(self, limit=None, marker=None,
                           sort_key=None, sort_dir=None):
        return _paginate_query(models.Portgroup, limit, marker,
                               sort_key, sort_dir)

    def get_portgroups_by_node_id(self, node_id, limit=None, marker=None,
                                  sort_key=None, sort_dir=None):
        query = model_query(models.Portgroup)
        query = query.filter_by(node_id=node_id)
        return _paginate_query(models.Portgroup, limit, marker,
                               sort_key, sort_dir, query)

    def create_portgroup(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()

        portgroup = models.Portgroup()
        portgroup.update(values)
        with _session_for_write() as session:
            try:
                session.add(portgroup)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'name' in exc.columns:
                    raise exception.PortgroupDuplicateName(name=values['name'])
                elif 'address' in exc.columns:
                    raise exception.PortgroupMACAlreadyExists(
                        mac=values['address'])
                raise exception.PortgroupAlreadyExists(uuid=values['uuid'])
            return portgroup

    def update_portgroup(self, portgroup_id, values):
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing portgroup.")
            raise exception.InvalidParameterValue(err=msg)

        with _session_for_write() as session:
            try:
                query = model_query(models.Portgroup)
                query = add_portgroup_filter(query, portgroup_id)
                ref = query.one()
                ref.update(values)
                session.flush()
            except NoResultFound:
                raise exception.PortgroupNotFound(portgroup=portgroup_id)
            except db_exc.DBDuplicateEntry as exc:
                if 'name' in exc.columns:
                    raise exception.PortgroupDuplicateName(name=values['name'])
                elif 'address' in exc.columns:
                    raise exception.PortgroupMACAlreadyExists(
                        mac=values['address'])
                else:
                    raise
            return ref

    def destroy_portgroup(self, portgroup_id):
        def portgroup_not_empty(session):
            """Checks whether the portgroup does not have ports."""

            query = model_query(models.Port)
            query = add_port_filter_by_portgroup(query, portgroup_id)

            return query.count() != 0

        with _session_for_write() as session:
            if portgroup_not_empty(session):
                raise exception.PortgroupNotEmpty(portgroup=portgroup_id)

            query = model_query(models.Portgroup, session=session)
            query = add_identity_filter(query, portgroup_id)

            count = query.delete()
            if count == 0:
                raise exception.PortgroupNotFound(portgroup=portgroup_id)

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
            values['uuid'] = uuidutils.generate_uuid()

        chassis = models.Chassis()
        chassis.update(values)
        with _session_for_write() as session:
            try:
                session.add(chassis)
                session.flush()
            except db_exc.DBDuplicateEntry:
                raise exception.ChassisAlreadyExists(uuid=values['uuid'])
            return chassis

    def update_chassis(self, chassis_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Chassis.")
            raise exception.InvalidParameterValue(err=msg)

        with _session_for_write():
            query = model_query(models.Chassis)
            query = add_identity_filter(query, chassis_id)

            count = query.update(values)
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis_id)
            ref = query.one()
        return ref

    def destroy_chassis(self, chassis_id):
        def chassis_not_empty():
            """Checks whether the chassis does not have nodes."""

            query = model_query(models.Node)
            query = add_node_filter_by_chassis(query, chassis_id)

            return query.count() != 0

        with _session_for_write():
            if chassis_not_empty():
                raise exception.ChassisNotEmpty(chassis=chassis_id)

            query = model_query(models.Chassis)
            query = add_identity_filter(query, chassis_id)

            count = query.delete()
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis_id)

    def register_conductor(self, values, update_existing=False):
        with _session_for_write() as session:
            query = (model_query(models.Conductor)
                     .filter_by(hostname=values['hostname']))
            try:
                ref = query.one()
                if ref.online is True and not update_existing:
                    raise exception.ConductorAlreadyRegistered(
                        conductor=values['hostname'])
            except NoResultFound:
                ref = models.Conductor()
                session.add(ref)
            ref.update(values)
            # always set online and updated_at fields when registering
            # a conductor, especially when updating an existing one
            ref.update({'updated_at': timeutils.utcnow(),
                        'online': True})
        return ref

    def get_conductor(self, hostname):
        try:
            return (model_query(models.Conductor)
                    .filter_by(hostname=hostname, online=True)
                    .one())
        except NoResultFound:
            raise exception.ConductorNotFound(conductor=hostname)

    def unregister_conductor(self, hostname):
        with _session_for_write():
            query = (model_query(models.Conductor)
                     .filter_by(hostname=hostname, online=True))
            count = query.update({'online': False})
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    def touch_conductor(self, hostname):
        with _session_for_write():
            query = (model_query(models.Conductor)
                     .filter_by(hostname=hostname))
            # since we're not changing any other field, manually set updated_at
            # and since we're heartbeating, make sure that online=True
            count = query.update({'updated_at': timeutils.utcnow(),
                                  'online': True})
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    def clear_node_reservations_for_conductor(self, hostname):
        nodes = []
        with _session_for_write():
            query = (model_query(models.Node)
                     .filter_by(reservation=hostname))
            nodes = [node['uuid'] for node in query]
            query.update({'reservation': None})

        if nodes:
            nodes = ', '.join(nodes)
            LOG.warning(
                _LW('Cleared reservations held by %(hostname)s: '
                    '%(nodes)s'), {'hostname': hostname, 'nodes': nodes})

    def clear_node_target_power_state(self, hostname):
        nodes = []
        with _session_for_write():
            query = (model_query(models.Node)
                     .filter_by(reservation=hostname))
            query = query.filter(models.Node.target_power_state != sql.null())
            nodes = [node['uuid'] for node in query]
            query.update({'target_power_state': None,
                          'last_error': _("Pending power operation was "
                                          "aborted due to conductor "
                                          "restart")})

        if nodes:
            nodes = ', '.join(nodes)
            LOG.warning(
                _LW('Cleared target_power_state of the locked nodes in '
                    'powering process, their power state can be incorrect: '
                    '%(nodes)s'), {'nodes': nodes})

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

    def get_offline_conductors(self):
        interval = CONF.conductor.heartbeat_timeout
        limit = timeutils.utcnow() - datetime.timedelta(seconds=interval)
        result = (model_query(models.Conductor).filter_by()
                  .filter(models.Conductor.updated_at < limit)
                  .all())
        return [row['hostname'] for row in result]

    def touch_node_provisioning(self, node_id):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)
            count = query.update({'provision_updated_at': timeutils.utcnow()})
            if count == 0:
                raise exception.NodeNotFound(node_id)

    def _check_node_exists(self, node_id):
        if not model_query(models.Node).filter_by(id=node_id).scalar():
            raise exception.NodeNotFound(node=node_id)

    def set_node_tags(self, node_id, tags):
        # remove duplicate tags
        tags = set(tags)
        with _session_for_write() as session:
            self.unset_node_tags(node_id)
            node_tags = []
            for tag in tags:
                node_tag = models.NodeTag(tag=tag, node_id=node_id)
                session.add(node_tag)
                node_tags.append(node_tag)

        return node_tags

    def unset_node_tags(self, node_id):
        self._check_node_exists(node_id)
        with _session_for_write():
            model_query(models.NodeTag).filter_by(node_id=node_id).delete()

    def get_node_tags_by_node_id(self, node_id):
        self._check_node_exists(node_id)
        result = (model_query(models.NodeTag)
                  .filter_by(node_id=node_id)
                  .all())
        return result

    def add_node_tag(self, node_id, tag):
        node_tag = models.NodeTag(tag=tag, node_id=node_id)

        self._check_node_exists(node_id)
        try:
            with _session_for_write() as session:
                session.add(node_tag)
                session.flush()
        except db_exc.DBDuplicateEntry:
            # NOTE(zhenguo): ignore tags duplicates
            pass

        return node_tag

    def delete_node_tag(self, node_id, tag):
        self._check_node_exists(node_id)
        with _session_for_write():
            result = model_query(models.NodeTag).filter_by(
                node_id=node_id, tag=tag).delete()

            if not result:
                raise exception.NodeTagNotFound(node_id=node_id, tag=tag)

    def node_tag_exists(self, node_id, tag):
        q = model_query(models.NodeTag).filter_by(node_id=node_id, tag=tag)
        return model_query(q.exists()).scalar()

    def get_node_by_port_addresses(self, addresses):
        q = model_query(models.Node).distinct().join(models.Port)
        q = q.filter(models.Port.address.in_(addresses))

        try:
            return q.one()
        except NoResultFound:
            raise exception.NodeNotFound(
                _('Node with port addresses %s was not found')
                % addresses)
        except MultipleResultsFound:
            raise exception.NodeNotFound(
                _('Multiple nodes with port addresses %s were found')
                % addresses)
