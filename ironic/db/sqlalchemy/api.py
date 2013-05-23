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
from ironic.common import utils
from ironic.db import api
from ironic.db.sqlalchemy import models
from ironic.openstack.common.db.sqlalchemy import session as db_session
from ironic.openstack.common import log
from ironic.openstack.common import uuidutils

CONF = cfg.CONF
CONF.import_opt('sql_connection',
                'ironic.openstack.common.db.sqlalchemy.session')

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


def add_uuid_filter(query, value):
    if utils.is_int_like(value):
        return query.filter_by(id=value)
    elif uuidutils.is_uuid_like(value):
        return query.filter_by(uuid=value)
    else:
        raise exception.InvalidUUID(uuid=value)


def add_mac_filter(query, value):
    if utils.is_int_like(value):
        return query.filter_by(id=value)
    elif utils.is_valid_mac(value):
        return query.filter_by(address=value)
    else:
        raise exception.InvalidMAC(mac=value)


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    def get_nodes(self, columns):
        pass

    def get_associated_nodes(self):
        pass

    def get_unassociated_nodes(self):
        pass

    def reserve_node(self, node, values):
        if values.get('instance_uuid', None) is None:
            raise exception.IronicException(_("Instance UUID not specified"))

        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_uuid_filter(query, node)

            count = query.filter_by(instance_uuid=None).\
                        update(values)
            if count != 1:
                raise exception.IronicException(_(
                    "Failed to associate instance %(i)s to node %(n)s.") %
                        {'i': values['instance_uuid'], 'n': node})
            ref = query.one()

        return ref

    def create_node(self, values):
        node = models.Node()
        node.update(values)
        node.save()
        return node

    def get_node(self, node):
        query = model_query(models.Node)
        query = add_uuid_filter(query, node)

        try:
            result = query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node)

        return result

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
            query = add_uuid_filter(query, node)

            count = query.delete()
            if count != 1:
                raise exception.NodeNotFound(node=node)

    def update_node(self, node, values):
        session = get_session()
        with session.begin():
            query = model_query(models.Node, session=session)
            query = add_uuid_filter(query, node)

            print "Updating with %s." % values
            count = query.update(values,
                                 synchronize_session='fetch')
            if count != 1:
                raise exception.NodeNotFound(node=node)
            ref = query.one()
        return ref

    def get_port(self, port):
        query = model_query(models.Port)
        query = add_mac_filter(query, port)

        try:
            result = query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port)

        return result

    def get_port_by_vif(self, vif):
        pass

    def get_ports_by_node(self, node):
        session = get_session()

        if utils.is_int_like(node):
            query = session.query(models.Port).\
                        filter_by(node_id=node)
        else:
            query = session.query(models.Port).\
                        join(models.Node,
                             models.Port.node_id == models.Node.id).\
                        filter(models.Node.uuid == node)
        result = query.all()

        return result

    def create_port(self, values):
        port = models.Port()
        port.update(values)
        port.save()
        return port

    def update_port(self, port, values):
        session = get_session()
        with session.begin():
            query = model_query(models.Port, session=session)
            query = add_mac_filter(query, port)

            count = query.update(values)
            if count != 1:
                raise exception.PortNotFound(port=port)
            ref = query.one()
        return ref

    def destroy_port(self, port):
        session = get_session()
        with session.begin():
            query = model_query(models.Port, session=session)
            query = add_mac_filter(query, port)

            count = query.delete()
            if count != 1:
                raise exception.PortNotFound(port=port)
