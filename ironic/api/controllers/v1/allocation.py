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

from http import client as http_client

from ironic_lib import metrics_utils
from oslo_utils import uuidutils
import pecan
from webob import exc as webob_exc

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)


ALLOCATION_SCHEMA = {
    'type': 'object',
    'properties': {
        'candidate_nodes': {
            'type': ['array', 'null'],
            'items': {'type': 'string'}
        },
        'extra': {'type': ['object', 'null']},
        'name': {'type': ['string', 'null']},
        'node': {'type': ['string', 'null']},
        'owner': {'type': ['string', 'null']},
        'resource_class': {'type': ['string', 'null'], 'maxLength': 80},
        'traits': {
            'type': ['array', 'null'],
            'items': api_utils.TRAITS_SCHEMA
        },
        'uuid': {'type': ['string', 'null']},
    },
    'additionalProperties': False,
}

ALLOCATION_VALIDATOR = args.and_valid(
    args.schema(ALLOCATION_SCHEMA),
    args.dict_valid(uuid=args.uuid)
)


PATCH_ALLOWED_FIELDS = ['name', 'extra']


def hide_fields_in_newer_versions(allocation):
    # if requested version is < 1.60, hide owner field
    if not api_utils.allow_allocation_owner():
        allocation.pop('owner', None)


def convert_with_links(rpc_allocation, fields=None, sanitize=True):

    allocation = api_utils.object_to_dict(
        rpc_allocation,
        link_resource='allocations',
        fields=('extra', 'name', 'state', 'last_error', 'resource_class',
                'owner'),
        list_fields=('candidate_nodes', 'traits')
    )
    api_utils.populate_node_uuid(rpc_allocation, allocation,
                                 raise_notfound=False)

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, allocation.keys())

    if sanitize:
        allocation_sanitize(allocation, fields)
    return allocation


def allocation_sanitize(allocation, fields):
    hide_fields_in_newer_versions(allocation)
    api_utils.sanitize_dict(allocation, fields)


def list_convert_with_links(rpc_allocations, limit, url=None, fields=None,
                            **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(p, fields=fields,
               sanitize=False) for p in rpc_allocations],
        item_name='allocations',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=allocation_sanitize,
        **kwargs
    )


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
                                    state=None, owner=None, marker=None,
                                    limit=None, sort_key='id', sort_dir='asc',
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
        :param owner: project_id of owner to filter by
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
            'state': state,
            'owner': owner
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
        return list_convert_with_links(allocations, limit,
                                       url=resource_url,
                                       fields=fields,
                                       sort_key=sort_key,
                                       sort_dir=sort_dir)

    def _check_allowed_allocation_fields(self, fields):
        """Check if fetching a particular field of an allocation is allowed.

        Check if the required version is being requested for fields
        that are only allowed to be fetched in a particular API version.

        :param fields: list or set of fields to check
        :raises: NotAcceptable if a field is not allowed
        """
        if fields is None:
            return
        if 'owner' in fields and not api_utils.allow_allocation_owner():
            raise exception.NotAcceptable()

    @METRICS.timer('AllocationsController.get_all')
    @method.expose()
    @args.validate(node=args.uuid_or_name,
                   resource_class=args.string,
                   state=args.string,
                   marker=args.uuid,
                   limit=args.integer,
                   sort_key=args.string,
                   sort_dir=args.string,
                   fields=args.string_list,
                   owner=args.string)
    def get_all(self, node=None, resource_class=None, state=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc', fields=None,
                owner=None):
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
        :param owner: Filter by owner.
        """
        owner = api_utils.check_list_policy('allocation', owner)

        self._check_allowed_allocation_fields(fields)
        if owner is not None and not api_utils.allow_allocation_owner():
            raise exception.NotAcceptable()

        return self._get_allocations_collection(node, resource_class, state,
                                                owner, marker, limit,
                                                sort_key, sort_dir,
                                                fields=fields)

    @METRICS.timer('AllocationsController.get_one')
    @method.expose()
    @args.validate(allocation_ident=args.uuid_or_name, fields=args.string_list)
    def get_one(self, allocation_ident, fields=None):
        """Retrieve information about the given allocation.

        :param allocation_ident: UUID or logical name of an allocation.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        rpc_allocation = api_utils.check_allocation_policy_and_retrieve(
            'baremetal:allocation:get', allocation_ident)
        self._check_allowed_allocation_fields(fields)

        return convert_with_links(rpc_allocation, fields=fields)

    def _authorize_create_allocation(self, allocation):
        cdict = api.request.context.to_policy_values()

        try:
            policy.authorize('baremetal:allocation:create', cdict, cdict)
            self._check_allowed_allocation_fields(allocation)
        except exception.HTTPForbidden:
            owner = cdict.get('project_id')
            if not owner or (allocation.get('owner')
                             and owner != allocation.get('owner')):
                raise
            policy.authorize('baremetal:allocation:create_restricted',
                             cdict, cdict)
            self._check_allowed_allocation_fields(allocation)
            allocation['owner'] = owner

        return allocation

    @METRICS.timer('AllocationsController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('allocation')
    @args.validate(allocation=ALLOCATION_VALIDATOR)
    def post(self, allocation):
        """Create a new allocation.

        :param allocation: an allocation within the request body.
        """
        context = api.request.context
        allocation = self._authorize_create_allocation(allocation)

        if (allocation.get('name')
                and not api_utils.is_valid_logical_name(allocation['name'])):
            msg = _("Cannot create allocation with invalid name "
                    "'%(name)s'") % {'name': allocation['name']}
            raise exception.Invalid(msg)

        node = None
        if allocation.get('node'):
            if api_utils.allow_allocation_backfill():
                try:
                    node = api_utils.get_rpc_node(allocation['node'])
                except exception.NodeNotFound as exc:
                    exc.code = http_client.BAD_REQUEST
                    raise
            else:
                msg = _("Cannot set node when creating an allocation "
                        "in this API version")
                raise exception.Invalid(msg)

        if not allocation.get('resource_class'):
            if node:
                allocation['resource_class'] = node.resource_class
            else:
                msg = _("The resource_class field is mandatory when not "
                        "backfilling")
                raise exception.Invalid(msg)

        if allocation.get('candidate_nodes'):
            # Convert nodes from names to UUIDs and check their validity
            try:
                converted = api.request.dbapi.check_node_list(
                    allocation['candidate_nodes'])
            except exception.NodeNotFound as exc:
                exc.code = http_client.BAD_REQUEST
                raise
            else:
                # Make sure we keep the ordering of candidate nodes.
                allocation['candidate_nodes'] = [
                    converted[ident] for ident in allocation['candidate_nodes']
                ]

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not allocation.get('uuid'):
            if node and node.instance_uuid:
                # When backfilling without UUID requested, assume that the
                # target instance_uuid is the desired UUID
                allocation['uuid'] = node.instance_uuid
            else:
                allocation['uuid'] = uuidutils.generate_uuid()

        new_allocation = objects.Allocation(context, **allocation)
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
        return convert_with_links(new_allocation)

    def _validate_patch(self, patch):
        fields = api_utils.patch_validate_allowed_fields(
            patch, PATCH_ALLOWED_FIELDS)
        self._check_allowed_allocation_fields(fields)

    @METRICS.timer('AllocationsController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(allocation_ident=args.string, patch=args.patch)
    def patch(self, allocation_ident, patch):
        """Update an existing allocation.

        :param allocation_ident: UUID or logical name of an allocation.
        :param patch: a json PATCH document to apply to this allocation.
        """
        if not api_utils.allow_allocation_update():
            raise webob_exc.HTTPMethodNotAllowed(_(
                "The API version does not allow updating allocations"))

        context = api.request.context
        rpc_allocation = api_utils.check_allocation_policy_and_retrieve(
            'baremetal:allocation:update', allocation_ident)
        self._validate_patch(patch)
        names = api_utils.get_patch_values(patch, '/name')
        for name in names:
            if name and not api_utils.is_valid_logical_name(name):
                msg = _("Cannot update allocation with invalid name "
                        "'%(name)s'") % {'name': name}
                raise exception.Invalid(msg)
        allocation_dict = rpc_allocation.as_dict()
        allocation_dict = api_utils.apply_jsonpatch(rpc_allocation.as_dict(),
                                                    patch)
        api_utils.patched_validate_with_schema(
            allocation_dict, ALLOCATION_SCHEMA, ALLOCATION_VALIDATOR)

        api_utils.patch_update_changed_fields(
            allocation_dict, rpc_allocation, fields=objects.Allocation.fields,
            schema=ALLOCATION_SCHEMA
        )

        notify.emit_start_notification(context, rpc_allocation, 'update')
        with notify.handle_error_notification(context,
                                              rpc_allocation, 'update'):
            rpc_allocation.save()
        notify.emit_end_notification(context, rpc_allocation, 'update')
        return convert_with_links(rpc_allocation)

    @METRICS.timer('AllocationsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(allocation_ident=args.uuid_or_name)
    def delete(self, allocation_ident):
        """Delete an allocation.

        :param allocation_ident: UUID or logical name of an allocation.
        """
        context = api.request.context
        rpc_allocation = api_utils.check_allocation_policy_and_retrieve(
            'baremetal:allocation:delete', allocation_ident)
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
    @method.expose()
    @args.validate(fields=args.string_list)
    def get_all(self, fields=None):
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:allocation:get', cdict, cdict)

        result = self.inner._get_allocations_collection(self.parent_node_ident,
                                                        fields=fields)
        try:
            return result['allocations'][0]
        except IndexError:
            raise exception.AllocationNotFound(
                _("Allocation for node %s was not found") %
                self.parent_node_ident)

    @METRICS.timer('NodeAllocationController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
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
