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

import datetime

from ironic_lib import metrics_utils
from oslo_utils import uuidutils
import pecan
from six.moves import http_client
from webob import exc as webob_exc
import wsme
from wsme import types as wtypes

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states as ir_states
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)


class Allocation(base.APIBase):
    """API representation of an allocation.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a
    allocation.
    """

    uuid = types.uuid
    """Unique UUID for this allocation"""

    extra = {wtypes.text: types.jsontype}
    """This allocation's meta data"""

    node_uuid = wsme.wsattr(types.uuid, readonly=True)
    """The UUID of the node this allocation belongs to"""

    node = wsme.wsattr(wtypes.text)
    """The node to backfill the allocation for (POST only)"""

    name = wsme.wsattr(wtypes.text)
    """The logical name for this allocation"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated allocation links"""

    state = wsme.wsattr(wtypes.text, readonly=True)
    """The current state of the allocation"""

    last_error = wsme.wsattr(wtypes.text, readonly=True)
    """Last error that happened to this allocation"""

    resource_class = wsme.wsattr(wtypes.StringType(max_length=80))
    """Requested resource class for this allocation"""

    # NOTE(dtantsur): candidate_nodes is a list of UUIDs on the database level,
    # but the API level also accept names, converting them on fly.
    candidate_nodes = wsme.wsattr([wtypes.text])
    """Candidate nodes for this allocation"""

    traits = wsme.wsattr([wtypes.text])
    """Requested traits for the allocation"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Allocation.fields)
        # NOTE: node_uuid is not part of objects.Allocation.fields
        #       because it's an API-only attribute
        fields.append('node_uuid')
        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue
            self.fields.append(field)
            setattr(self, field, kwargs.get(field, wtypes.Unset))

    @staticmethod
    def _convert_with_links(allocation, url):
        """Add links to the allocation."""
        # This field is only used in POST, never return it.
        allocation.node = wsme.Unset
        allocation.links = [
            link.Link.make_link('self', url, 'allocations', allocation.uuid),
            link.Link.make_link('bookmark', url, 'allocations',
                                allocation.uuid, bookmark=True)
        ]
        return allocation

    @classmethod
    def convert_with_links(cls, rpc_allocation, fields=None, sanitize=True):
        """Add links to the allocation."""
        allocation = Allocation(**rpc_allocation.as_dict())

        if rpc_allocation.node_id:
            try:
                allocation.node_uuid = objects.Node.get_by_id(
                    api.request.context,
                    rpc_allocation.node_id).uuid
            except exception.NodeNotFound:
                allocation.node_uuid = None
        else:
            allocation.node_uuid = None

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, allocation.fields)

        # Make the default values consistent between POST and GET API
        if allocation.candidate_nodes is None:
            allocation.candidate_nodes = []
        if allocation.traits is None:
            allocation.traits = []

        allocation = cls._convert_with_links(allocation,
                                             api.request.host_url)

        if not sanitize:
            return allocation

        allocation.sanitize(fields)

        return allocation

    def sanitize(self, fields=None):
        """Removes sensitive and unrequested data.

        Will only keep the fields specified in the ``fields`` parameter.

        :param fields:
            list of fields to preserve, or ``None`` to preserve them all
        :type fields: list of str
        """

        if fields is not None:
            self.unset_fields_except(fields)

    @classmethod
    def sample(cls):
        """Return a sample of the allocation."""
        sample = cls(uuid='a594544a-2daf-420c-8775-17a8c3e0852f',
                     node_uuid='7ae81bb3-dec3-4289-8d6c-da80bd8001ae',
                     name='node1-allocation-01',
                     state=ir_states.ALLOCATING,
                     last_error=None,
                     resource_class='baremetal',
                     traits=['CUSTOM_GPU'],
                     candidate_nodes=[],
                     extra={'foo': 'bar'},
                     created_at=datetime.datetime(2000, 1, 1, 12, 0, 0),
                     updated_at=datetime.datetime(2000, 1, 1, 12, 0, 0))
        return cls._convert_with_links(sample, 'http://localhost:6385')


class AllocationCollection(collection.Collection):
    """API representation of a collection of allocations."""

    allocations = [Allocation]
    """A list containing allocation objects"""

    def __init__(self, **kwargs):
        self._type = 'allocations'

    @staticmethod
    def convert_with_links(rpc_allocations, limit, url=None, fields=None,
                           **kwargs):
        collection = AllocationCollection()
        collection.allocations = [
            Allocation.convert_with_links(p, fields=fields, sanitize=False)
            for p in rpc_allocations
        ]
        collection.next = collection.get_next(limit, url=url, **kwargs)

        for item in collection.allocations:
            item.sanitize(fields=fields)

        return collection

    @classmethod
    def sample(cls):
        """Return a sample of the allocation."""
        sample = cls()
        sample.allocations = [Allocation.sample()]
        return sample


class AllocationPatchType(types.JsonPatchType):

    _api_base = Allocation


class AllocationsController(pecan.rest.RestController):
    """REST controller for allocations."""

    invalid_sort_key_list = ['extra', 'candidate_nodes', 'traits']

    @pecan.expose()
    def _route(self, args, request=None):
        if not api_utils.allow_allocations():
            msg = _("The API version does not allow allocations")
            if api.request.method == "GET":
                raise webob_exc.HTTPNotFound(msg)
            else:
                raise webob_exc.HTTPMethodNotAllowed(msg)
        return super(AllocationsController, self)._route(args, request)

    def _get_allocations_collection(self, node_ident=None, resource_class=None,
                                    state=None, marker=None, limit=None,
                                    sort_key='id', sort_dir='asc',
                                    resource_url=None, fields=None):
        """Return allocations collection.

        :param node_ident: UUID or name of a node.
        :param marker: Pagination marker for large data sets.
        :param limit: Maximum number of resources to return in a single result.
        :param sort_key: Column to sort results by. Default: id.
        :param sort_dir: Direction to sort. "asc" or "desc". Default: asc.
        :param resource_url: Optional, URL to the allocation resource.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        marker_obj = None
        if marker:
            marker_obj = objects.Allocation.get_by_uuid(api.request.context,
                                                        marker)

        if node_ident:
            try:
                node_uuid = api_utils.get_rpc_node(node_ident).uuid
            except exception.NodeNotFound as exc:
                exc.code = http_client.BAD_REQUEST
                raise
        else:
            node_uuid = None

        possible_filters = {
            'node_uuid': node_uuid,
            'resource_class': resource_class,
            'state': state
        }

        filters = {}
        for key, value in possible_filters.items():
            if value is not None:
                filters[key] = value

        allocations = objects.Allocation.list(api.request.context,
                                              limit=limit,
                                              marker=marker_obj,
                                              sort_key=sort_key,
                                              sort_dir=sort_dir,
                                              filters=filters)
        return AllocationCollection.convert_with_links(allocations, limit,
                                                       url=resource_url,
                                                       fields=fields,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir)

    @METRICS.timer('AllocationsController.get_all')
    @expose.expose(AllocationCollection, types.uuid_or_name, wtypes.text,
                   wtypes.text, types.uuid, int, wtypes.text, wtypes.text,
                   types.listtype)
    def get_all(self, node=None, resource_class=None, state=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc', fields=None):
        """Retrieve a list of allocations.

        :param node: UUID or name of a node, to get only allocations for that
                     node.
        :param resource_class: Filter by requested resource class.
        :param state: Filter by allocation state.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:allocation:get', cdict, cdict)

        return self._get_allocations_collection(node, resource_class, state,
                                                marker, limit,
                                                sort_key, sort_dir,
                                                fields=fields)

    @METRICS.timer('AllocationsController.get_one')
    @expose.expose(Allocation, types.uuid_or_name, types.listtype)
    def get_one(self, allocation_ident, fields=None):
        """Retrieve information about the given allocation.

        :param allocation_ident: UUID or logical name of an allocation.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:allocation:get', cdict, cdict)

        rpc_allocation = api_utils.get_rpc_allocation_with_suffix(
            allocation_ident)
        return Allocation.convert_with_links(rpc_allocation, fields=fields)

    @METRICS.timer('AllocationsController.post')
    @expose.expose(Allocation, body=Allocation,
                   status_code=http_client.CREATED)
    def post(self, allocation):
        """Create a new allocation.

        :param allocation: an allocation within the request body.
        """
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:allocation:create', cdict, cdict)

        if (allocation.name
                and not api_utils.is_valid_logical_name(allocation.name)):
            msg = _("Cannot create allocation with invalid name "
                    "'%(name)s'") % {'name': allocation.name}
            raise exception.Invalid(msg)

        if allocation.traits:
            for trait in allocation.traits:
                api_utils.validate_trait(trait)

        node = None
        if allocation.node is not wtypes.Unset:
            if api_utils.allow_allocation_backfill():
                try:
                    node = api_utils.get_rpc_node(allocation.node)
                except exception.NodeNotFound as exc:
                    exc.code = http_client.BAD_REQUEST
                    raise
            else:
                msg = _("Cannot set node when creating an allocation "
                        "in this API version")
                raise exception.Invalid(msg)

        if not allocation.resource_class:
            if node:
                allocation.resource_class = node.resource_class
            else:
                msg = _("The resource_class field is mandatory when not "
                        "backfilling")
                raise exception.Invalid(msg)

        if allocation.candidate_nodes:
            # Convert nodes from names to UUIDs and check their validity
            try:
                converted = api.request.dbapi.check_node_list(
                    allocation.candidate_nodes)
            except exception.NodeNotFound as exc:
                exc.code = http_client.BAD_REQUEST
                raise
            else:
                # Make sure we keep the ordering of candidate nodes.
                allocation.candidate_nodes = [
                    converted[ident] for ident in allocation.candidate_nodes]

        all_dict = allocation.as_dict()

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not all_dict.get('uuid'):
            if node and node.instance_uuid:
                # When backfilling without UUID requested, assume that the
                # target instance_uuid is the desired UUID
                all_dict['uuid'] = node.instance_uuid
            else:
                all_dict['uuid'] = uuidutils.generate_uuid()

        new_allocation = objects.Allocation(context, **all_dict)
        if node:
            new_allocation.node_id = node.id
            topic = api.request.rpcapi.get_topic_for(node)
        else:
            topic = api.request.rpcapi.get_random_topic()

        notify.emit_start_notification(context, new_allocation, 'create')
        with notify.handle_error_notification(context, new_allocation,
                                              'create'):
            new_allocation = api.request.rpcapi.create_allocation(
                context, new_allocation, topic)
        notify.emit_end_notification(context, new_allocation, 'create')

        # Set the HTTP Location Header
        api.response.location = link.build_url('allocations',
                                               new_allocation.uuid)
        return Allocation.convert_with_links(new_allocation)

    def _validate_patch(self, patch):
        allowed_fields = ['name', 'extra']
        for p in patch:
            path = p['path'].split('/')[1]
            if path not in allowed_fields:
                msg = _("Cannot update %s in an allocation. Only 'name' and "
                        "'extra' are allowed to be updated.")
                raise exception.Invalid(msg % p['path'])

    @METRICS.timer('AllocationsController.patch')
    @wsme.validate(types.uuid, [AllocationPatchType])
    @expose.expose(Allocation, types.uuid_or_name, body=[AllocationPatchType])
    def patch(self, allocation_ident, patch):
        """Update an existing allocation.

        :param allocation_ident: UUID or logical name of an allocation.
        :param patch: a json PATCH document to apply to this allocation.
        """
        if not api_utils.allow_allocation_update():
            raise webob_exc.HTTPMethodNotAllowed(_(
                "The API version does not allow updating allocations"))
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:allocation:update', cdict, cdict)
        self._validate_patch(patch)
        names = api_utils.get_patch_values(patch, '/name')
        for name in names:
            if name and not api_utils.is_valid_logical_name(name):
                msg = _("Cannot update allocation with invalid name "
                        "'%(name)s'") % {'name': name}
                raise exception.Invalid(msg)
        rpc_allocation = api_utils.get_rpc_allocation_with_suffix(
            allocation_ident)
        allocation_dict = rpc_allocation.as_dict()
        allocation = Allocation(**api_utils.apply_jsonpatch(allocation_dict,
                                                            patch))
        # Update only the fields that have changed
        for field in objects.Allocation.fields:
            try:
                patch_val = getattr(allocation, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_allocation[field] != patch_val:
                rpc_allocation[field] = patch_val

        notify.emit_start_notification(context, rpc_allocation, 'update')
        with notify.handle_error_notification(context,
                                              rpc_allocation, 'update'):
            rpc_allocation.save()
        notify.emit_end_notification(context, rpc_allocation, 'update')
        return Allocation.convert_with_links(rpc_allocation)

    @METRICS.timer('AllocationsController.delete')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
    def delete(self, allocation_ident):
        """Delete an allocation.

        :param allocation_ident: UUID or logical name of an allocation.
        """
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:allocation:delete', cdict, cdict)

        rpc_allocation = api_utils.get_rpc_allocation_with_suffix(
            allocation_ident)
        if rpc_allocation.node_id:
            node_uuid = objects.Node.get_by_id(api.request.context,
                                               rpc_allocation.node_id).uuid
        else:
            node_uuid = None

        notify.emit_start_notification(context, rpc_allocation, 'delete',
                                       node_uuid=node_uuid)
        with notify.handle_error_notification(context, rpc_allocation,
                                              'delete', node_uuid=node_uuid):
            topic = api.request.rpcapi.get_random_topic()
            api.request.rpcapi.destroy_allocation(context, rpc_allocation,
                                                  topic)
        notify.emit_end_notification(context, rpc_allocation, 'delete',
                                     node_uuid=node_uuid)


class NodeAllocationController(pecan.rest.RestController):
    """REST controller for allocations."""

    invalid_sort_key_list = ['extra', 'candidate_nodes', 'traits']

    @pecan.expose()
    def _route(self, args, request=None):
        if not api_utils.allow_allocations():
            raise webob_exc.HTTPNotFound(_(
                "The API version does not allow allocations"))
        return super(NodeAllocationController, self)._route(args, request)

    def __init__(self, node_ident):
        super(NodeAllocationController, self).__init__()
        self.parent_node_ident = node_ident
        self.inner = AllocationsController()

    @METRICS.timer('NodeAllocationController.get_all')
    @expose.expose(Allocation, types.listtype)
    def get_all(self, fields=None):
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:allocation:get', cdict, cdict)

        result = self.inner._get_allocations_collection(self.parent_node_ident,
                                                        fields=fields)
        try:
            return result.allocations[0]
        except IndexError:
            raise exception.AllocationNotFound(
                _("Allocation for node %s was not found") %
                self.parent_node_ident)

    @METRICS.timer('NodeAllocationController.delete')
    @expose.expose(None, status_code=http_client.NO_CONTENT)
    def delete(self):
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:allocation:delete', cdict, cdict)

        rpc_node = api_utils.get_rpc_node_with_suffix(self.parent_node_ident)
        allocations = objects.Allocation.list(
            api.request.context,
            filters={'node_uuid': rpc_node.uuid})

        try:
            rpc_allocation = allocations[0]
        except IndexError:
            raise exception.AllocationNotFound(
                _("Allocation for node %s was not found") %
                self.parent_node_ident)

        notify.emit_start_notification(context, rpc_allocation, 'delete',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_allocation,
                                              'delete',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_random_topic()
            api.request.rpcapi.destroy_allocation(context, rpc_allocation,
                                                  topic)
        notify.emit_end_notification(context, rpc_allocation, 'delete',
                                     node_uuid=rpc_node.uuid)
