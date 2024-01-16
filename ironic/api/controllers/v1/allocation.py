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
from oslo_config import cfg
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
from ironic import objects


CONF = cfg.CONF

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
        fields=(
            'candidate_nodes',
            'extra',
            'last_error',
            'name',
            'owner',
            'resource_class',
            'state',
            'traits'
        )
    )
    try:
        api_utils.populate_node_uuid(rpc_allocation, allocation)
    except exception.NodeNotFound:
        allocation['node_uuid'] = None

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, set(allocation))

    if sanitize:
        allocation_sanitize(allocation, fields)
    return allocation


def allocation_sanitize(allocation, fields):
    hide_fields_in_newer_versions(allocation)
    api_utils.sanitize_dict(allocation, fields)


def list_convert_with_links(rpc_allocations, limit, url, fields=None,
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
                                    resource_url='allocations', fields=None,
                                    parent_node=None):
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
        :param parent_node: The explicit parent node uuid to return if
                            the controller is being accessed as a
                            sub-resource. i.e. /v1/nodes/<uuid>/allocation
        """
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        # If the user is not allowed to see everything, we need to filter
        # based upon access rights.
        cdict = api.request.context.to_policy_values()
        if cdict.get('system_scope') != 'all' and not parent_node:
            # The user is a project scoped, and there is not an explicit
            # parent node which will be returned.
            if not api_utils.check_policy_true(
                    'baremetal:allocation:list_all'):
                # If the user cannot see everything via the policy,
                # we need to filter the view down to only what they should
                # be able to see in the database.
                owner = cdict.get('project_id')
        else:
            # Override if any node_ident was submitted in since this
            # is a subresource query.
            node_ident = parent_node

        marker_obj = None
        if marker:
            marker_obj = objects.Allocation.get_by_uuid(api.request.context,
                                                        marker)
        if node_ident:
            try:
                # Check ability to access the associated node or requested
                # node to filter by.
                rpc_node = api_utils.get_rpc_node(node_ident)
                api_utils.check_owner_policy('node', 'baremetal:node:get',
                                             rpc_node.owner,
                                             lessee=rpc_node.lessee,
                                             conceal_node=False)
                node_uuid = rpc_node.uuid
            except exception.NodeNotFound as exc:
                exc.code = http_client.BAD_REQUEST
                raise
            except exception.NotAuthorized as exc:
                if not parent_node:
                    exc.code = http_client.BAD_REQUEST
                raise exception.NotFound()
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
        for allocation in allocations:
            api_utils.check_owner_policy('allocation',
                                         'baremetal:allocation:get',
                                         allocation.owner)
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

        .. parameters:: ../../api-ref/source/parameters.yaml

           :node: r_allocation_node
           :resource_class: req_allocation_resource_class
           :state: r_allocation_state
           :marker: marker
           :limit: limit
           :sort_key: sort_key
           :sort_dir: sort_dir
           :fields: fields
           :owner: r_owner
        """
        requestor = api_utils.check_list_policy('allocation', owner)

        self._check_allowed_allocation_fields(fields)
        if owner is not None and not api_utils.allow_allocation_owner():
            # Requestor has asked for an owner field/column match, but
            # their client version does not support it.
            raise exception.NotAcceptable()
        if (owner is not None
                and requestor is not None
                and owner != requestor):
            # The requestor is asking about other owner's records.
            # Naughty!
            raise exception.NotAuthorized()

        if requestor is not None:
            owner = requestor

        return self._get_allocations_collection(node, resource_class, state,
                                                owner, marker, limit,
                                                sort_key, sort_dir,
                                                fields=fields)

    @METRICS.timer('AllocationsController.get_one')
    @method.expose()
    @args.validate(allocation_ident=args.uuid_or_name, fields=args.string_list)
    def get_one(self, allocation_ident, fields=None):
        """Retrieve information about the given allocation.

        .. parameters:: ../../api-ref/source/parameters.yaml

           :allocation_ident: allocation_ident
           :fields: fields
        """
        rpc_allocation = api_utils.check_allocation_policy_and_retrieve(
            'baremetal:allocation:get', allocation_ident)
        self._check_allowed_allocation_fields(fields)

        return convert_with_links(rpc_allocation, fields=fields)

    def _authorize_create_allocation(self, allocation):

        try:
            # PRE-RBAC this rule was logically restricted, it is more-unlocked
            # post RBAC, but we need to ensure it is not abused.
            api_utils.check_policy('baremetal:allocation:create')
            self._check_allowed_allocation_fields(allocation)
            if (not CONF.oslo_policy.enforce_new_defaults
                    and not allocation.get('owner')):
                # Even if permitted, we need to go ahead and check if this is
                # restricted for now until scoped interaction is the default
                # interaction.
                api_utils.check_policy('baremetal:allocation:create_pre_rbac')
                # TODO(TheJulia): This can be removed later once we
                # move entirely to scope based checking. This requires
                # that if the scope enforcement is not enabled, that
                # any user can't create an allocation until the deployment
                # is in a new operating mode *where* owner will be added
                # automatically if not a privilged user.
        except exception.HTTPForbidden:
            cdict = api.request.context.to_policy_values()
            project = cdict.get('project_id')
            if (project and allocation.get('owner')
                and project != allocation.get('owner')):
                raise
            if (allocation.get('owner')
                and not CONF.oslo_policy.enforce_new_defaults):
                api_utils.check_policy('baremetal:allocation:create_pre_rbac')
            api_utils.check_policy('baremetal:allocation:create_restricted')
            self._check_allowed_allocation_fields(allocation)
            allocation['owner'] = project
        return allocation

    @METRICS.timer('AllocationsController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('allocation')
    @args.validate(allocation=ALLOCATION_VALIDATOR)
    def post(self, allocation):
        """Create a new allocation.

        .. parameters:: ../../api-ref/source/parameters.yaml

           :allocation: req_allocation_name
        """
        context = api.request.context
        cdict = context.to_policy_values()
        allocation = self._authorize_create_allocation(allocation)

        if (allocation.get('name')
                and not api_utils.is_valid_logical_name(allocation['name'])):
            msg = _("Cannot create allocation with invalid name "
                    "'%(name)s'") % {'name': allocation['name']}
            raise exception.Invalid(msg)

        # TODO(TheJulia): We need to likely look at refactoring post
        # processing for allocations as pep8 says it is a complexity of 19,
        # although it is not actually that horrible since it is phased out
        # just modifying/assembling the allocation. Given that, it seems
        # not great to try for a full method rewrite at the same time as
        # RBAC work, so the complexity limit is being raised. :(
        if (CONF.oslo_policy.enforce_new_defaults
                and cdict.get('system_scope') != 'all'):
            # if not a system scope originated request, we need to check/apply
            # an owner - But we can only do this with when new defaults are
            # enabled.
            project_id = cdict.get('project_id')
            req_alloc_owner = allocation.get('owner')
            if req_alloc_owner:
                if not api_utils.check_policy_true(
                        'baremetal:allocation:create_restricted'):
                    if req_alloc_owner != project_id:
                        msg = _("Cannot create allocation with an owner "
                                "Project ID value %(req_owner)s not matching "
                                "the requestor Project ID %(project)s. "
                                "Policy baremetal:allocation:create_restricted"
                                " is required for this capability."
                                ) % {'req_owner': req_alloc_owner,
                                     'project': project_id}
                        raise exception.NotAuthorized(msg)
                # NOTE(TheJulia): IF not restricted, i.e. else above,
                # their supplied allocation owner is okay, they are allowed
                # to provide an override by policy.
            else:
                # An allocation owner was not supplied, we need to save one.
                allocation['owner'] = project_id
        node = None
        if allocation.get('node'):
            if api_utils.allow_allocation_backfill():
                try:
                    node = api_utils.get_rpc_node(allocation['node'])
                    api_utils.check_owner_policy(
                        'node', 'baremetal:node:get',
                        node.owner, node.lessee,
                        conceal_node=allocation['node'])
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
                owner = None
                if not api_utils.check_policy_true(
                        'baremetal:allocation:create_restricted'):
                    owner = cdict.get('project_id')
                # Filter the candidate search by the requestor project ID
                # if any. The result is processes authenticating with system
                # scope will not be impacted, where as project scoped requests
                # will need additional authorization.
                converted = api.request.dbapi.check_node_list(
                    allocation['candidate_nodes'],
                    project=owner)
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

        .. parameters:: ../../api-ref/source/parameters.yaml

           :allocation_ident: allocation_ident
           :patch: allocation_patch
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

        .. parameters:: ../../api-ref/source/parameters.yaml

           :allocation_ident: allocation_ident
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
        """Get all allocations.

        .. parameters:: ../../api-ref/source/parameters.yaml

           :fields: fields
        """
        parent_node = self.parent_node_ident
        result = self.inner._get_allocations_collection(
            parent_node,
            fields=fields,
            parent_node=parent_node)

        try:
            return result['allocations'][0]
        except IndexError:
            raise exception.AllocationNotFound(
                _("Allocation for node %s was not found") %
                self.parent_node_ident)

    @METRICS.timer('NodeAllocationController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    def delete(self):
        """Delete an allocation."""
        context = api.request.context

        rpc_node = api_utils.get_rpc_node_with_suffix(self.parent_node_ident)
        # Check the policy, and 404 if not authorized.
        api_utils.check_owner_policy('node', 'baremetal:node:get',
                                     rpc_node.owner, lessee=rpc_node.lessee,
                                     conceal_node=self.parent_node_ident)

        # A project ID is associated, thus we should filter
        # our search using it.
        filters = {'node_uuid': rpc_node.uuid}
        allocations = objects.Allocation.list(
            api.request.context,
            filters=filters)

        try:
            rpc_allocation = allocations[0]
            allocation_owner = allocations[0]['owner']
            api_utils.check_owner_policy('allocation',
                                         'baremetal:allocation:delete',
                                         allocation_owner)
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
