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
import json
import threading

from oslo_concurrency import lockutils
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import orm as sa_orm
from oslo_db.sqlalchemy import utils as db_utils
from oslo_log import log
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
from osprofiler import sqlalchemy as osp_sqlalchemy
import sqlalchemy as sa
from sqlalchemy import or_
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import Load
from sqlalchemy.orm import selectinload
from sqlalchemy import sql

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import profiler
from ironic.common import release_mappings
from ironic.common import states
from ironic.common import utils
from ironic.conf import CONF
from ironic.db import api
from ironic.db.sqlalchemy import models


LOG = log.getLogger(__name__)


_CONTEXT = threading.local()


RESERVATION_SEMAPHORE = "reserve_node_db_lock"
synchronized = lockutils.synchronized_with_prefix('ironic-')

# NOTE(mgoddard): We limit the number of traits per node to 50 as this is the
# maximum number of traits per resource provider allowed in placement.
MAX_TRAITS_PER_NODE = 50


def get_backend():
    """The backend is this module itself."""
    return Connection()


def _session_for_read():
    return _wrap_session(enginefacade.reader.using(_CONTEXT))


# Please add @oslo_db_api.retry_on_deadlock decorator to all methods using
# _session_for_write (as deadlocks happen on write), so that oslo_db is able
# to retry in case of deadlocks.
def _session_for_write():
    return _wrap_session(enginefacade.writer.using(_CONTEXT))


def _wrap_session(session):
    if CONF.profiler.enabled and CONF.profiler.trace_sqlalchemy:
        session = osp_sqlalchemy.wrap_session(sa, session)
    return session


def _get_node_select():
    """Returns a SQLAlchemy Select Object for Nodes.

    This method returns a pre-formatted select object which models
    the entire Node object, allowing callers to operate on a node like
    they would have with an SQLAlchemy ORM Query Object.

    This object *also* performs two additional select queries, in the form
    of a selectin operation, to achieve the same results of a Join query,
    but without the join query itself, and the client side load.

    This method is best utilized when retrieving lists of nodes.

    Select objects in this fashion were  added as a result of SQLAlchemy 1.4
    in preparation for SQLAlchemy 2.0's release to provide a unified
    select interface.

    :returns: a select object
    """

    # NOTE(TheJulia): This returns a query in the SQLAlchemy 1.4->2.0
    # migration style as query model loading is deprecated.

    # This must use selectinload to avoid later need to invokededuplication.
    return (sa.select(models.Node)
            .options(selectinload(models.Node.tags),
                     selectinload(models.Node.traits)))


def _get_deploy_template_select_with_steps():
    """Return a select object for the DeployTemplate joined with steps.

    :returns: a select object.
    """
    return sa.select(
        models.DeployTemplate
    ).options(selectinload(models.DeployTemplate.steps))


def model_query(model, *args, **kwargs):
    """Query helper for simpler session usage.

    WARNING: DO NOT USE, unless you know exactly what your doing
    AND are okay with a transaction possibly hanging.

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


def add_identity_where(op, model, value):
    """Adds an identity filter to operation for where method.

    Filters results by ID, if supplied value is a valid integer.
    Otherwise attempts to filter results by UUID.

    :param op: Initial operation to add filter to.
               i.e. a update or delete statement.
    :param model: The SQLAlchemy model to apply.
    :param value: Value for filtering results by.
    :return: Modified query.
    """
    if strutils.is_int_like(value):
        return op.where(model.id == value)
    elif uuidutils.is_uuid_like(value):
        return op.where(model.uuid == value)
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
    if netutils.is_valid_mac(value):
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


def add_port_filter_by_node_owner(query, value):
    query = query.join(models.Node,
                       models.Port.node_id == models.Node.id)
    return query.filter(models.Node.owner == value)


def add_port_filter_by_node_project(query, value):
    query = query.join(models.Node,
                       models.Port.node_id == models.Node.id)
    return query.filter((models.Node.owner == value)
                        | (models.Node.lessee == value))


def add_portgroup_filter_by_node_project(query, value):
    query = query.join(models.Node,
                       models.Portgroup.node_id == models.Node.id)
    return query.filter((models.Node.owner == value)
                        | (models.Node.lessee == value))


def add_volume_conn_filter_by_node_project(query, value):
    query = query.join(models.Node,
                       models.VolumeConnector.node_id == models.Node.id)
    return query.filter((models.Node.owner == value)
                        | (models.Node.lessee == value))


def add_volume_target_filter_by_node_project(query, value):
    query = query.join(models.Node,
                       models.VolumeTarget.node_id == models.Node.id)
    return query.filter((models.Node.owner == value)
                        | (models.Node.lessee == value))


def add_portgroup_filter(query, value):
    """Adds a portgroup-specific filter to a query.

    Filters results by address, if supplied value is a valid MAC
    address. Otherwise attempts to filter results by identity.

    :param query: Initial query to add filter to.
    :param value: Value for filtering results by.
    :return: Modified query.
    """
    if netutils.is_valid_mac(value):
        return query.filter_by(address=value)
    else:
        return add_identity_where(query, models.Portgroup, value)


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


def add_allocation_filter_by_node(query, value):
    if strutils.is_int_like(value):
        return query.filter_by(node_id=value)
    else:
        query = query.join(models.Node,
                           models.Allocation.node_id == models.Node.id)
        return query.filter(models.Node.uuid == value)


def add_allocation_filter_by_conductor(query, value):
    if strutils.is_int_like(value):
        return query.filter_by(conductor_affinity=value)
    else:
        # Assume hostname and join with the conductor table
        query = query.join(
            models.Conductor,
            models.Allocation.conductor_affinity == models.Conductor.id)
        return query.filter(models.Conductor.hostname == value)


def _paginate_query(model, limit=None, marker=None, sort_key=None,
                    sort_dir=None, query=None, return_base_tuple=False):
    # NOTE(TheJulia): We can't just ask for the bool of query if it is
    # populated, so we need to ask if it is None.
    if query is None:
        query = sa.select(model)
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
    with _session_for_read() as session:
        # NOTE(TheJulia): SQLAlchemy 2.0 no longer returns pre-uniqued result
        # sets in ORM mode, so we need to explicitly ask for it to be unique
        # before returning it to the caller.
        if isinstance(query, sa_orm.Query):
            # The classic "Legacy" ORM query object result set which is
            # deprecated in advance of SQLAlchemy 2.0.
            # TODO(TheJulia): Calls of this style basically need to be
            # eliminated in ironic as returning this way does not allow
            # commit or rollback in enginefacade to occur until the returned
            # object is garbage collected as ORM Query objects allow
            # for DB interactions to occur after the fact, so it remains
            # connected to the DB..
            # Save the query.all() results, but don't return yet, so we
            # begin to exit and unwind the session.
            ref = query.all()
        else:
            # In this case, we have a sqlalchemy.sql.selectable.Select
            # (most likely) which utilizes the unified select interface.
            res = session.execute(query).fetchall()
            if len(res) == 0:
                # Return an empty list instead of a class with no objects.
                return []
            if return_base_tuple:
                # The caller expects a tuple, lets just give it to them.
                return res
            # Everything is a tuple in a resultset from the unified interface
            # but for objects, our model expects just object access,
            # so we extract and return them.
            ref = [r[0] for r in res]
    # Return the results to the caller, outside of the session context
    # if an ORM object, because we want the session to close.
    return ref


def _filter_active_conductors(query, interval=None):
    if interval is None:
        interval = CONF.conductor.heartbeat_timeout
    limit = timeutils.utcnow() - datetime.timedelta(seconds=interval)

    query = (query.filter(models.Conductor.online.is_(True))
             .filter(models.Conductor.updated_at >= limit))
    return query


def _zip_matching(a, b, key):
    """Zip two unsorted lists, yielding matching items or None.

    Each zipped item is a tuple taking one of three forms:

    (a[i], b[j]) if a[i] and b[j] are equal.
    (a[i], None) if a[i] is less than b[j] or b is empty.
    (None, b[j]) if a[i] is greater than b[j] or a is empty.

    Note that the returned list may be longer than either of the two
    lists.

    Adapted from https://stackoverflow.com/a/11426702.

    :param a: the first list.
    :param b: the second list.
    :param key: a function that generates a key used to compare items.
    """
    a = collections.deque(sorted(a, key=key))
    b = collections.deque(sorted(b, key=key))
    while a and b:
        k_a = key(a[0])
        k_b = key(b[0])
        if k_a == k_b:
            yield a.popleft(), b.popleft()
        elif k_a < k_b:
            yield a.popleft(), None
        else:
            yield None, b.popleft()
    # Consume any remaining items in each deque.
    for i in a:
        yield i, None
    for i in b:
        yield None, i


@profiler.trace_cls("db_api")
class Connection(api.Connection):
    """SqlAlchemy connection."""

    # NOTE(dtantsur): don't forget to update the get_nodeinfo_list docstring
    # in ironic/db/api.py when adding new filters!
    _NODE_QUERY_FIELDS = {'console_enabled', 'maintenance', 'retired',
                          'driver', 'resource_class', 'provision_state',
                          'uuid', 'id', 'fault', 'conductor_group',
                          'owner', 'lessee', 'instance_uuid'}
    _NODE_IN_QUERY_FIELDS = {'%s_in' % field: field
                             for field in ('uuid', 'provision_state', 'shard')}
    _NODE_NON_NULL_FILTERS = {'associated': 'instance_uuid',
                              'reserved': 'reservation',
                              'with_power_state': 'power_state',
                              'sharded': 'shard'}
    _NODE_FILTERS = ({'chassis_uuid', 'reserved_by_any_of',
                      'provisioned_before', 'inspection_started_before',
                      'description_contains', 'project'}
                     | _NODE_QUERY_FIELDS
                     | set(_NODE_IN_QUERY_FIELDS)
                     | set(_NODE_NON_NULL_FILTERS))

    def __init__(self):
        pass

    def _validate_nodes_filters(self, filters):
        if filters is None:
            filters = dict()
        unsupported_filters = set(filters).difference(self._NODE_FILTERS)
        if unsupported_filters:
            msg = _("SqlAlchemy API does not support "
                    "filtering by %s") % ', '.join(unsupported_filters)
            raise ValueError(msg)
        return filters

    def _add_nodes_filters(self, query, filters):
        filters = self._validate_nodes_filters(filters)
        for field in self._NODE_QUERY_FIELDS:
            if field in filters:
                query = query.filter_by(**{field: filters[field]})
        for key, field in self._NODE_IN_QUERY_FIELDS.items():
            if key in filters:
                query = query.filter(
                    getattr(models.Node, field).in_(filters[key]))
        for key, field in self._NODE_NON_NULL_FILTERS.items():
            if key in filters:
                column = getattr(models.Node, field)
                if filters[key]:
                    query = query.filter(column != sql.null())
                else:
                    query = query.filter(column == sql.null())

        if 'chassis_uuid' in filters:
            # get_chassis_by_uuid() to raise an exception if the chassis
            # is not found
            chassis_obj = self.get_chassis_by_uuid(filters['chassis_uuid'])
            query = query.filter_by(chassis_id=chassis_obj.id)
        if 'reserved_by_any_of' in filters:
            query = query.filter(models.Node.reservation.in_(
                filters['reserved_by_any_of']))
        if 'provisioned_before' in filters:
            limit = (timeutils.utcnow()
                     - datetime.timedelta(
                         seconds=filters['provisioned_before']))
            query = query.filter(models.Node.provision_updated_at < limit)
        if 'inspection_started_before' in filters:
            limit = ((timeutils.utcnow())
                     - (datetime.timedelta(
                         seconds=filters['inspection_started_before'])))
            query = query.filter(models.Node.inspection_started_at < limit)
        if 'description_contains' in filters:
            keyword = filters['description_contains']
            if keyword is not None:
                query = query.filter(
                    models.Node.description.like(r'%{}%'.format(keyword)))
        if 'project' in filters:
            project = filters['project']
            query = query.filter((models.Node.owner == project)
                                 | (models.Node.lessee == project))

        return query

    def _add_allocations_filters(self, query, filters):
        if filters is None:
            filters = dict()
        supported_filters = {'state', 'resource_class', 'node_uuid',
                             'conductor_affinity', 'owner'}
        unsupported_filters = set(filters).difference(supported_filters)
        if unsupported_filters:
            msg = _("SqlAlchemy API does not support "
                    "filtering by %s") % ', '.join(unsupported_filters)
            raise ValueError(msg)

        try:
            node_uuid = filters.pop('node_uuid')
        except KeyError:
            pass
        else:
            query = add_allocation_filter_by_node(query, node_uuid)

        try:
            conductor = filters.pop('conductor_affinity')
        except KeyError:
            pass
        else:
            query = add_allocation_filter_by_conductor(query, conductor)

        if filters:
            query = query.filter_by(**filters)
        return query

    def get_nodeinfo_list(self, columns=None, filters=None, limit=None,
                          marker=None, sort_key=None, sort_dir=None):
        # list-ify columns default values because it is bad form
        # to include a mutable list in function definitions.
        if columns is None:
            columns = [models.Node.id]
        else:
            columns = [getattr(models.Node, c) for c in columns]

        query = sa.select(*columns)
        query = self._add_nodes_filters(query, filters)
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir, query,
                               return_base_tuple=True)

    def get_node_list(self, filters=None, limit=None, marker=None,
                      sort_key=None, sort_dir=None, fields=None):
        if not fields:
            query = _get_node_select()
            query = self._add_nodes_filters(query, filters)
            return _paginate_query(models.Node, limit, marker,
                                   sort_key, sort_dir, query)
        else:
            # Shunt to the proper method to return the limited list.
            return self.get_node_list_columns(columns=fields, filters=filters,
                                              limit=limit, marker=marker,
                                              sort_key=sort_key,
                                              sort_dir=sort_dir)

    def get_node_list_columns(self, columns=None, filters=None, limit=None,
                              marker=None, sort_key=None, sort_dir=None):
        """Get a node list with specific fields/columns.

        :param columns: A list of columns to retrieve from the database
                        and populate into the object.
        :param filters: The requested database field filters in the form of
                        a dictionary with the applicable key, and filter
                        value.
        :param limit: Limit the number of returned nodes, default None.
        :param marker: Starting marker to generate a paginated result
                       set for the consumer.
        :param sort_key: Sort key to apply to the result set.
        :param sort_dir: Sort direction to apply to the result set.
        :returns: A list of Node objects based on the data model from
                  a SQLAlchemy result set, which the object layer can
                  use to convert the node into an Node object list.
        """
        traits_found = False
        use_columns = columns[:]
        if 'traits' in columns:
            # Traits is synthetic in the data model and not a direct
            # table column. As such, a different query pattern is used
            # with SQLAlchemy.
            traits_found = True
            use_columns.remove('traits')
        # Generate the column object list so SQLAlchemy only fulfills
        # the requested columns.
        use_columns = [getattr(models.Node, c) for c in use_columns]
        # In essence, traits (and anything else needed to generate the
        # composite objects) need to be reconciled without using a join
        # as multiple rows can be generated in the result set being returned
        # from the database server. In this case, with traits, we use
        # a selectinload pattern.
        if traits_found:
            query = sa.select(models.Node).options(
                selectinload(models.Node.traits),
                Load(models.Node).load_only(*use_columns)
            )
        else:
            # Note for others, if you ask for a whole model, it is
            # modeled, i.e. you can access it as an object.
            query = sa.select(models.NodeBase).options(
                Load(models.Node).load_only(*use_columns)
            )
        query = self._add_nodes_filters(query, filters)
        return _paginate_query(models.Node, limit, marker,
                               sort_key, sort_dir, query)

    def check_node_list(self, idents, project=None):
        mapping = {}
        if idents:
            idents = set(idents)
        else:
            return mapping

        uuids = {i for i in idents if uuidutils.is_uuid_like(i)}
        names = {i for i in idents if not uuidutils.is_uuid_like(i)
                 and utils.is_valid_logical_name(i)}
        missing = idents - set(uuids) - set(names)
        if missing:
            # Such nodes cannot exist, bailing out early
            raise exception.NodeNotFound(
                _("Nodes cannot be found: %s") % ', '.join(missing))

        with _session_for_read() as session:
            query = session.query(models.Node.uuid, models.Node.name).filter(
                sql.or_(models.Node.uuid.in_(uuids),
                        models.Node.name.in_(names))
            )
            if project:
                query = query.filter((models.Node.owner == project)
                                     | (models.Node.lessee == project))

            for row in query:
                if row[0] in idents:
                    mapping[row[0]] = row[0]
                if row[1] and row[1] in idents:
                    mapping[row[1]] = row[0]

        missing = idents - set(mapping)
        if missing:
            raise exception.NodeNotFound(
                _("Nodes cannot be found: %s") % ', '.join(missing))

        return mapping

    @synchronized(RESERVATION_SEMAPHORE, fair=True)
    def _reserve_node_place_lock(self, tag, node_id, node):
        try:
            # NOTE(TheJulia): We explicitly do *not* synch the session
            # so the other actions in the conductor do not become aware
            # that the lock is in place and believe they hold the lock.
            # This necessitates an overall lock in the code side, so
            # we avoid conditions where two separate threads can believe
            # they hold locks at the same time.
            with _session_for_write() as session:
                res = session.execute(
                    sa.update(models.Node).
                    where(models.Node.id == node.id).
                    where(models.Node.reservation == None).  # noqa
                    values(reservation=tag).
                    execution_options(synchronize_session=False))
                session.flush()
            node = self._get_node_by_id_no_joins(node.id)
            # NOTE(TheJulia): In SQLAlchemy 2.0 style, we don't
            # magically get a changed node as they moved from the
            # many ways to do things to singular ways to do things.
            if res.rowcount != 1:
                # Nothing updated and node exists. Must already be
                # locked.
                raise exception.NodeLocked(node=node.uuid,
                                           host=node.reservation)
        except NoResultFound:
            # In the event that someone has deleted the node on
            # another thread.
            raise exception.NodeNotFound(node=node_id)

    @oslo_db_api.retry_on_deadlock
    def reserve_node(self, tag, node_id):
        with _session_for_read() as session:
            try:
                # TODO(TheJulia): Figure out a good way to query
                # this so that we do it as light as possible without
                # the full object invocation, which will speed lock
                # activities. Granted, this is all at the DB level
                # so maybe that is okay in the grand scheme of things.
                query = session.query(models.Node)
                query = add_identity_filter(query, node_id)
                node = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)
            if node.reservation:
                # Fail fast, instead of attempt the update.
                raise exception.NodeLocked(node=node.uuid,
                                           host=node.reservation)
        self._reserve_node_place_lock(tag, node_id, node)
        # Return a node object as that is the contract for this method.
        return self.get_node_by_id(node.id)

    @oslo_db_api.retry_on_deadlock
    def release_node(self, tag, node_id):
        with _session_for_read() as session:
            try:
                query = session.query(models.Node)
                query = add_identity_filter(query, node_id)
                node = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)
        with _session_for_write() as session:
            try:
                res = session.execute(
                    sa.update(models.Node).
                    where(models.Node.id == node.id).
                    where(models.Node.reservation == tag).
                    values(reservation=None).
                    execution_options(synchronize_session=False)
                )
                node = self.get_node_by_id(node.id)
                if res.rowcount != 1:
                    if node.reservation is None:
                        raise exception.NodeNotLocked(node=node.uuid)
                    else:
                        raise exception.NodeLocked(node=node.uuid,
                                                   host=node['reservation'])
                session.flush()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

    @oslo_db_api.retry_on_deadlock
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

        # TODO(mgoddard): Support creating node with traits
        if 'traits' in values:
            msg = _("Cannot create node with traits.")
            raise exception.InvalidParameterValue(err=msg)

        node = models.Node()
        node.update(values)
        try:
            with _session_for_write() as session:
                session.add(node)
                # Set tags & traits to [] for new created node
                # NOTE(mgoddard): We need to set the tags and traits fields in
                # the session context, otherwise SQLAlchemy will try and fail
                # to lazy load the attributes, resulting in an exception being
                # raised.
                node['tags'] = []
                node['traits'] = []
                session.flush()
        except db_exc.DBDuplicateEntry as exc:
            if 'name' in exc.columns:
                raise exception.DuplicateName(name=values['name'])
            elif 'instance_uuid' in exc.columns:
                raise exception.InstanceAssociated(
                    instance_uuid=values['instance_uuid'],
                    node=values['uuid'])
            raise exception.NodeAlreadyExists(uuid=values['uuid'])
        return node

    def _get_node_by_id_no_joins(self, node_id):
        # TODO(TheJulia): Maybe replace with this with a minimal
        # "get these three fields" thing.
        try:
            with _session_for_read() as session:
                # Explicitly load NodeBase as the invocation of the
                # priamary model object reesults in the join query
                # triggering.
                return session.execute(
                    sa.select(models.NodeBase).filter_by(id=node_id).limit(1)
                ).scalars().first()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_id)

    def get_node_by_id(self, node_id):
        try:
            query = _get_node_select()
            with _session_for_read() as session:
                res = session.scalars(
                    query.filter_by(id=node_id).limit(1)
                ).unique().one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_id)
        return res

    def get_node_by_uuid(self, node_uuid):
        try:
            query = _get_node_select()
            with _session_for_read() as session:
                res = session.scalars(
                    query.filter_by(uuid=node_uuid).limit(1)
                ).unique().one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_uuid)
        return res

    def get_node_by_name(self, node_name):
        try:
            query = _get_node_select()
            with _session_for_read() as session:
                res = session.scalars(
                    query.filter_by(name=node_name).limit(1)
                ).unique().one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_name)
        return res

    def get_node_by_instance(self, instance):
        if not uuidutils.is_uuid_like(instance):
            raise exception.InvalidUUID(uuid=instance)

        try:
            query = _get_node_select()
            with _session_for_read() as session:
                res = session.scalars(
                    query.filter_by(instance_uuid=instance).limit(1)
                ).unique().one()
        except NoResultFound:
            raise exception.InstanceNotFound(instance_uuid=instance)
        return res

    @oslo_db_api.retry_on_deadlock
    def destroy_node(self, node_id):
        with _session_for_write() as session:
            query = session.query(models.Node)
            query = add_identity_filter(query, node_id)

            try:
                node_ref = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            # Orphan allocation, if any. On the API level this is only allowed
            # with maintenance on.
            node_ref.allocation_id = None
            node_ref.save(session)

            # Get node ID, if an UUID was supplied. The ID is
            # required for deleting all ports, attached to the node.
            if uuidutils.is_uuid_like(node_id):
                node_id = node_ref['id']

            port_query = session.query(models.Port)
            port_query = add_port_filter_by_node(port_query, node_id)
            port_query.delete()

            portgroup_query = session.query(models.Portgroup)
            portgroup_query = add_portgroup_filter_by_node(portgroup_query,
                                                           node_id)
            portgroup_query.delete()

            # Delete all tags attached to the node
            tag_query = session.query(models.NodeTag).filter_by(
                node_id=node_id)
            tag_query.delete()

            # Delete all traits attached to the node
            trait_query = session.query(
                models.NodeTrait).filter_by(node_id=node_id)
            trait_query.delete()

            volume_connector_query = session.query(
                models.VolumeConnector).filter_by(node_id=node_id)
            volume_connector_query.delete()

            volume_target_query = session.query(
                models.VolumeTarget).filter_by(node_id=node_id)
            volume_target_query.delete()

            # delete all bios attached to the node
            bios_settings_query = session.query(
                models.BIOSSetting).filter_by(node_id=node_id)
            bios_settings_query.delete()

            # delete all allocations for this node
            allocation_query = session.query(
                models.Allocation).filter_by(node_id=node_id)
            allocation_query.delete()

            # delete all history for this node
            history_query = session.query(
                models.NodeHistory).filter_by(node_id=node_id)
            history_query.delete()

            # delete all inventory for this node
            inventory_query = session.query(
                models.NodeInventory).filter_by(node_id=node_id)
            inventory_query.delete()

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

    @oslo_db_api.retry_on_deadlock
    def _do_update_node(self, node_id, values):
        with _session_for_write() as session:
            # NOTE(mgoddard): Don't issue a joined query for the update as this
            # does not work with PostgreSQL.
            query = session.query(models.Node)
            query = add_identity_filter(query, node_id)
            try:
                ref = query.with_for_update().one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            if 'provision_state' in values:
                values['provision_updated_at'] = timeutils.utcnow()
                if values['provision_state'] == states.INSPECTING:
                    values['inspection_started_at'] = timeutils.utcnow()
                    values['inspection_finished_at'] = None
                elif ((ref.provision_state == states.INSPECTING
                       or ref.provision_state == states.INSPECTWAIT)
                      and values['provision_state'] == states.MANAGEABLE):
                    values['inspection_finished_at'] = timeutils.utcnow()
                    values['inspection_started_at'] = None
                elif ((ref.provision_state == states.INSPECTING
                       or ref.provision_state == states.INSPECTWAIT)
                      and values['provision_state'] == states.INSPECTFAIL):
                    values['inspection_started_at'] = None

            ref.update(values)

        # Return the updated node model joined with all relevant fields.
        query = _get_node_select()
        query = add_identity_filter(query, node_id)
        # FIXME(TheJulia): This entire method needs to be re-written to
        # use the proper execution format for SQLAlchemy 2.0. Likely
        # A query, independent update, and a re-query on the transaction.
        with _session_for_read() as session:
            return session.execute(query).one()[0]

    def get_port_by_id(self, port_id):
        try:
            with _session_for_read() as session:
                query = session.query(models.Port).filter_by(id=port_id)
                res = query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port_id)
        return res

    def get_port_by_uuid(self, port_uuid):
        try:
            with _session_for_read() as session:
                query = session.query(models.Port).filter_by(uuid=port_uuid)
                res = query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port_uuid)
        return res

    def get_port_by_address(self, address, owner=None, project=None):
        try:
            with _session_for_read() as session:
                query = session.query(models.Port).filter_by(address=address)
                if owner:
                    query = add_port_filter_by_node_owner(query, owner)
                elif project:
                    query = add_port_filter_by_node_project(query, project)
                res = query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=address)
        return res

    def get_port_by_name(self, port_name):
        try:
            with _session_for_read() as session:
                query = session.query(models.Port).filter_by(name=port_name)
                res = query.one()
        except NoResultFound:
            raise exception.PortNotFound(port=port_name)
        return res

    def get_port_list(self, limit=None, marker=None,
                      sort_key=None, sort_dir=None, owner=None,
                      project=None):
        query = sa.select(models.Port)
        if owner:
            query = add_port_filter_by_node_owner(query, owner)
        elif project:
            query = add_port_filter_by_node_project(query, project)
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir, query)

    def get_ports_by_shards(self, shards, limit=None, marker=None,
                            sort_key=None, sort_dir=None):
        shard_node_ids = sa.select(models.Node) \
            .where(models.Node.shard.in_(shards)) \
            .with_only_columns(models.Node.id)
        with _session_for_read() as session:
            query = session.query(models.Port).filter(
                models.Port.node_id.in_(shard_node_ids))
            ports = _paginate_query(
                models.Port, limit, marker, sort_key, sort_dir, query)
        return ports

    def get_ports_by_node_id(self, node_id, limit=None, marker=None,
                             sort_key=None, sort_dir=None, owner=None,
                             project=None):
        query = sa.select(models.Port).where(models.Port.node_id == node_id)
        if owner:
            query = add_port_filter_by_node_owner(query, owner)
        elif project:
            query = add_port_filter_by_node_project(query, project)
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir, query)

    def get_ports_by_portgroup_id(self, portgroup_id, limit=None, marker=None,
                                  sort_key=None, sort_dir=None, owner=None,
                                  project=None):
        query = sa.select(models.Port).where(
            models.Port.portgroup_id == portgroup_id)
        if owner:
            query = add_port_filter_by_node_owner(query, owner)
        elif project:
            query = add_port_filter_by_node_project(query, project)
        return _paginate_query(models.Port, limit, marker,
                               sort_key, sort_dir, query)

    @oslo_db_api.retry_on_deadlock
    def create_port(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()

        port = models.Port()
        port.update(values)
        try:
            with _session_for_write() as session:
                session.add(port)
                session.flush()
        except db_exc.DBDuplicateEntry as exc:
            if 'address' in exc.columns:
                raise exception.MACAlreadyExists(mac=values['address'])
            raise exception.PortAlreadyExists(uuid=values['uuid'])
        return port

    @oslo_db_api.retry_on_deadlock
    def update_port(self, port_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Port.")
            raise exception.InvalidParameterValue(err=msg)
        try:
            with _session_for_write() as session:
                query = session.query(models.Port)
                query = add_port_filter(query, port_id)
                ref = query.one()
                ref.update(values)
                session.flush()
        except NoResultFound:
            raise exception.PortNotFound(port=port_id)
        except db_exc.DBDuplicateEntry as exc:
            if 'name' in exc.columns:
                raise exception.PortDuplicateName(name=values['name'])
            else:
                raise exception.MACAlreadyExists(mac=values['address'])
        return ref

    @oslo_db_api.retry_on_deadlock
    def destroy_port(self, port_id):
        with _session_for_write() as session:
            query = session.query(models.Port)
            query = add_port_filter(query, port_id)
            count = query.delete()
            if count == 0:
                raise exception.PortNotFound(port=port_id)

    def get_portgroup_by_id(self, portgroup_id, project=None):
        try:
            with _session_for_read() as session:
                query = session.query(models.Portgroup).filter_by(
                    id=portgroup_id)
                if project:
                    query = add_portgroup_filter_by_node_project(query,
                                                                 project)
                res = query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=portgroup_id)
        return res

    def get_portgroup_by_uuid(self, portgroup_uuid):
        try:
            with _session_for_read() as session:
                query = session.query(models.Portgroup).filter_by(
                    uuid=portgroup_uuid)
                res = query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=portgroup_uuid)
        return res

    def get_portgroup_by_address(self, address, project=None):
        try:
            with _session_for_read() as session:
                query = session.query(models.Portgroup).filter_by(
                    address=address)
                if project:
                    query = add_portgroup_filter_by_node_project(query,
                                                                 project)
                res = query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=address)
        return res

    def get_portgroup_by_name(self, name):
        try:
            with _session_for_read() as session:
                query = session.query(models.Portgroup).filter_by(name=name)
                res = query.one()
        except NoResultFound:
            raise exception.PortgroupNotFound(portgroup=name)
        return res

    def get_portgroup_list(self, limit=None, marker=None,
                           sort_key=None, sort_dir=None, project=None):
        query = sa.select(models.Portgroup)
        if project:
            query = add_portgroup_filter_by_node_project(query, project)
        return _paginate_query(models.Portgroup, limit, marker,
                               sort_key, sort_dir, query)

    def get_portgroups_by_node_id(self, node_id, limit=None, marker=None,
                                  sort_key=None, sort_dir=None, project=None):
        query = sa.select(models.Portgroup)
        query = query.where(models.Portgroup.node_id == node_id)
        if project:
            query = add_portgroup_filter_by_node_project(query, project)
        return _paginate_query(models.Portgroup, limit, marker,
                               sort_key, sort_dir, query)

    @oslo_db_api.retry_on_deadlock
    def create_portgroup(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()
        if not values.get('mode'):
            values['mode'] = CONF.default_portgroup_mode

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

    @oslo_db_api.retry_on_deadlock
    def update_portgroup(self, portgroup_id, values):
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing portgroup.")
            raise exception.InvalidParameterValue(err=msg)

        with _session_for_write() as session:
            try:
                query = session.query(models.Portgroup)
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

    @oslo_db_api.retry_on_deadlock
    def destroy_portgroup(self, portgroup_id):
        def portgroup_not_empty(session):
            """Checks whether the portgroup does not have ports."""
            with _session_for_read() as session:
                return session.scalar(
                    sa.select(
                        sa.func.count(models.Port.id)
                    ).where(models.Port.portgroup_id == portgroup_id)) != 0

        with _session_for_write() as session:
            if portgroup_not_empty(session):
                raise exception.PortgroupNotEmpty(portgroup=portgroup_id)

            query = sa.delete(models.Portgroup)
            query = add_identity_where(query, models.Portgroup, portgroup_id)

            count = session.execute(query).rowcount
            if count == 0:
                raise exception.PortgroupNotFound(portgroup=portgroup_id)

    def get_chassis_by_id(self, chassis_id):
        query = sa.select(models.Chassis).where(
            models.Chassis.id == chassis_id)

        try:
            with _session_for_read() as session:
                return session.execute(query).one()[0]
        except NoResultFound:
            raise exception.ChassisNotFound(chassis=chassis_id)

    def get_chassis_by_uuid(self, chassis_uuid):
        query = sa.select(models.Chassis).where(
            models.Chassis.uuid == chassis_uuid)

        try:
            with _session_for_read() as session:
                return session.execute(query).one()[0]
        except NoResultFound:
            raise exception.ChassisNotFound(chassis=chassis_uuid)

    def get_chassis_list(self, limit=None, marker=None,
                         sort_key=None, sort_dir=None):
        return _paginate_query(models.Chassis, limit, marker,
                               sort_key, sort_dir)

    @oslo_db_api.retry_on_deadlock
    def create_chassis(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()

        chassis = models.Chassis()
        chassis.update(values)
        try:
            with _session_for_write() as session:
                session.add(chassis)
                session.flush()
        except db_exc.DBDuplicateEntry:
            raise exception.ChassisAlreadyExists(uuid=values['uuid'])
        return chassis

    @oslo_db_api.retry_on_deadlock
    def update_chassis(self, chassis_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Chassis.")
            raise exception.InvalidParameterValue(err=msg)

        with _session_for_write() as session:
            query = session.query(models.Chassis)
            query = add_identity_where(query, models.Chassis, chassis_id)

            count = query.update(values)
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis_id)
            ref = query.one()
        return ref

    @oslo_db_api.retry_on_deadlock
    def destroy_chassis(self, chassis_id):
        with _session_for_write() as session:
            query = session.query(models.Node)
            query = add_node_filter_by_chassis(query, chassis_id)

            if query.count() != 0:
                raise exception.ChassisNotEmpty(chassis=chassis_id)

            query = session.query(models.Chassis)
            query = add_identity_filter(query, chassis_id)

            count = query.delete()
            if count != 1:
                raise exception.ChassisNotFound(chassis=chassis_id)

    @oslo_db_api.retry_on_deadlock
    def register_conductor(self, values, update_existing=False):
        with _session_for_write() as session:
            query = (session.query(models.Conductor)
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

    def get_conductor_list(self, limit=None, marker=None,
                           sort_key=None, sort_dir=None):
        return _paginate_query(models.Conductor, limit, marker,
                               sort_key, sort_dir)

    def get_conductor(self, hostname, online=True):
        try:
            query = sa.select(models.Conductor).where(
                models.Conductor.hostname == hostname)
            if online is not None:
                query = query.where(models.Conductor.online == online)
            with _session_for_read() as session:
                res = session.execute(query).one()[0]
                return res
        except NoResultFound:
            raise exception.ConductorNotFound(conductor=hostname)

    @oslo_db_api.retry_on_deadlock
    def unregister_conductor(self, hostname):
        with _session_for_write() as session:
            query = sa.update(models.Conductor).where(
                models.Conductor.hostname == hostname,
                models.Conductor.online == True).values(  # noqa
                    online=False)
            count = session.execute(query).rowcount
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    @oslo_db_api.retry_on_deadlock
    def touch_conductor(self, hostname):
        with _session_for_write() as session:
            query = sa.update(models.Conductor).where(
                models.Conductor.hostname == hostname
            ).values({
                'updated_at': timeutils.utcnow(),
                'online': True}
            ).execution_options(synchronize_session=False)
            res = session.execute(query)
            count = res.rowcount
        if count == 0:
            raise exception.ConductorNotFound(conductor=hostname)

    @oslo_db_api.retry_on_deadlock
    def clear_node_reservations_for_conductor(self, hostname):
        nodes = []
        with _session_for_write() as session:
            query = (session.query(models.Node)
                     .filter(models.Node.reservation.ilike(hostname)))
            nodes = [node['uuid'] for node in query]
            query.update({'reservation': None}, synchronize_session=False)

        if nodes:
            nodes = ', '.join(nodes)
            LOG.warning(
                'Cleared reservations held by %(hostname)s: '
                '%(nodes)s', {'hostname': hostname, 'nodes': nodes})

    @oslo_db_api.retry_on_deadlock
    def clear_node_target_power_state(self, hostname):
        nodes = []
        with _session_for_write() as session:
            query = (session.query(models.Node)
                     .filter(models.Node.reservation.ilike(hostname)))
            query = query.filter(models.Node.target_power_state != sql.null())
            nodes = [node['uuid'] for node in query]
            query.update({'target_power_state': None,
                          'last_error': _("Pending power operation was "
                                          "aborted due to conductor "
                                          "restart")},
                         synchronize_session=False)

        if nodes:
            nodes = ', '.join(nodes)
            LOG.warning(
                'Cleared target_power_state of the locked nodes in '
                'powering process, their power state can be incorrect: '
                '%(nodes)s', {'nodes': nodes})

    def get_active_hardware_type_dict(self, use_groups=False):
        with _session_for_read() as session:
            # TODO(TheJulia): We should likely take a look at this
            # joined query, as we may not be getting what we expect.
            # Metal3 logs upwards of 200 rows returned with multiple datetime
            # columns.
            # Given dualing datetime fields, we really can't just expect
            # requesting a unique set to "just work".
            query = (session.query(models.ConductorHardwareInterfaces,
                                   models.Conductor)
                     .join(models.Conductor))
            result = _filter_active_conductors(query)

            d2c = collections.defaultdict(set)
            for iface_row, cdr_row in result:
                hw_type = iface_row['hardware_type']
                if use_groups:
                    key = '%s:%s' % (cdr_row['conductor_group'], hw_type)
                else:
                    key = hw_type
                d2c[key].add(cdr_row['hostname'])
        return d2c

    def get_offline_conductors(self, field='hostname'):
        with _session_for_read() as session:
            field = getattr(models.Conductor, field)
            interval = CONF.conductor.heartbeat_timeout
            limit = timeutils.utcnow() - datetime.timedelta(seconds=interval)
            result = (session.query(field)
                      .filter(models.Conductor.updated_at < limit))
            return [row[0] for row in result]

    def get_online_conductors(self):
        with _session_for_read() as session:
            query = session.query(models.Conductor.hostname)
            query = _filter_active_conductors(query)
            return [row[0] for row in query]

    def list_conductor_hardware_interfaces(self, conductor_id):
        with _session_for_read() as session:
            query = (session.query(models.ConductorHardwareInterfaces)
                     .filter_by(conductor_id=conductor_id))
            ref = query.all()
        return ref

    def list_hardware_type_interfaces(self, hardware_types):
        with _session_for_read() as session:
            query = (session.query(models.ConductorHardwareInterfaces,
                                   models.Conductor)
                     .join(models.Conductor)
                     .filter(models.ConductorHardwareInterfaces.hardware_type
                             .in_(hardware_types)))

            query = _filter_active_conductors(query)
            return [row[0] for row in query]

    @oslo_db_api.retry_on_deadlock
    def register_conductor_hardware_interfaces(self, conductor_id, interfaces):
        with _session_for_write() as session:
            try:
                for iface in interfaces:
                    conductor_hw_iface = models.ConductorHardwareInterfaces()
                    conductor_hw_iface['conductor_id'] = conductor_id
                    for k, v in iface.items():
                        conductor_hw_iface[k] = v
                    # TODO(TheJulia): Uhh... We should try to do this as one
                    # bulk operation and not insert each row.
                    session.add(conductor_hw_iface)
                session.flush()
            except db_exc.DBDuplicateEntry as e:
                r = exception.ConductorHardwareInterfacesAlreadyRegistered(
                    row=str(e.inner_exception.params))
                raise r

    @oslo_db_api.retry_on_deadlock
    def unregister_conductor_hardware_interfaces(self, conductor_id):
        with _session_for_write() as session:
            query = (session.query(models.ConductorHardwareInterfaces)
                     .filter_by(conductor_id=conductor_id))
            query.delete()

    @oslo_db_api.retry_on_deadlock
    def touch_node_provisioning(self, node_id):
        with _session_for_write() as session:
            query = session.query(models.Node)
            query = add_identity_filter(query, node_id)
            count = query.update({'provision_updated_at': timeutils.utcnow()})
            if count == 0:
                raise exception.NodeNotFound(node=node_id)

    def _check_node_exists(self, session, node_id):
        if not session.query(models.Node).where(
                models.Node.id == node_id).scalar():
            raise exception.NodeNotFound(node=node_id)

    @oslo_db_api.retry_on_deadlock
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

    @oslo_db_api.retry_on_deadlock
    def unset_node_tags(self, node_id):
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            session.query(models.NodeTag).filter_by(node_id=node_id).delete()

    def get_node_tags_by_node_id(self, node_id):
        with _session_for_read() as session:
            self._check_node_exists(session, node_id)
            result = (session.query(models.NodeTag)
                      .filter_by(node_id=node_id)
                      .all())
        return result

    @oslo_db_api.retry_on_deadlock
    def add_node_tag(self, node_id, tag):
        try:
            with _session_for_write() as session:
                node_tag = models.NodeTag(tag=tag, node_id=node_id)

                self._check_node_exists(session, node_id)
                session.add(node_tag)
                session.flush()
        except db_exc.DBDuplicateEntry:
            # NOTE(zhenguo): ignore tags duplicates
            pass

        return node_tag

    @oslo_db_api.retry_on_deadlock
    def delete_node_tag(self, node_id, tag):
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            result = session.query(models.NodeTag).filter_by(
                node_id=node_id, tag=tag).delete()

        if not result:
            raise exception.NodeTagNotFound(node_id=node_id, tag=tag)

    def node_tag_exists(self, node_id, tag):
        with _session_for_read() as session:
            self._check_node_exists(session, node_id)
            q = session.query(models.NodeTag).filter_by(
                node_id=node_id, tag=tag)
            return session.query(q.exists()).scalar()

    def get_node_by_port_addresses(self, addresses):
        q = _get_node_select()
        q = q.distinct().join(models.Port)
        q = q.filter(models.Port.address.in_(addresses))

        try:
            # FIXME(TheJulia): This needs to be updated to be
            # an explicit query to identify the node for SQLAlchemy.
            with _session_for_read() as session:
                # Always return the first element, since we always
                # get a tuple from sqlalchemy.
                return session.execute(q).one()[0]
        except NoResultFound:
            raise exception.NodeNotFound(
                _('Node with port addresses %s was not found')
                % addresses)
        except MultipleResultsFound:
            raise exception.NodeNotFound(
                _('Multiple nodes with port addresses %s were found')
                % addresses)

    def get_volume_connector_list(self, limit=None, marker=None,
                                  sort_key=None, sort_dir=None, project=None):
        query = sa.select(models.VolumeConnector)
        if project:
            query = add_volume_conn_filter_by_node_project(query, project)
        return _paginate_query(models.VolumeConnector, limit, marker,
                               sort_key, sort_dir, query)

    def get_volume_connector_by_id(self, db_id):
        try:
            with _session_for_read() as session:
                query = session.query(models.VolumeConnector).filter_by(
                    id=db_id)
                res = query.one()
        except NoResultFound:
            raise exception.VolumeConnectorNotFound(connector=db_id)
        return res

    def get_volume_connector_by_uuid(self, connector_uuid):
        try:
            with _session_for_read() as session:
                query = session.query(models.VolumeConnector).filter_by(
                    uuid=connector_uuid)
                res = query.one()
        except NoResultFound:
            raise exception.VolumeConnectorNotFound(connector=connector_uuid)
        return res

    def get_volume_connectors_by_node_id(self, node_id, limit=None,
                                         marker=None, sort_key=None,
                                         sort_dir=None, project=None):
        query = sa.select(models.VolumeConnector).where(
            models.VolumeConnector.node_id == node_id)
        if project:
            add_volume_conn_filter_by_node_project(query, project)
        return _paginate_query(models.VolumeConnector, limit, marker,
                               sort_key, sort_dir, query)

    @oslo_db_api.retry_on_deadlock
    def create_volume_connector(self, connector_info):
        if 'uuid' not in connector_info:
            connector_info['uuid'] = uuidutils.generate_uuid()

        connector = models.VolumeConnector()
        connector.update(connector_info)
        with _session_for_write() as session:
            try:
                session.add(connector)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'type' in exc.columns:
                    raise exception.VolumeConnectorTypeAndIdAlreadyExists(
                        type=connector_info['type'],
                        connector_id=connector_info['connector_id'])
                raise exception.VolumeConnectorAlreadyExists(
                    uuid=connector_info['uuid'])
            return connector

    @oslo_db_api.retry_on_deadlock
    def update_volume_connector(self, ident, connector_info):
        if 'uuid' in connector_info:
            msg = _("Cannot overwrite UUID for an existing Volume Connector.")
            raise exception.InvalidParameterValue(err=msg)

        try:
            with _session_for_write() as session:
                query = session.query(models.VolumeConnector)
                query = add_identity_filter(query, ident)
                ref = query.one()
                orig_type = ref['type']
                orig_connector_id = ref['connector_id']
                ref.update(connector_info)
                session.flush()
        except db_exc.DBDuplicateEntry:
            raise exception.VolumeConnectorTypeAndIdAlreadyExists(
                type=connector_info.get('type', orig_type),
                connector_id=connector_info.get('connector_id',
                                                orig_connector_id))
        except NoResultFound:
            raise exception.VolumeConnectorNotFound(connector=ident)
        return ref

    @oslo_db_api.retry_on_deadlock
    def destroy_volume_connector(self, ident):
        with _session_for_write() as session:
            query = session.query(models.VolumeConnector)
            query = add_identity_filter(query, ident)
            count = query.delete()
            if count == 0:
                raise exception.VolumeConnectorNotFound(connector=ident)

    def get_volume_target_list(self, limit=None, marker=None,
                               sort_key=None, sort_dir=None, project=None):
        query = sa.select(models.VolumeTarget)
        if project:
            query = add_volume_target_filter_by_node_project(query, project)
        return _paginate_query(models.VolumeTarget, limit, marker,
                               sort_key, sort_dir, query)

    def get_volume_target_by_id(self, db_id):
        try:
            with _session_for_read() as session:
                query = session.query(models.VolumeTarget).where(
                    models.VolumeTarget.id == db_id)
                res = query.one()
        except NoResultFound:
            raise exception.VolumeTargetNotFound(target=db_id)
        return res

    def get_volume_target_by_uuid(self, uuid):
        try:
            with _session_for_read() as session:
                query = session.query(models.VolumeTarget).filter_by(
                    uuid=uuid)
                res = query.one()
        except NoResultFound:
            raise exception.VolumeTargetNotFound(target=uuid)
        return res

    def get_volume_targets_by_node_id(self, node_id, limit=None, marker=None,
                                      sort_key=None, sort_dir=None,
                                      project=None):
        query = sa.select(models.VolumeTarget).where(
            models.VolumeTarget.node_id == node_id)
        if project:
            add_volume_target_filter_by_node_project(query, project)
        return _paginate_query(models.VolumeTarget, limit, marker, sort_key,
                               sort_dir, query)

    def get_volume_targets_by_volume_id(self, volume_id, limit=None,
                                        marker=None, sort_key=None,
                                        sort_dir=None, project=None):
        query = sa.select(models.VolumeTarget).where(
            models.VolumeTarget.volume_id == volume_id)
        if project:
            query = add_volume_target_filter_by_node_project(query, project)
        return _paginate_query(models.VolumeTarget, limit, marker, sort_key,
                               sort_dir, query)

    @oslo_db_api.retry_on_deadlock
    def create_volume_target(self, target_info):
        if 'uuid' not in target_info:
            target_info['uuid'] = uuidutils.generate_uuid()

        target = models.VolumeTarget()
        target.update(target_info)
        with _session_for_write() as session:
            try:
                session.add(target)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'boot_index' in exc.columns:
                    raise exception.VolumeTargetBootIndexAlreadyExists(
                        boot_index=target_info['boot_index'])
                raise exception.VolumeTargetAlreadyExists(
                    uuid=target_info['uuid'])
            return target

    @oslo_db_api.retry_on_deadlock
    def update_volume_target(self, ident, target_info):
        if 'uuid' in target_info:
            msg = _("Cannot overwrite UUID for an existing Volume Target.")
            raise exception.InvalidParameterValue(err=msg)

        try:
            with _session_for_write() as session:
                query = session.query(models.VolumeTarget)
                query = add_identity_filter(query, ident)
                ref = query.one()
                orig_boot_index = ref['boot_index']
                ref.update(target_info)
                session.flush()
        except db_exc.DBDuplicateEntry:
            raise exception.VolumeTargetBootIndexAlreadyExists(
                boot_index=target_info.get('boot_index', orig_boot_index))
        except NoResultFound:
            raise exception.VolumeTargetNotFound(target=ident)
        return ref

    @oslo_db_api.retry_on_deadlock
    def destroy_volume_target(self, ident):
        with _session_for_write() as session:
            query = session.query(models.VolumeTarget)
            query = add_identity_filter(query, ident)
            count = query.delete()
            if count == 0:
                raise exception.VolumeTargetNotFound(target=ident)

    def get_not_versions(self, model_name, versions):
        """Returns objects with versions that are not the specified versions.

        This returns objects with versions that are not the specified versions.
        Objects with null versions (there shouldn't be any) are also returned.

        :param model_name: the name of the model (class) of desired objects
        :param versions: list of versions of objects not to be returned
        :returns: list of the DB objects
        :raises: IronicException if there is no class associated with the name
        """
        if not versions:
            return []

        if model_name == 'Node':
            model_name = 'NodeBase'
        model = models.get_class(model_name)

        # NOTE(rloo): .notin_ does not handle null:
        # http://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.operators.ColumnOperators.notin_
        query = model_query(model).filter(
            sql.or_(model.version == sql.null(),
                    model.version.notin_(versions)))
        return query.all()

    def check_versions(self, ignore_models=(), permit_initial_version=False):
        """Checks the whole database for incompatible objects.

        This scans all the tables in search of objects that are not supported;
        i.e., those that are not specified in
        `ironic.common.release_mappings.RELEASE_MAPPING`. This includes objects
        that have null 'version' values.

        :param ignore_models: List of model names to skip.
        :param permit_initial_version: Boolean, default False, to permit a
                                       NoSuchTableError exception to be raised
                                       by SQLAlchemy and accordingly bypass
                                       when an object has it's initial object
                                       version.
        :returns: A Boolean. True if all the objects have supported versions;
                  False otherwise.
        """
        object_versions = release_mappings.get_object_versions()
        table_missing_ok = False
        models_to_check = models.Base.__subclasses__()
        # We need to append Node to the list as it is a subclass of
        # NodeBase, which is intentional to delineate excess queries.
        models_to_check.append(models.Node)
        for model in models_to_check:
            if model.__name__ not in object_versions:
                continue

            if model.__name__ in ignore_models:
                continue

            supported_versions = object_versions[model.__name__]
            if not supported_versions:
                continue

            if permit_initial_version and supported_versions == {'1.0'}:
                # We're getting called from someplace it is okay to handle
                # a missing table, i.e. database upgrades which will create
                # the table *and* the field version is 1.0, which means we
                # are likely about to *create* the table, but first have to
                # pass the version/compatability checking logic.
                table_missing_ok = True

            # NOTE(mgagne): Additional safety check to detect old database
            # version which does not have the 'version' columns available.
            # This usually means a skip version upgrade is attempted
            # from a version earlier than Pike which added
            # those columns required for the next check.
            try:
                engine = enginefacade.reader.get_engine()
                if not db_utils.column_exists(engine,
                                              model.__tablename__,
                                              model.version.name):
                    raise exception.DatabaseVersionTooOld()
            except sa.exc.NoSuchTableError:
                if table_missing_ok:
                    # This is to be expected, it is okay. Moving along.
                    LOG.warning('Observed missing table while performing '
                                'upgrade version checking. This is not fatal '
                                'as the expected version is only 1.0 and '
                                'the check has been called before the table '
                                'is to be created. Model: %s',
                                model.__tablename__)
                    continue
                raise

            # NOTE(rloo): we use model.version, not model, because we
            #             know that the object has a 'version' column
            #             but we don't know whether the entire object is
            #             compatible with its (old) DB representation.
            # NOTE(rloo): .notin_ does not handle null:
            # http://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.operators.ColumnOperators.notin_
            with _session_for_read() as session:
                query = session.query(model.version).filter(
                    sql.or_(model.version == sql.null(),
                            model.version.notin_(supported_versions)))
                if query.count():
                    return False

        return True

    @oslo_db_api.retry_on_deadlock
    def update_to_latest_versions(self, context, max_count):
        """Updates objects to their latest known versions.

        This scans all the tables and for objects that are not in their latest
        version, updates them to that version.

        :param context: the admin context
        :param max_count: The maximum number of objects to migrate. Must be
                          >= 0. If zero, all the objects will be migrated.
        :returns: A 2-tuple, 1. the total number of objects that need to be
                  migrated (at the beginning of this call) and 2. the number
                  of migrated objects.
        """
        # NOTE(rloo): 'master' has the most recent (latest) versions.
        mapping = release_mappings.RELEASE_MAPPING['master']['objects']
        total_to_migrate = 0
        total_migrated = 0
        all_models = models.Base.__subclasses__()
        all_models.append(models.Node)
        sql_models = [model for model in all_models
                      if model.__name__ in mapping]
        with _session_for_read() as session:
            for model in sql_models:
                version = mapping[model.__name__][0]
                query = session.query(model).filter(model.version != version)
                total_to_migrate += query.count()

        if not total_to_migrate:
            return total_to_migrate, 0

        # NOTE(xek): Each of these operations happen in different transactions.
        # This is to ensure a minimal load on the database, but at the same
        # time it can cause an inconsistency in the amount of total and
        # migrated objects returned (total could be > migrated). This is
        # because some objects may have already migrated or been deleted from
        # the database between the time the total was computed (above) to the
        # time we do the updating (below).
        #
        # By the time this script is run, only the new release version is
        # running, so the impact of this error will be minimal - e.g. the
        # operator will run this script more than once to ensure that all
        # data have been migrated.

        # If max_count is zero, we want to migrate all the objects.
        max_to_migrate = max_count or total_to_migrate

        for model in sql_models:
            use_node_id = False
            if (not hasattr(model, 'id') and hasattr(model, 'node_id')):
                use_node_id = True
            version = mapping[model.__name__][0]
            num_migrated = 0
            with _session_for_write() as session:
                query = session.query(model).filter(model.version != version)
                # NOTE(rloo) Caution here; after doing query.count(), it is
                #            possible that the value is different in the
                #            next invocation of the query.
                if max_to_migrate < query.count():
                    # Only want to update max_to_migrate objects; cannot use
                    # sql's limit(), so we generate a new query with
                    # max_to_migrate objects.
                    ids = []
                    for obj in query.slice(0, max_to_migrate):
                        if not use_node_id:
                            ids.append(obj['id'])
                        else:
                            # BIOSSettings, NodeTrait, NodeTag do not have id
                            # columns, fallback to node_id as they both have
                            # it.
                            ids.append(obj['node_id'])
                    if not use_node_id:
                        num_migrated = (
                            session.query(model).
                            filter(sql.and_(model.id.in_(ids),
                                            model.version != version)).
                            update({model.version: version},
                                   synchronize_session=False))
                    else:
                        num_migrated = (
                            session.query(model).
                            filter(sql.and_(model.node_id.in_(ids),
                                            model.version != version)).
                            update({model.version: version},
                                   synchronize_session=False))
                else:
                    num_migrated = (
                        session.query(model).
                        filter(model.version != version).
                        update({model.version: version},
                               synchronize_session=False))

            total_migrated += num_migrated
            max_to_migrate -= num_migrated
            if max_to_migrate <= 0:
                break

        return total_to_migrate, total_migrated

    @staticmethod
    def _verify_max_traits_per_node(node_id, num_traits):
        """Verify that an operation would not exceed the per-node trait limit.

        :param node_id: The ID of a node.
        :param num_traits: The number of traits the node would have after the
            operation.
        :raises: InvalidParameterValue if the operation would exceed the
            per-node trait limit.
        """
        if num_traits > MAX_TRAITS_PER_NODE:
            msg = (_("Could not modify traits for node %(node_id)s as it "
                     "would exceed the maximum number of traits per node "
                     "(%(num_traits)d vs. %(max_traits)d)")
                   % {'node_id': node_id, 'num_traits': num_traits,
                      'max_traits': MAX_TRAITS_PER_NODE})
            raise exception.InvalidParameterValue(err=msg)

    @oslo_db_api.retry_on_deadlock
    def set_node_traits(self, node_id, traits, version):
        # Remove duplicate traits
        traits = set(traits)

        self._verify_max_traits_per_node(node_id, len(traits))

        with _session_for_write() as session:
            # NOTE(mgoddard): Node existence is checked in unset_node_traits.
            self.unset_node_traits(node_id)
            node_traits = []
            for trait in traits:
                node_trait = models.NodeTrait(trait=trait, node_id=node_id,
                                              version=version)
                session.add(node_trait)
                node_traits.append(node_trait)

        return node_traits

    @oslo_db_api.retry_on_deadlock
    def unset_node_traits(self, node_id):
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            session.query(models.NodeTrait).filter_by(node_id=node_id).delete()

    def get_node_traits_by_node_id(self, node_id):
        with _session_for_read() as session:
            self._check_node_exists(session, node_id)
            result = (session.query(models.NodeTrait)
                      .filter_by(node_id=node_id)
                      .all())
        return result

    @oslo_db_api.retry_on_deadlock
    def add_node_trait(self, node_id, trait, version):
        node_trait = models.NodeTrait(trait=trait, node_id=node_id,
                                      version=version)

        try:
            with _session_for_write() as session:
                self._check_node_exists(session, node_id)

                session.add(node_trait)
                session.flush()

                num_traits = (session.query(models.NodeTrait)
                              .filter_by(node_id=node_id).count())
                self._verify_max_traits_per_node(node_id, num_traits)
        except db_exc.DBDuplicateEntry:
            # NOTE(mgoddard): Ignore traits duplicates
            pass

        return node_trait

    @oslo_db_api.retry_on_deadlock
    def delete_node_trait(self, node_id, trait):
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            result = session.query(models.NodeTrait).filter_by(
                node_id=node_id, trait=trait).delete()

        if not result:
            raise exception.NodeTraitNotFound(node_id=node_id, trait=trait)

    def node_trait_exists(self, node_id, trait):
        with _session_for_read() as session:
            self._check_node_exists(session, node_id)
            q = session.query(
                models.NodeTrait).filter_by(node_id=node_id, trait=trait)
            return session.query(q.exists()).scalar()

    @oslo_db_api.retry_on_deadlock
    def create_bios_setting_list(self, node_id, settings, version):
        bios_settings = []
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            try:
                for setting in settings:
                    bios_setting = models.BIOSSetting(
                        node_id=node_id,
                        name=setting['name'],
                        value=setting['value'],
                        attribute_type=setting.get('attribute_type'),
                        allowable_values=setting.get('allowable_values'),
                        lower_bound=setting.get('lower_bound'),
                        max_length=setting.get('max_length'),
                        min_length=setting.get('min_length'),
                        read_only=setting.get('read_only'),
                        reset_required=setting.get('reset_required'),
                        unique=setting.get('unique'),
                        upper_bound=setting.get('upper_bound'),
                        version=version)
                    bios_settings.append(bios_setting)
                    session.add(bios_setting)
                session.flush()
            except db_exc.DBDuplicateEntry:
                raise exception.BIOSSettingAlreadyExists(
                    node=node_id, name=setting['name'])
        return bios_settings

    @oslo_db_api.retry_on_deadlock
    def update_bios_setting_list(self, node_id, settings, version):
        bios_settings = []
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            try:
                for setting in settings:
                    query = session.query(models.BIOSSetting).filter_by(
                        node_id=node_id, name=setting['name'])
                    ref = query.one()
                    ref.update({'value': setting['value'],
                                'attribute_type':
                                setting.get('attribute_type'),
                                'allowable_values':
                                setting.get('allowable_values'),
                                'lower_bound': setting.get('lower_bound'),
                                'max_length': setting.get('max_length'),
                                'min_length': setting.get('min_length'),
                                'read_only': setting.get('read_only'),
                                'reset_required':
                                setting.get('reset_required'),
                                'unique': setting.get('unique'),
                                'upper_bound': setting.get('upper_bound'),
                                'version': version})
                    bios_settings.append(ref)
                session.flush()
            except NoResultFound:
                raise exception.BIOSSettingNotFound(
                    node=node_id, name=setting['name'])
        return bios_settings

    @oslo_db_api.retry_on_deadlock
    def delete_bios_setting_list(self, node_id, names):
        missing_bios_settings = []
        with _session_for_write() as session:
            self._check_node_exists(session, node_id)
            for name in names:
                count = session.query(models.BIOSSetting).filter_by(
                    node_id=node_id, name=name).delete()
                if count == 0:
                    missing_bios_settings.append(name)
        if len(missing_bios_settings) > 0:
            raise exception.BIOSSettingListNotFound(
                node=node_id, names=','.join(missing_bios_settings))

    def get_bios_setting(self, node_id, name):
        with _session_for_read() as session:
            self._check_node_exists(session, node_id)
            query = session.query(models.BIOSSetting).filter_by(
                node_id=node_id, name=name)
            try:
                ref = query.one()
            except NoResultFound:
                raise exception.BIOSSettingNotFound(node=node_id, name=name)
        return ref

    def get_bios_setting_list(self, node_id):
        with _session_for_read() as session:
            self._check_node_exists(session, node_id)
            result = (session.query(models.BIOSSetting)
                      .filter_by(node_id=node_id)
                      .all())
        return result

    def get_allocation_by_id(self, allocation_id):
        """Return an allocation representation.

        :param allocation_id: The id of an allocation.
        :returns: An allocation.
        :raises: AllocationNotFound
        """
        with _session_for_read() as session:
            query = session.query(models.Allocation).filter_by(
                id=allocation_id)
            try:
                ref = query.one()
            except NoResultFound:
                raise exception.AllocationNotFound(allocation=allocation_id)
        return ref

    def get_allocation_by_uuid(self, allocation_uuid):
        """Return an allocation representation.

        :param allocation_uuid: The uuid of an allocation.
        :returns: An allocation.
        :raises: AllocationNotFound
        """
        with _session_for_read() as session:
            query = session.query(models.Allocation).filter_by(
                uuid=allocation_uuid)
            try:
                ref = query.one()
            except NoResultFound:
                raise exception.AllocationNotFound(allocation=allocation_uuid)
        return ref

    def get_allocation_by_name(self, name):
        """Return an allocation representation.

        :param name: The logical name of an allocation.
        :returns: An allocation.
        :raises: AllocationNotFound
        """
        with _session_for_read() as session:
            query = session.query(models.Allocation).filter_by(name=name)
            try:
                ref = query.one()
            except NoResultFound:
                raise exception.AllocationNotFound(allocation=name)
        return ref

    def get_allocation_list(self, filters=None, limit=None, marker=None,
                            sort_key=None, sort_dir=None):
        """Return a list of allocations.

        :param filters: Filters to apply. Defaults to None.

                        :node_uuid: uuid of node
                        :state: allocation state
                        :resource_class: requested resource class
        :param limit: Maximum number of allocations to return.
        :param marker: The last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: Direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of allocations.
        """
        query = self._add_allocations_filters(
            sa.select(models.Allocation),
            filters)
        return _paginate_query(models.Allocation, limit, marker,
                               sort_key, sort_dir, query)

    @oslo_db_api.retry_on_deadlock
    def create_allocation(self, values):
        """Create a new allocation.

        :param values: Dict of values to create an allocation with
        :returns: An allocation
        :raises: AllocationDuplicateName
        :raises: AllocationAlreadyExists
        """
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()
        if not values.get('state'):
            values['state'] = states.ALLOCATING

        allocation = models.Allocation()
        allocation.update(values)
        with _session_for_write() as session:
            try:
                session.add(allocation)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'name' in exc.columns:
                    raise exception.AllocationDuplicateName(
                        name=values['name'])
                else:
                    raise exception.AllocationAlreadyExists(
                        uuid=values['uuid'])
            return allocation

    @oslo_db_api.retry_on_deadlock
    def update_allocation(self, allocation_id, values, update_node=True):
        """Update properties of an allocation.

        :param allocation_id: Allocation ID
        :param values: Dict of values to update.
        :param update_node: If True and node_id is updated, update the node
            with instance_uuid and traits from the allocation
        :returns: An allocation.
        :raises: AllocationNotFound
        :raises: AllocationDuplicateName
        :raises: InstanceAssociated
        :raises: NodeAssociated
        """
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing allocation.")
            raise exception.InvalidParameterValue(err=msg)

        # These values are used in exception handling. They should always be
        # initialized, but set them to None just in case.
        instance_uuid = node_uuid = None

        with _session_for_write() as session:
            try:
                query = session.query(models.Allocation)
                query = add_identity_filter(query, allocation_id)
                ref = query.one()
                ref.update(values)
                instance_uuid = ref.uuid

                if values.get('node_id') and update_node:
                    node = session.query(models.Node).filter_by(
                        id=ref.node_id).with_for_update().one()
                    node_uuid = node.uuid
                    if node.instance_uuid and node.instance_uuid != ref.uuid:
                        raise exception.NodeAssociated(
                            node=node.uuid, instance=node.instance_uuid)
                    iinfo = node.instance_info.copy()
                    iinfo['traits'] = ref.traits or []
                    node.update({'allocation_id': ref.id,
                                 'instance_uuid': instance_uuid,
                                 'instance_info': iinfo})
                session.flush()
            except NoResultFound:
                raise exception.AllocationNotFound(allocation=allocation_id)
            except db_exc.DBDuplicateEntry as exc:
                if 'name' in exc.columns:
                    raise exception.AllocationDuplicateName(
                        name=values['name'])
                elif 'instance_uuid' in exc.columns:
                    # Case when the allocation UUID is already used on some
                    # node as instance_uuid.
                    raise exception.InstanceAssociated(
                        instance_uuid=instance_uuid, node=node_uuid)
                else:
                    raise
            return ref

    @oslo_db_api.retry_on_deadlock
    def take_over_allocation(self, allocation_id, old_conductor_id,
                             new_conductor_id):
        """Do a take over for an allocation.

        The allocation is only updated if the old conductor matches the
        provided value, thus guarding against races.

        :param allocation_id: Allocation ID
        :param old_conductor_id: The conductor ID we expect to be the current
            ``conductor_affinity`` of the allocation.
        :param new_conductor_id: The conductor ID of the new
            ``conductor_affinity``.
        :returns: True if the take over was successful, False otherwise.
        :raises: AllocationNotFound
        """
        with _session_for_write() as session:
            try:
                query = session.query(models.Allocation)
                query = add_identity_filter(query, allocation_id)
                # NOTE(dtantsur): the FOR UPDATE clause locks the allocation
                ref = query.with_for_update().one()
                if ref.conductor_affinity != old_conductor_id:
                    # Race detected, bailing out
                    return False

                ref.update({'conductor_affinity': new_conductor_id})
                session.flush()
            except NoResultFound:
                raise exception.AllocationNotFound(allocation=allocation_id)
            else:
                return True

    @oslo_db_api.retry_on_deadlock
    def destroy_allocation(self, allocation_id):
        """Destroy an allocation.

        :param allocation_id: Allocation ID or UUID
        :raises: AllocationNotFound
        """
        with _session_for_write() as session:
            query = session.query(models.Allocation)
            query = add_identity_filter(query, allocation_id)

            try:
                ref = query.one()
            except NoResultFound:
                raise exception.AllocationNotFound(allocation=allocation_id)

            allocation_id = ref['id']

            node_query = session.query(models.Node).filter_by(
                allocation_id=allocation_id)
            node_query.update({'allocation_id': None, 'instance_uuid': None})

            query.delete()

    @staticmethod
    def _get_deploy_template_steps(steps, deploy_template_id=None):
        results = []
        for values in steps:
            step = models.DeployTemplateStep()
            step.update(values)
            if deploy_template_id:
                step['deploy_template_id'] = deploy_template_id
            results.append(step)
        return results

    @oslo_db_api.retry_on_deadlock
    def create_deploy_template(self, values):
        steps = values.get('steps', [])
        values['steps'] = self._get_deploy_template_steps(steps)

        template = models.DeployTemplate()
        template.update(values)
        with _session_for_write() as session:
            try:
                session.add(template)
                session.flush()
            except db_exc.DBDuplicateEntry as e:
                if 'name' in e.columns:
                    raise exception.DeployTemplateDuplicateName(
                        name=values['name'])
                raise exception.DeployTemplateAlreadyExists(
                    uuid=values['uuid'])
        return template

    def _update_deploy_template_steps(self, session, template_id, steps):
        """Update the steps for a deploy template.

        :param session: DB session object.
        :param template_id: deploy template ID.
        :param steps: list of steps that should exist for the deploy template.
        """

        def _step_key(step):
            """Compare two deploy template steps."""
            # NOTE(mgoddard): In python 3, dicts are not orderable so cannot be
            # used as a sort key. Serialise the step arguments to a JSON string
            # for comparison. Taken from https://stackoverflow.com/a/22003440.
            sortable_args = json.dumps(step.args, sort_keys=True)
            return step.interface, step.step, sortable_args, step.priority

        # List all existing steps for the template.
        current_steps = (session.query(models.DeployTemplateStep)
                         .filter_by(deploy_template_id=template_id))

        # List the new steps for the template.
        new_steps = self._get_deploy_template_steps(steps, template_id)

        # The following is an efficient way to ensure that the steps in the
        # database match those that have been requested. We compare the current
        # and requested steps in a single pass using the _zip_matching
        # function.
        steps_to_create = []
        step_ids_to_delete = []
        for current_step, new_step in _zip_matching(current_steps, new_steps,
                                                    _step_key):
            if current_step is None:
                # No matching current step found for this new step - create.
                steps_to_create.append(new_step)
            elif new_step is None:
                # No matching new step found for this current step - delete.
                step_ids_to_delete.append(current_step.id)
            # else: steps match, no work required.

        # Delete and create steps in bulk as necessary.
        if step_ids_to_delete:
            ((session.query(models.DeployTemplateStep)
              .filter(models.DeployTemplateStep.id.in_(step_ids_to_delete)))
             .delete(synchronize_session=False))
        if steps_to_create:
            session.bulk_save_objects(steps_to_create)

    @oslo_db_api.retry_on_deadlock
    def update_deploy_template(self, template_id, values):
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing deploy template.")
            raise exception.InvalidParameterValue(err=msg)

        try:
            with _session_for_write() as session:
                # NOTE(mgoddard): Don't issue a joined query for the update as
                # this does not work with PostgreSQL.
                query = session.query(models.DeployTemplate)
                query = add_identity_filter(query, template_id)
                ref = query.with_for_update().one()
                # First, update non-step columns.
                steps = values.pop('steps', None)
                ref.update(values)
                # If necessary, update steps.
                if steps is not None:
                    self._update_deploy_template_steps(session, ref.id, steps)
                session.flush()

            with _session_for_read() as session:
                # Return the updated template joined with all relevant fields.
                query = _get_deploy_template_select_with_steps()
                query = add_identity_filter(query, template_id)
                return session.execute(query).one()[0]
        except db_exc.DBDuplicateEntry as e:
            if 'name' in e.columns:
                raise exception.DeployTemplateDuplicateName(
                    name=values['name'])
            raise
        except NoResultFound:
            # TODO(TheJulia): What would unified core raise?!?
            raise exception.DeployTemplateNotFound(
                template=template_id)

    @oslo_db_api.retry_on_deadlock
    def destroy_deploy_template(self, template_id):
        with _session_for_write() as session:
            session.query(models.DeployTemplateStep).filter_by(
                deploy_template_id=template_id).delete()
            count = session.query(models.DeployTemplate).filter_by(
                id=template_id).delete()
            if count == 0:
                raise exception.DeployTemplateNotFound(template=template_id)

    def _get_deploy_template(self, field, value):
        """Helper method for retrieving a deploy template."""
        query = (_get_deploy_template_select_with_steps()
                 .where(field == value))
        try:
            # FIXME(TheJulia): This needs to be fixed for SQLAlchemy 2.0
            with _session_for_read() as session:
                return session.execute(query).one()[0]
        except NoResultFound:
            raise exception.DeployTemplateNotFound(template=value)

    def get_deploy_template_by_id(self, template_id):
        return self._get_deploy_template(models.DeployTemplate.id,
                                         template_id)

    def get_deploy_template_by_uuid(self, template_uuid):
        return self._get_deploy_template(models.DeployTemplate.uuid,
                                         template_uuid)

    def get_deploy_template_by_name(self, template_name):
        return self._get_deploy_template(models.DeployTemplate.name,
                                         template_name)

    def get_deploy_template_list(self, limit=None, marker=None,
                                 sort_key=None, sort_dir=None):
        with _session_for_read() as session:
            query = session.query(models.DeployTemplate).options(
                selectinload(models.DeployTemplate.steps))
        return _paginate_query(models.DeployTemplate, limit, marker,
                               sort_key, sort_dir, query)

    def get_deploy_template_list_by_names(self, names):
        query = _get_deploy_template_select_with_steps()
        with _session_for_read() as session:
            res = session.execute(
                query.where(
                    models.DeployTemplate.name.in_(names)
                )
            ).all()
            return [r[0] for r in res]

    @oslo_db_api.retry_on_deadlock
    def create_node_history(self, values):
        values['uuid'] = uuidutils.generate_uuid()

        history = models.NodeHistory()
        history.update(values)
        with _session_for_write() as session:
            try:
                session.add(history)
                session.flush()
            except db_exc.DBDuplicateEntry:
                raise exception.NodeHistoryAlreadyExists(uuid=values['uuid'])
        return history

    @oslo_db_api.retry_on_deadlock
    def destroy_node_history_by_uuid(self, history_uuid):
        with _session_for_write() as session:
            query = session.query(models.NodeHistory).filter_by(
                uuid=history_uuid)
            count = query.delete()
            if count == 0:
                raise exception.NodeHistoryNotFound(history=history_uuid)

    def get_node_history_by_id(self, history_id):
        try:
            with _session_for_read() as session:
                query = session.query(models.NodeHistory).filter_by(
                    id=history_id)
                res = query.one()
        except NoResultFound:
            raise exception.NodeHistoryNotFound(history=history_id)
        return res

    def get_node_history_by_uuid(self, history_uuid):
        try:
            with _session_for_read() as session:
                query = session.query(models.NodeHistory).filter_by(
                    uuid=history_uuid)
                res = query.one()
        except NoResultFound:
            raise exception.NodeHistoryNotFound(history=history_uuid)
        return res

    def get_node_history_list(self, limit=None, marker=None,
                              sort_key='created_at', sort_dir='asc'):
        return _paginate_query(models.NodeHistory, limit, marker, sort_key,
                               sort_dir)

    def get_node_history_by_node_id(self, node_id, limit=None, marker=None,
                                    sort_key=None, sort_dir=None):
        with _session_for_read() as session:
            query = session.query(models.NodeHistory)
            query = query.where(models.NodeHistory.node_id == node_id)
        return _paginate_query(models.NodeHistory, limit, marker,
                               sort_key, sort_dir, query)

    def query_node_history_records_for_purge(self, conductor_id):
        min_days = CONF.conductor.node_history_minimum_days
        max_num = CONF.conductor.node_history_max_entries

        with _session_for_read() as session:
            # First, figure out our nodes.
            nodes = session.query(
                models.Node.id,
            ).filter(
                models.Node.conductor_affinity == conductor_id
            )

            # Build our query to get the node_id and record id.
            query = session.query(
                models.NodeHistory.node_id,
                models.NodeHistory.id,
            )

            # Filter by the nodes
            query = query.filter(
                models.NodeHistory.node_id.in_(nodes)
            ).order_by(
                # Order in an ascending order as older is always first.
                models.NodeHistory.created_at.asc()
            )

            # Filter by minimum days
            if min_days > 0:
                before = datetime.datetime.now() - datetime.timedelta(
                    days=min_days)
                query = query.filter(
                    models.NodeHistory.created_at < before
                )

            # Build our result set
            result_set = {}
            for entry in query.all():
                if entry[0] not in result_set:
                    result_set[entry[0]] = []
                result_set[entry[0]].append(entry[1])

            final_set = {}
            # Generate our final set of entries which should be removed
            # by accounting for the number of permitted entries.
            for entry in result_set:
                final_set[entry] = []
                set_len = len(result_set[entry])
                # Any count <= the maximum number is okay
                if set_len > max_num:
                    # figure out how many entries need to be removed
                    num_to_remove = set_len - max_num
                    for i in range(0, num_to_remove):
                        final_set[entry].append(result_set[entry][i])
                        # remove the entries at the end of the list
                        # which will be the more recent items as we
                        # ordered ascending originally.
            return final_set

    def bulk_delete_node_history_records(self, entries):
        with _session_for_write() as session:
            # Uses input entry list, selects entries matching those ids
            # then deletes them and does not synchronize the session so
            # sqlalchemy doesn't do extra un-necessary work.
            # NOTE(TheJulia): This is "legacy" syntax, but it is still
            # valid and under the hood SQLAlchemy rewrites the form into
            # a delete syntax.
            session.query(
                models.NodeHistory
            ).filter(
                models.NodeHistory.id.in_(entries)
            ).delete(synchronize_session=False)

    def count_nodes_in_provision_state(self, state):
        if not isinstance(state, list):
            state = [state]
        with _session_for_read() as session:
            # Intentionally does not use the full ORM model
            # because that is de-duped by pkey, but we already
            # have unique constraints on UUID/name, so... shouldn't
            # be a big deal. #JuliaFamousLastWords.
            # Anyway, intent here is to be as quick as possible and
            # literally have the DB do *all* of the world, so no
            # client side ops occur. The column is also indexed,
            # which means this will be an index based response.
            return session.scalar(
                sa.select(
                    sa.func.count(models.Node.id)
                ).filter(
                    or_(
                        models.Node.provision_state == v for v in state
                    )
                )
            )

    @oslo_db_api.retry_on_deadlock
    def create_node_inventory(self, values):
        inventory = models.NodeInventory()
        inventory.update(values)
        with _session_for_write() as session:
            try:
                session.add(inventory)
                session.flush()
            except db_exc.DBDuplicateEntry:
                raise exception.NodeInventoryAlreadyExists(
                    id=values['id'])
            return inventory

    @oslo_db_api.retry_on_deadlock
    def destroy_node_inventory_by_node_id(self, node_id):
        with _session_for_write() as session:
            query = session.query(models.NodeInventory).filter_by(
                node_id=node_id)
            count = query.delete()
            if count == 0:
                raise exception.NodeInventoryNotFound(
                    node=node_id)

    def get_node_inventory_by_node_id(self, node_id):
        try:
            with _session_for_read() as session:
                query = session.query(models.NodeInventory).filter_by(
                    node_id=node_id)
                res = query.one()
        except NoResultFound:
            raise exception.NodeInventoryNotFound(node=node_id)
        return res

    def get_shard_list(self):
        """Return a list of shards.

        :returns: A list of dicts containing the keys name and count.
        """
        # Note(JayF): This should never be a large enough list to require
        #             pagination. Furthermore, it wouldn't really be a sensible
        #             thing to paginate as the data it's fetching can mutate.
        #             So we just aren't even going to try.
        shard_list = []
        with _session_for_read() as session:
            res = session.execute(
                # Note(JayF): SQLAlchemy counts are notoriously slow because
                #             sometimes they will use a subquery. Be careful
                #             before changing this to use any magic.
                sa.text(
                    "SELECT count(id), shard from nodes group by shard;"
                )).fetchall()

            if res:
                res.sort(key=lambda x: x[0], reverse=True)
                for shard in res:
                    shard_list.append(
                        {"name": str(shard[1]), "count": shard[0]}
                    )

        return shard_list
