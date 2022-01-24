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

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states as ir_states
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ['uuid', 'address', 'name']

PORTGROUP_SCHEMA = {
    'type': 'object',
    'properties': {
        'address': {'type': ['string', 'null']},
        'extra': {'type': ['object', 'null']},
        'mode': {'type': ['string', 'null']},
        'name': {'type': ['string', 'null']},
        'node_uuid': {'type': 'string'},
        'properties': {'type': ['object', 'null']},
        'standalone_ports_supported': {'type': ['string', 'boolean', 'null']},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['node_uuid'],
    'additionalProperties': False,
}

PORTGROUP_PATCH_SCHEMA = PORTGROUP_SCHEMA

PORTGROUP_VALIDATOR_EXTRA = args.dict_valid(
    address=args.mac_address,
    node_uuid=args.uuid,
    standalone_ports_supported=args.boolean,
    uuid=args.uuid
)
PORTGROUP_VALIDATOR = args.and_valid(
    args.schema(PORTGROUP_SCHEMA),
    PORTGROUP_VALIDATOR_EXTRA
)

PORTGROUP_PATCH_VALIDATOR = args.and_valid(
    args.schema(PORTGROUP_PATCH_SCHEMA),
    PORTGROUP_VALIDATOR_EXTRA
)

PATCH_ALLOWED_FIELDS = [
    'address',
    'extra',
    'mode',
    'name',
    'node_uuid',
    'properties',
    'standalone_ports_supported'
]


def convert_with_links(rpc_portgroup, fields=None, sanitize=True):
    """Add links to the portgroup."""
    portgroup = api_utils.object_to_dict(
        rpc_portgroup,
        link_resource='portgroups',
        fields=(
            'address',
            'extra',
            'internal_info',
            'mode',
            'name',
            'properties',
            'standalone_ports_supported'
        )
    )
    api_utils.populate_node_uuid(rpc_portgroup, portgroup)
    url = api.request.public_url
    portgroup['ports'] = [
        link.make_link('self', url, 'portgroups',
                       rpc_portgroup.uuid + "/ports"),
        link.make_link('bookmark', url, 'portgroups',
                       rpc_portgroup.uuid + "/ports", bookmark=True)
    ]

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, portgroup)

    if not sanitize:
        return portgroup

    api_utils.sanitize_dict(portgroup, fields)

    return portgroup


def list_convert_with_links(rpc_portgroups, limit, url, fields=None, **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(p, fields=fields, sanitize=False)
               for p in rpc_portgroups],
        item_name='portgroups',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=api_utils.sanitize_dict,
        **kwargs
    )


class PortgroupsController(pecan.rest.RestController):
    """REST controller for portgroups."""

    _custom_actions = {
        'detail': ['GET'],
    }

    invalid_sort_key_list = ['extra', 'internal_info', 'properties']

    _subcontroller_map = {
        'ports': port.PortsController,
    }

    @pecan.expose()
    def _lookup(self, ident, *remainder):
        if not api_utils.allow_portgroups():
            pecan.abort(http_client.NOT_FOUND)
        try:
            ident = args.uuid_or_name('portgroup', ident)
        except exception.InvalidParameterValue as e:
            pecan.abort(http_client.BAD_REQUEST, e.args[0])
        if not remainder:
            return
        subcontroller = self._subcontroller_map.get(remainder[0])
        if subcontroller:
            if api_utils.allow_portgroups_subcontrollers():
                return subcontroller(
                    portgroup_ident=ident,
                    node_ident=self.parent_node_ident), remainder[1:]
            pecan.abort(http_client.NOT_FOUND)

    def __init__(self, node_ident=None):
        super(PortgroupsController, self).__init__()
        self.parent_node_ident = node_ident

    def _get_portgroups_collection(self, node_ident, address,
                                   marker, limit, sort_key, sort_dir,
                                   resource_url=None, fields=None,
                                   detail=None, project=None):
        """Return portgroups collection.

        :param node_ident: UUID or name of a node.
        :param address: MAC address of a portgroup.
        :param marker: Pagination marker for large data sets.
        :param limit: Maximum number of resources to return in a single result.
        :param sort_key: Column to sort results by. Default: id.
        :param sort_dir: Direction to sort. "asc" or "desc". Default: asc.
        :param resource_url: Optional, URL to the portgroup resource.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        :param project: Optional, project ID to filter the request by.
        """
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Portgroup.get_by_uuid(api.request.context,
                                                       marker)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        node_ident = self.parent_node_ident or node_ident

        if node_ident:
            # FIXME: Since all we need is the node ID, we can
            #        make this more efficient by only querying
            #        for that column. This will get cleaned up
            #        as we move to the object interface.
            node = api_utils.get_rpc_node(node_ident)
            portgroups = objects.Portgroup.list_by_node_id(
                api.request.context, node.id, limit,
                marker_obj, sort_key=sort_key, sort_dir=sort_dir,
                project=project)
        elif address:
            portgroups = self._get_portgroups_by_address(address,
                                                         project=project)
        else:
            portgroups = objects.Portgroup.list(api.request.context, limit,
                                                marker_obj, sort_key=sort_key,
                                                sort_dir=sort_dir,
                                                project=project)
        parameters = {}
        if detail is not None:
            parameters['detail'] = detail

        return list_convert_with_links(portgroups, limit,
                                       url=resource_url,
                                       fields=fields,
                                       sort_key=sort_key,
                                       sort_dir=sort_dir,
                                       **parameters)

    def _get_portgroups_by_address(self, address, project=None):
        """Retrieve a portgroup by its address.

        :param address: MAC address of a portgroup, to get the portgroup
                        which has this MAC address.
        :returns: a list with the portgroup, or an empty list if no portgroup
                  is found.

        """
        try:
            portgroup = objects.Portgroup.get_by_address(api.request.context,
                                                         address,
                                                         project=project)
            return [portgroup]
        except exception.PortgroupNotFound:
            return []

    @METRICS.timer('PortgroupsController.get_all')
    @method.expose()
    @args.validate(node=args.uuid_or_name, address=args.mac_address,
                   marker=args.uuid, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
    def get_all(self, node=None, address=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc', fields=None,
                detail=None):
        """Retrieve a list of portgroups.

        :param node: UUID or name of a node, to get only portgroups for that
                     node.
        :param address: MAC address of a portgroup, to get the portgroup which
                        has this MAC address.
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
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        if self.parent_node_ident:
            # Override the node, since this is being called by another
            # controller with a linked view.
            node = self.parent_node_ident

        project = api_utils.check_port_list_policy(
            portgroup=True,
            parent_node=self.parent_node_ident)

        api_utils.check_allowed_portgroup_fields(fields)
        api_utils.check_allowed_portgroup_fields([sort_key])

        fields = api_utils.get_request_return_fields(fields, detail,
                                                     _DEFAULT_RETURN_FIELDS)

        return self._get_portgroups_collection(node, address,
                                               marker, limit,
                                               sort_key, sort_dir,
                                               fields=fields,
                                               resource_url='portgroups',
                                               detail=detail,
                                               project=project)

    @METRICS.timer('PortgroupsController.detail')
    @method.expose()
    @args.validate(node=args.uuid_or_name, address=args.mac_address,
                   marker=args.uuid, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string)
    def detail(self, node=None, address=None, marker=None,
               limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of portgroups with detail.

        :param node: UUID or name of a node, to get only portgroups for that
                     node.
        :param address: MAC address of a portgroup, to get the portgroup which
                        has this MAC address.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        if self.parent_node_ident:
            # If we have a parent node, then we need to override this method's
            # node filter.
            node = self.parent_node_ident

        project = api_utils.check_port_list_policy(
            portgroup=True,
            parent_node=self.parent_node_ident)

        api_utils.check_allowed_portgroup_fields([sort_key])

        # NOTE: /detail should only work against collections
        parent = api.request.path.split('/')[:-1][-1]
        if parent != "portgroups":
            raise exception.HTTPNotFound()

        return self._get_portgroups_collection(
            node, address, marker, limit, sort_key, sort_dir,
            resource_url='portgroups/detail', project=project)

    @METRICS.timer('PortgroupsController.get_one')
    @method.expose()
    @args.validate(portgroup_ident=args.uuid_or_name, fields=args.string_list)
    def get_one(self, portgroup_ident, fields=None):
        """Retrieve information about the given portgroup.

        :param portgroup_ident: UUID or logical name of a portgroup.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        rpc_portgroup, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:portgroup:get', portgroup_ident, portgroup=True)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        api_utils.check_allowed_portgroup_fields(fields)

        rpc_portgroup = api_utils.get_rpc_portgroup_with_suffix(
            portgroup_ident)
        return convert_with_links(rpc_portgroup, fields=fields)

    @METRICS.timer('PortgroupsController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('portgroup')
    @args.validate(portgroup=PORTGROUP_VALIDATOR)
    def post(self, portgroup):
        """Create a new portgroup.

        :param portgroup: a portgroup within the request body.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        raise_node_not_found = False
        node = None
        owner = None
        lessee = None
        node_uuid = portgroup.get('node_uuid')
        try:
            # The replace_node_uuid_with_id also checks access to the node
            # and will raise an exception if access is not permitted.
            node = api_utils.replace_node_uuid_with_id(portgroup)
            owner = node.owner
            lessee = node.lessee
        except exception.NotFound:
            raise_node_not_found = True

        # While the rule is for the port, the base object that controls access
        # is the node.
        api_utils.check_owner_policy('node', 'baremetal:portgroup:create',
                                     owner, lessee=lessee,
                                     conceal_node=False)
        if raise_node_not_found:
            # Delayed raise of NodeNotFound because we want to check
            # the access policy first.
            raise exception.NodeNotFound(node=node_uuid,
                                         code=http_client.BAD_REQUEST)
        context = api.request.context

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        if (not api_utils.allow_portgroup_mode_properties()
                and (portgroup.get('mode') or portgroup.get('properties'))):
            raise exception.NotAcceptable()

        if (portgroup.get('name')
                and not api_utils.is_valid_logical_name(portgroup['name'])):
            error_msg = _("Cannot create portgroup with invalid name "
                          "'%(name)s'") % {'name': portgroup['name']}
            raise exception.ClientSideError(
                error_msg, status_code=http_client.BAD_REQUEST)

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not portgroup.get('uuid'):
            portgroup['uuid'] = uuidutils.generate_uuid()

        new_portgroup = objects.Portgroup(context, **portgroup)

        notify.emit_start_notification(context, new_portgroup, 'create',
                                       node_uuid=node.uuid)
        with notify.handle_error_notification(context, new_portgroup, 'create',
                                              node_uuid=node.uuid):
            new_portgroup.create()
        notify.emit_end_notification(context, new_portgroup, 'create',
                                     node_uuid=node.uuid)

        # Set the HTTP Location Header
        api.response.location = link.build_url('portgroups',
                                               new_portgroup.uuid)
        return convert_with_links(new_portgroup)

    @METRICS.timer('PortgroupsController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(portgroup_ident=args.uuid_or_name, patch=args.patch)
    def patch(self, portgroup_ident, patch):
        """Update an existing portgroup.

        :param portgroup_ident: UUID or logical name of a portgroup.
        :param patch: a json PATCH document to apply to this portgroup.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        context = api.request.context

        rpc_portgroup, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:portgroup:update', portgroup_ident, portgroup=True)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        if (not api_utils.allow_portgroup_mode_properties()
                and (api_utils.is_path_updated(patch, '/mode')
                     or api_utils.is_path_updated(patch, '/properties'))):
            raise exception.NotAcceptable()

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        names = api_utils.get_patch_values(patch, '/name')
        for name in names:
            if (name and not api_utils.is_valid_logical_name(name)):
                error_msg = _("Portgroup %(portgroup)s: Cannot change name to"
                              " invalid name '%(name)s'") % {'portgroup':
                                                             portgroup_ident,
                                                             'name': name}
                raise exception.ClientSideError(
                    error_msg, status_code=http_client.BAD_REQUEST)

        portgroup_dict = rpc_portgroup.as_dict()

        # NOTE:
        # 1) Remove node_id because it's an internal value and
        #    not present in the API object
        # 2) Add node_uuid
        portgroup_dict.pop('node_id')
        portgroup_dict['node_uuid'] = rpc_node.uuid
        portgroup_dict = api_utils.apply_jsonpatch(portgroup_dict, patch)

        if 'mode' not in portgroup_dict:
            msg = _("'mode' is a mandatory attribute and can not be removed")
            raise exception.ClientSideError(msg)

        try:
            if portgroup_dict['node_uuid'] != rpc_node.uuid:
                rpc_node = objects.Node.get(api.request.context,
                                            portgroup_dict['node_uuid'])

        except exception.NodeNotFound as e:
            # Change error code because 404 (NotFound) is inappropriate
            # response for a POST request to patch a Portgroup
            e.code = http_client.BAD_REQUEST  # BadRequest
            raise

        api_utils.patched_validate_with_schema(
            portgroup_dict, PORTGROUP_PATCH_SCHEMA, PORTGROUP_PATCH_VALIDATOR)

        api_utils.patch_update_changed_fields(
            portgroup_dict, rpc_portgroup, fields=objects.Portgroup.fields,
            schema=PORTGROUP_PATCH_SCHEMA, id_map={'node_id': rpc_node.id}
        )

        if (rpc_node.provision_state == ir_states.INSPECTING
                and api_utils.allow_inspect_wait_state()):
            msg = _('Cannot update portgroup "%(portgroup)s" on node '
                    '"%(node)s" while it is in state "%(state)s".') % {
                'portgroup': rpc_portgroup.uuid, 'node': rpc_node.uuid,
                'state': ir_states.INSPECTING}
            raise exception.ClientSideError(msg,
                                            status_code=http_client.CONFLICT)

        notify.emit_start_notification(context, rpc_portgroup, 'update',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_portgroup, 'update',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_portgroup = api.request.rpcapi.update_portgroup(
                context, rpc_portgroup, topic)

        api_portgroup = convert_with_links(new_portgroup)
        notify.emit_end_notification(context, new_portgroup, 'update',
                                     node_uuid=rpc_node.uuid)

        return api_portgroup

    @METRICS.timer('PortgroupsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(portgroup_ident=args.uuid_or_name)
    def delete(self, portgroup_ident):
        """Delete a portgroup.

        :param portgroup_ident: UUID or logical name of a portgroup.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        rpc_portgroup, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:portgroup:delete', portgroup_ident, portgroup=True)

        context = api.request.context

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        notify.emit_start_notification(context, rpc_portgroup, 'delete',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_portgroup, 'delete',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            api.request.rpcapi.destroy_portgroup(context, rpc_portgroup,
                                                 topic)
        notify.emit_end_notification(context, rpc_portgroup, 'delete',
                                     node_uuid=rpc_node.uuid)
