# Copyright 2013 UnitedStack Inc.
# All Rights Reserved.
#
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
from oslo_log import log
from oslo_utils import uuidutils
from pecan import rest

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states as ir_states
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)
LOG = log.getLogger(__name__)


_DEFAULT_RETURN_FIELDS = ['uuid', 'address']


PORT_SCHEMA = {
    'type': 'object',
    'properties': {
        'address': {'type': 'string'},
        'extra': {'type': ['object', 'null']},
        'is_smartnic': {'type': ['string', 'boolean', 'null']},
        'local_link_connection': {'type': ['null', 'object']},
        'node_uuid': {'type': 'string'},
        'physical_network': {'type': ['string', 'null'], 'maxLength': 64},
        'portgroup_uuid': {'type': ['string', 'null']},
        'pxe_enabled': {'type': ['string', 'boolean', 'null']},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['address', 'node_uuid'],
    'additionalProperties': False,
}


PORT_PATCH_SCHEMA = PORT_SCHEMA

PATCH_ALLOWED_FIELDS = [
    'address',
    'extra',
    'is_smartnic',
    'local_link_connection',
    'node_uuid',
    'physical_network',
    'portgroup_uuid',
    'pxe_enabled'
]

PORT_VALIDATOR_EXTRA = args.dict_valid(
    address=args.mac_address,
    node_uuid=args.uuid,
    is_smartnic=args.boolean,
    local_link_connection=api_utils.LOCAL_LINK_VALIDATOR,
    portgroup_uuid=args.uuid,
    pxe_enabled=args.boolean,
    uuid=args.uuid,
)

PORT_VALIDATOR = args.and_valid(
    args.schema(PORT_SCHEMA),
    PORT_VALIDATOR_EXTRA
)

PORT_PATCH_VALIDATOR = args.and_valid(
    args.schema(PORT_PATCH_SCHEMA),
    PORT_VALIDATOR_EXTRA
)


def hide_fields_in_newer_versions(port):
    # if requested version is < 1.18, hide internal_info field
    if not api_utils.allow_port_internal_info():
        port.pop('internal_info', None)
    # if requested version is < 1.19, hide local_link_connection and
    # pxe_enabled fields
    if not api_utils.allow_port_advanced_net_fields():
        port.pop('pxe_enabled', None)
        port.pop('local_link_connection', None)
    # if requested version is < 1.24, hide portgroup_uuid field
    if not api_utils.allow_portgroups_subcontrollers():
        port.pop('portgroup_uuid', None)
    # if requested version is < 1.34, hide physical_network field.
    if not api_utils.allow_port_physical_network():
        port.pop('physical_network', None)
    # if requested version is < 1.53, hide is_smartnic field.
    if not api_utils.allow_port_is_smartnic():
        port.pop('is_smartnic', None)


def convert_with_links(rpc_port, fields=None, sanitize=True):
    port = api_utils.object_to_dict(
        rpc_port,
        link_resource='ports',
        fields=(
            'address',
            'extra',
            'internal_info',
            'is_smartnic',
            'local_link_connection',
            'physical_network',
            'pxe_enabled',
        )
    )
    api_utils.populate_node_uuid(rpc_port, port)
    if rpc_port.portgroup_id:
        pg = objects.Portgroup.get(api.request.context, rpc_port.portgroup_id)
        port['portgroup_uuid'] = pg.uuid
    else:
        port['portgroup_uuid'] = None

    _validate_fields(port, fields)

    if not sanitize:
        return port

    port_sanitize(port, fields=fields)

    return port


def _validate_fields(port, fields=None):
    if fields is not None:
        api_utils.check_for_invalid_fields(fields, port)


def port_sanitize(port, fields=None):
    """Removes sensitive and unrequested data.

    Will only keep the fields specified in the ``fields`` parameter.

    :param fields:
        list of fields to preserve, or ``None`` to preserve them all
    :type fields: list of str
    """
    hide_fields_in_newer_versions(port)
    api_utils.sanitize_dict(port, fields)


def list_convert_with_links(rpc_ports, limit, url, fields=None, **kwargs):
    ports = []
    for rpc_port in rpc_ports:
        try:
            port = convert_with_links(rpc_port, fields=fields,
                                      sanitize=False)
        except exception.NodeNotFound:
            # NOTE(dtantsur): node was deleted after we fetched the port
            # list, meaning that the port was also deleted. Skip it.
            LOG.debug('Skipping port %s as its node was deleted',
                      rpc_port.uuid)
            continue
        except exception.PortgroupNotFound:
            # NOTE(dtantsur): port group was deleted after we fetched the
            # port list, it may mean that the port was deleted too, but
            # we don't know it. Pretend that the port group was removed.
            LOG.debug('Removing port group UUID from port %s as the port '
                      'group was deleted', rpc_port.uuid)
            rpc_port.portgroup_id = None
            port = convert_with_links(rpc_port, fields=fields,
                                      sanitize=False)
        ports.append(port)
    return collection.list_convert_with_links(
        items=ports,
        item_name='ports',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=port_sanitize,
        **kwargs
    )


class PortsController(rest.RestController):
    """REST controller for Ports."""

    _custom_actions = {
        'detail': ['GET'],
    }

    invalid_sort_key_list = ['extra', 'internal_info', 'local_link_connection']

    advanced_net_fields = ['pxe_enabled', 'local_link_connection']

    def __init__(self, node_ident=None, portgroup_ident=None):
        super(PortsController, self).__init__()
        self.parent_node_ident = node_ident
        self.parent_portgroup_ident = portgroup_ident

    def _get_ports_collection(self, node_ident, address, portgroup_ident,
                              marker, limit, sort_key, sort_dir,
                              resource_url=None, fields=None, detail=None,
                              project=None):
        """Retrieve a collection of ports.

        :param node_ident: UUID or name of a node, to get only ports for that
                           node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param portgroup_ident: UUID or name of a portgroup, to get only ports
                                for that portgroup.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param resource_url: Optional, base url to be used for links
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        :param detail: Optional, show detailed list of ports
        :param project: Optional, filter by project
        :returns: a list of ports.

        """

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Port.get_by_uuid(api.request.context,
                                                  marker)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        node_ident = self.parent_node_ident or node_ident
        portgroup_ident = self.parent_portgroup_ident or portgroup_ident

        if node_ident and portgroup_ident:
            raise exception.OperationNotPermitted()

        if portgroup_ident:
            # FIXME: Since all we need is the portgroup ID, we can
            #                 make this more efficient by only querying
            #                 for that column. This will get cleaned up
            #                 as we move to the object interface.
            portgroup = api_utils.get_rpc_portgroup(portgroup_ident)
            ports = objects.Port.list_by_portgroup_id(api.request.context,
                                                      portgroup.id, limit,
                                                      marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir,
                                                      project=project)
        elif node_ident:
            # FIXME(comstud): Since all we need is the node ID, we can
            #                 make this more efficient by only querying
            #                 for that column. This will get cleaned up
            #                 as we move to the object interface.
            node = api_utils.get_rpc_node(node_ident)
            ports = objects.Port.list_by_node_id(api.request.context,
                                                 node.id, limit, marker_obj,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir,
                                                 project=project)
        elif address:
            ports = self._get_ports_by_address(address, project=project)
        else:
            ports = objects.Port.list(api.request.context, limit,
                                      marker_obj, sort_key=sort_key,
                                      sort_dir=sort_dir, project=project)
        parameters = {}

        if detail is not None:
            parameters['detail'] = detail

        return list_convert_with_links(ports, limit,
                                       url=resource_url,
                                       fields=fields,
                                       sort_key=sort_key,
                                       sort_dir=sort_dir,
                                       **parameters)

    def _get_ports_by_address(self, address, project=None):
        """Retrieve a port by its address.

        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param project: Optional, filter by project
        :returns: a list with the port, or an empty list if no port is found.

        """
        try:
            port = objects.Port.get_by_address(api.request.context, address,
                                               project=project)
            return [port]
        except exception.PortNotFound:
            return []

    def _check_allowed_port_fields(self, fields):
        """Check if fetching a particular field of a port is allowed.

        Check if the required version is being requested for fields
        that are only allowed to be fetched in a particular API version.

        :param fields: list or set of fields to check
        :raises: NotAcceptable if a field is not allowed
        """
        if fields is None:
            return
        if (not api_utils.allow_port_advanced_net_fields()
                and set(fields).intersection(self.advanced_net_fields)):
            raise exception.NotAcceptable()
        if ('portgroup_uuid' in fields
                and not api_utils.allow_portgroups_subcontrollers()):
            raise exception.NotAcceptable()
        if ('physical_network' in fields
                and not api_utils.allow_port_physical_network()):
            raise exception.NotAcceptable()
        if ('is_smartnic' in fields
                and not api_utils.allow_port_is_smartnic()):
            raise exception.NotAcceptable()
        if ('local_link_connection/network_type' in fields
                and not api_utils.allow_local_link_connection_network_type()):
            raise exception.NotAcceptable()
        if (isinstance(fields, dict)
                and fields.get('local_link_connection') is not None):
            if (not api_utils.allow_local_link_connection_network_type()
                    and 'network_type' in fields['local_link_connection']):
                raise exception.NotAcceptable()

    @METRICS.timer('PortsController.get_all')
    @method.expose()
    @args.validate(node=args.uuid_or_name, node_uuid=args.uuid,
                   address=args.mac_address, marker=args.uuid,
                   limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   portgroup=args.uuid_or_name, detail=args.boolean)
    def get_all(self, node=None, node_uuid=None, address=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc', fields=None,
                portgroup=None, detail=None):
        """Retrieve a list of ports.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node, to get only ports for that
                           node.
        :param node_uuid: UUID of a node, to get only ports for that
                           node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        :param portgroup: UUID or name of a portgroup, to get only ports
                                   for that portgroup.
        :raises: NotAcceptable, HTTPNotFound
        """
        project = api_utils.check_port_list_policy(
            parent_node=self.parent_node_ident,
            parent_portgroup=self.parent_portgroup_ident)

        if self.parent_node_ident:
            node = self.parent_node_ident

        if self.parent_portgroup_ident:
            portgroup = self.parent_portgroup_ident

        api_utils.check_allow_specify_fields(fields)
        self._check_allowed_port_fields(fields)
        self._check_allowed_port_fields([sort_key])

        if portgroup and not api_utils.allow_portgroups_subcontrollers():
            raise exception.NotAcceptable()

        fields = api_utils.get_request_return_fields(fields, detail,
                                                     _DEFAULT_RETURN_FIELDS)

        if not node_uuid and node:
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            # Make sure only one interface, node or node_uuid is used
            if (not api_utils.allow_node_logical_names()
                and not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        return self._get_ports_collection(node_uuid or node, address,
                                          portgroup, marker, limit, sort_key,
                                          sort_dir, resource_url='ports',
                                          fields=fields, detail=detail,
                                          project=project)

    @METRICS.timer('PortsController.detail')
    @method.expose()
    @args.validate(node=args.uuid_or_name, node_uuid=args.uuid,
                   address=args.mac_address, marker=args.uuid,
                   limit=args.integer, sort_key=args.string,
                   sort_dir=args.string,
                   portgroup=args.uuid_or_name)
    def detail(self, node=None, node_uuid=None, address=None, marker=None,
               limit=None, sort_key='id', sort_dir='asc', portgroup=None):
        """Retrieve a list of ports with detail.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node, to get only ports for that
                     node.
        :param node_uuid: UUID of a node, to get only ports for that
                          node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param portgroup: UUID or name of a portgroup, to get only ports
                           for that portgroup.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :raises: NotAcceptable, HTTPNotFound
        """
        project = api_utils.check_port_list_policy(
            parent_node=self.parent_node_ident,
            parent_portgroup=self.parent_portgroup_ident)

        self._check_allowed_port_fields([sort_key])
        if portgroup and not api_utils.allow_portgroups_subcontrollers():
            raise exception.NotAcceptable()

        if not node_uuid and node:
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            # Make sure only one interface, node or node_uuid is used
            if (not api_utils.allow_node_logical_names()
                and not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        # NOTE(lucasagomes): /detail should only work against collections
        parent = api.request.path.split('/')[:-1][-1]
        if parent != "ports":
            raise exception.HTTPNotFound()

        return self._get_ports_collection(node_uuid or node, address,
                                          portgroup, marker, limit, sort_key,
                                          sort_dir,
                                          resource_url='ports/detail',
                                          project=project)

    @METRICS.timer('PortsController.get_one')
    @method.expose()
    @args.validate(port_uuid=args.uuid, fields=args.string_list)
    def get_one(self, port_uuid, fields=None):
        """Retrieve information about the given port.

        :param port_uuid: UUID of a port.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        :raises: NotAcceptable, HTTPNotFound
        """
        if self.parent_node_ident or self.parent_portgroup_ident:
            raise exception.OperationNotPermitted()

        rpc_port, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:port:get', port_uuid)

        api_utils.check_allow_specify_fields(fields)
        self._check_allowed_port_fields(fields)

        return convert_with_links(rpc_port, fields=fields)

    @METRICS.timer('PortsController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('port')
    @args.validate(port=PORT_VALIDATOR)
    def post(self, port):
        """Create a new port.

        :param port: a port within the request body.
        :raises: NotAcceptable, HTTPNotFound, Conflict
        """
        if self.parent_node_ident or self.parent_portgroup_ident:
            raise exception.OperationNotPermitted()

        # NOTE(lucasagomes): Create the node_id attribute on-the-fly
        #                    to satisfy the api -> rpc object
        #                    conversion.
        # NOTE(TheJulia): The get of the node *does* check if the node
        # can be accessed. We need to be able to get the node regardless
        # in order to perform the actual policy check.
        raise_node_not_found = False
        node = None
        owner = None
        lessee = None
        node_uuid = port.get('node_uuid')
        try:
            node = api_utils.replace_node_uuid_with_id(port)
            owner = node.owner
            lessee = node.lessee
        except exception.NotFound:
            raise_node_not_found = True

        # While the rule is for the port, the base object that controls access
        # is the node.
        api_utils.check_owner_policy('node', 'baremetal:port:create',
                                     owner, lessee=lessee,
                                     conceal_node=False)
        if raise_node_not_found:
            # Delayed raise of NodeNotFound because we want to check
            # the access policy first.
            raise exception.NodeNotFound(node=node_uuid,
                                         code=http_client.BAD_REQUEST)

        context = api.request.context

        self._check_allowed_port_fields(port)

        portgroup = None
        if port.get('portgroup_uuid'):
            try:
                portgroup = objects.Portgroup.get(api.request.context,
                                                  port.pop('portgroup_uuid'))
                if portgroup.node_id != node.id:
                    raise exception.BadRequest(_('Port can not be added to a '
                                                 'portgroup belonging to a '
                                                 'different node.'))
                # NOTE(lucasagomes): Create the portgroup_id attribute
                #                    on-the-fly to satisfy the api ->
                #                    rpc object conversion.
                port['portgroup_id'] = portgroup.id
            except exception.PortgroupNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Port
                e.code = http_client.BAD_REQUEST  # BadRequest
                raise e

        if port.get('is_smartnic'):
            try:
                api_utils.LOCAL_LINK_SMART_NIC_VALIDATOR(
                    'local_link_connection',
                    port.get('local_link_connection'))
            except exception.Invalid:
                raise exception.Invalid(
                    "Smart NIC port must have port_id "
                    "and hostname in local_link_connection")

        physical_network = port.get('physical_network')
        if physical_network is not None and not physical_network:
            raise exception.Invalid('A non-empty value is required when '
                                    'setting physical_network')

        if (portgroup and (port.get('pxe_enabled'))):
            if not portgroup.standalone_ports_supported:
                msg = _("Port group %s doesn't support standalone ports. "
                        "This port cannot be created as a member of that "
                        "portgroup as the port's 'pxe_enabled' field was "
                        "set to True.")
                raise exception.Conflict(
                    msg % portgroup.uuid)

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not port.get('uuid'):
            port['uuid'] = uuidutils.generate_uuid()

        rpc_port = objects.Port(context, **port)

        notify_extra = {
            'node_uuid': node.uuid,
            'portgroup_uuid': portgroup and portgroup.uuid or None
        }
        notify.emit_start_notification(context, rpc_port, 'create',
                                       **notify_extra)
        with notify.handle_error_notification(context, rpc_port, 'create',
                                              **notify_extra):
            topic = api.request.rpcapi.get_topic_for(node)
            new_port = api.request.rpcapi.create_port(context, rpc_port,
                                                      topic)
        notify.emit_end_notification(context, new_port, 'create',
                                     **notify_extra)
        # Set the HTTP Location Header
        api.response.location = link.build_url('ports', new_port.uuid)
        return convert_with_links(new_port)

    @METRICS.timer('PortsController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(port_uuid=args.uuid, patch=args.patch)
    def patch(self, port_uuid, patch):
        """Update an existing port.

        :param port_uuid: UUID of a port.
        :param patch: a json PATCH document to apply to this port.
        :raises: NotAcceptable, HTTPNotFound
        """
        if self.parent_node_ident or self.parent_portgroup_ident:
            raise exception.OperationNotPermitted()

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        context = api.request.context
        fields_to_check = set()
        for field in (self.advanced_net_fields
                      + ['portgroup_uuid', 'physical_network',
                         'is_smartnic', 'local_link_connection/network_type']):
            field_path = '/%s' % field
            if (api_utils.get_patch_values(patch, field_path)
                    or api_utils.is_path_removed(patch, field_path)):
                fields_to_check.add(field)
        self._check_allowed_port_fields(fields_to_check)

        rpc_port, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:port:update', port_uuid)

        port_dict = rpc_port.as_dict()
        # NOTE(lucasagomes):
        # 1) Remove node_id because it's an internal value and
        #    not present in the API object
        # 2) Add node_uuid
        port_dict.pop('node_id', None)
        port_dict['node_uuid'] = rpc_node.uuid
        # NOTE(vsaienko):
        # 1) Remove portgroup_id because it's an internal value and
        #    not present in the API object
        # 2) Add portgroup_uuid
        portgroup = None
        if port_dict.get('portgroup_id'):
            portgroup = objects.Portgroup.get_by_id(
                context, port_dict.pop('portgroup_id'))
        port_dict['portgroup_uuid'] = portgroup and portgroup.uuid or None

        port_dict = api_utils.apply_jsonpatch(port_dict, patch)

        try:
            if api_utils.is_path_updated(patch, '/portgroup_uuid'):
                if port_dict.get('portgroup_uuid'):
                    portgroup = objects.Portgroup.get_by_uuid(
                        context, port_dict['portgroup_uuid'])
                else:
                    portgroup = None
        except exception.PortGroupNotFound as e:
            # Change error code because 404 (NotFound) is inappropriate
            # response for a PATCH request to change a Port
            e.code = http_client.BAD_REQUEST  # BadRequest
            raise

        try:
            if port_dict['node_uuid'] != rpc_node.uuid:
                rpc_node = objects.Node.get(
                    api.request.context, port_dict['node_uuid'])
        except exception.NodeNotFound as e:
            # Change error code because 404 (NotFound) is inappropriate
            # response for a PATCH request to change a Port
            e.code = http_client.BAD_REQUEST  # BadRequest
            raise

        api_utils.patched_validate_with_schema(
            port_dict, PORT_PATCH_SCHEMA, PORT_PATCH_VALIDATOR)

        api_utils.patch_update_changed_fields(
            port_dict, rpc_port, fields=objects.Port.fields,
            schema=PORT_PATCH_SCHEMA,
            id_map={
                'node_id': rpc_node.id,
                'portgroup_id': portgroup and portgroup.id or None
            }
        )

        if (rpc_node.provision_state == ir_states.INSPECTING
                and api_utils.allow_inspect_wait_state()):
            msg = _('Cannot update port "%(port)s" on "%(node)s" while it is '
                    'in state "%(state)s".') % {'port': rpc_port.uuid,
                                                'node': rpc_node.uuid,
                                                'state': ir_states.INSPECTING}
            raise exception.ClientSideError(msg,
                                            status_code=http_client.CONFLICT)

        if (api_utils.is_path_updated(patch, '/physical_network')
            and rpc_port['physical_network'] is not None
                and not rpc_port['physical_network']):
            raise exception.Invalid('A non-empty value is required when '
                                    'setting physical_network')

        notify_extra = {'node_uuid': rpc_node.uuid,
                        'portgroup_uuid': portgroup and portgroup.uuid or None}
        notify.emit_start_notification(context, rpc_port, 'update',
                                       **notify_extra)
        with notify.handle_error_notification(context, rpc_port, 'update',
                                              **notify_extra):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_port = api.request.rpcapi.update_port(context, rpc_port,
                                                      topic)

        api_port = convert_with_links(new_port)
        notify.emit_end_notification(context, new_port, 'update',
                                     **notify_extra)

        return api_port

    @METRICS.timer('PortsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(port_uuid=args.uuid)
    def delete(self, port_uuid):
        """Delete a port.

        :param port_uuid: UUID of a port.
        :raises: OperationNotPermitted, HTTPNotFound
        """
        if self.parent_node_ident or self.parent_portgroup_ident:
            raise exception.OperationNotPermitted()

        rpc_port, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:port:delete', port_uuid)

        context = api.request.context

        portgroup_uuid = None
        if rpc_port.portgroup_id:
            portgroup = objects.Portgroup.get_by_id(context,
                                                    rpc_port.portgroup_id)
            portgroup_uuid = portgroup.uuid

        notify_extra = {'node_uuid': rpc_node.uuid,
                        'portgroup_uuid': portgroup_uuid}
        notify.emit_start_notification(context, rpc_port, 'delete',
                                       **notify_extra)
        with notify.handle_error_notification(context, rpc_port, 'delete',
                                              **notify_extra):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            api.request.rpcapi.destroy_port(context, rpc_port, topic)
        notify.emit_end_notification(context, rpc_port, 'delete',
                                     **notify_extra)
