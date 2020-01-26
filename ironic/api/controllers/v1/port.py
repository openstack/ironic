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

import datetime
from http import client as http_client

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import uuidutils
from pecan import rest

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states as ir_states
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)
LOG = log.getLogger(__name__)


_DEFAULT_RETURN_FIELDS = ('uuid', 'address')


def hide_fields_in_newer_versions(obj):
    # if requested version is < 1.18, hide internal_info field
    if not api_utils.allow_port_internal_info():
        obj.internal_info = atypes.Unset
    # if requested version is < 1.19, hide local_link_connection and
    # pxe_enabled fields
    if not api_utils.allow_port_advanced_net_fields():
        obj.pxe_enabled = atypes.Unset
        obj.local_link_connection = atypes.Unset
    # if requested version is < 1.24, hide portgroup_uuid field
    if not api_utils.allow_portgroups_subcontrollers():
        obj.portgroup_uuid = atypes.Unset
    # if requested version is < 1.34, hide physical_network field.
    if not api_utils.allow_port_physical_network():
        obj.physical_network = atypes.Unset
    # if requested version is < 1.53, hide is_smartnic field.
    if not api_utils.allow_port_is_smartnic():
        obj.is_smartnic = atypes.Unset


class Port(base.APIBase):
    """API representation of a port.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a port.
    """

    _node_uuid = None
    _portgroup_uuid = None

    def _get_node_uuid(self):
        return self._node_uuid

    def _set_node_uuid(self, value):
        if value and self._node_uuid != value:
            try:
                # FIXME(comstud): One should only allow UUID here, but
                # there seems to be a bug in that tests are passing an
                # ID. See bug #1301046 for more details.
                node = objects.Node.get(api.request.context, value)
                self._node_uuid = node.uuid
                # NOTE(lucasagomes): Create the node_id attribute on-the-fly
                #                    to satisfy the api -> rpc object
                #                    conversion.
                self.node_id = node.id
            except exception.NodeNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Port
                e.code = http_client.BAD_REQUEST  # BadRequest
                raise
        elif value == atypes.Unset:
            self._node_uuid = atypes.Unset

    def _get_portgroup_uuid(self):
        return self._portgroup_uuid

    def _set_portgroup_uuid(self, value):
        if value and self._portgroup_uuid != value:
            if not api_utils.allow_portgroups_subcontrollers():
                self._portgroup_uuid = atypes.Unset
                return
            try:
                portgroup = objects.Portgroup.get(api.request.context, value)
                if portgroup.node_id != self.node_id:
                    raise exception.BadRequest(_('Port can not be added to a '
                                                 'portgroup belonging to a '
                                                 'different node.'))
                self._portgroup_uuid = portgroup.uuid
                # NOTE(lucasagomes): Create the portgroup_id attribute
                #                    on-the-fly to satisfy the api ->
                #                    rpc object conversion.
                self.portgroup_id = portgroup.id
            except exception.PortgroupNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Port
                e.code = http_client.BAD_REQUEST  # BadRequest
                raise e
        elif value == atypes.Unset:
            self._portgroup_uuid = atypes.Unset
        elif value is None and api_utils.allow_portgroups_subcontrollers():
            # This is to output portgroup_uuid field if API version allows this
            self._portgroup_uuid = None

    uuid = types.uuid
    """Unique UUID for this port"""

    address = atypes.wsattr(types.macaddress, mandatory=True)
    """MAC Address for this port"""

    extra = {str: types.jsontype}
    """This port's meta data"""

    internal_info = atypes.wsattr({str: types.jsontype}, readonly=True)
    """This port's internal information maintained by ironic"""

    node_uuid = atypes.wsproperty(types.uuid, _get_node_uuid, _set_node_uuid,
                                  mandatory=True)
    """The UUID of the node this port belongs to"""

    portgroup_uuid = atypes.wsproperty(types.uuid, _get_portgroup_uuid,
                                       _set_portgroup_uuid, mandatory=False)
    """The UUID of the portgroup this port belongs to"""

    pxe_enabled = types.boolean
    """Indicates whether pxe is enabled or disabled on the node."""

    local_link_connection = types.locallinkconnectiontype
    """The port binding profile for the port"""

    physical_network = atypes.StringType(max_length=64)
    """The name of the physical network to which this port is connected."""

    links = atypes.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated port links"""

    is_smartnic = types.boolean
    """Indicates whether this port is a Smart NIC port."""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Port.fields)
        # NOTE(lucasagomes): node_uuid is not part of objects.Port.fields
        #                    because it's an API-only attribute
        fields.append('node_uuid')
        # NOTE: portgroup_uuid is not part of objects.Port.fields
        #                    because it's an API-only attribute
        fields.append('portgroup_uuid')
        for field in fields:
            # Add fields we expose.
            if hasattr(self, field):
                self.fields.append(field)
                setattr(self, field, kwargs.get(field, atypes.Unset))

        # NOTE(lucasagomes): node_id is an attribute created on-the-fly
        # by _set_node_uuid(), it needs to be present in the fields so
        # that as_dict() will contain node_id field when converting it
        # before saving it in the database.
        self.fields.append('node_id')
        setattr(self, 'node_uuid', kwargs.get('node_id', atypes.Unset))

        # NOTE: portgroup_id is an attribute created on-the-fly
        # by _set_portgroup_uuid(), it needs to be present in the fields so
        # that as_dict() will contain portgroup_id field when converting it
        # before saving it in the database.
        self.fields.append('portgroup_id')
        setattr(self, 'portgroup_uuid', kwargs.get('portgroup_id',
                                                   atypes.Unset))

    @classmethod
    def convert_with_links(cls, rpc_port, fields=None, sanitize=True):
        port = Port(**rpc_port.as_dict())

        port._validate_fields(fields)

        url = api.request.public_url

        port.links = [link.Link.make_link('self', url,
                                          'ports', port.uuid),
                      link.Link.make_link('bookmark', url,
                                          'ports', port.uuid,
                                          bookmark=True)
                      ]

        if not sanitize:
            return port

        port.sanitize(fields=fields)

        return port

    def _validate_fields(self, fields=None):
        if fields is not None:
            api_utils.check_for_invalid_fields(fields, self.as_dict())

    def sanitize(self, fields=None):
        """Removes sensitive and unrequested data.

        Will only keep the fields specified in the ``fields`` parameter.

        :param fields:
            list of fields to preserve, or ``None`` to preserve them all
        :type fields: list of str
        """
        hide_fields_in_newer_versions(self)

        if fields is not None:
            self.unset_fields_except(fields)

        # never expose the node_id attribute
        self.node_id = atypes.Unset

        # never expose the portgroup_id attribute
        self.portgroup_id = atypes.Unset

    @classmethod
    def sample(cls, expand=True):
        time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        sample = cls(uuid='27e3153e-d5bf-4b7e-b517-fb518e17f34c',
                     address='fe:54:00:77:07:d9',
                     extra={'foo': 'bar'},
                     internal_info={},
                     created_at=time,
                     updated_at=time,
                     pxe_enabled=True,
                     local_link_connection={
                         'switch_info': 'host', 'port_id': 'Gig0/1',
                         'switch_id': 'aa:bb:cc:dd:ee:ff'},
                     physical_network='physnet1',
                     is_smartnic=False)
        # NOTE(lucasagomes): node_uuid getter() method look at the
        # _node_uuid variable
        sample._node_uuid = '7ae81bb3-dec3-4289-8d6c-da80bd8001ae'
        sample._portgroup_uuid = '037d9a52-af89-4560-b5a3-a33283295ba2'
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class PortPatchType(types.JsonPatchType):
    _api_base = Port

    @staticmethod
    def internal_attrs():
        defaults = types.JsonPatchType.internal_attrs()
        return defaults + ['/internal_info']


class PortCollection(collection.Collection):
    """API representation of a collection of ports."""

    ports = [Port]
    """A list containing ports objects"""

    def __init__(self, **kwargs):
        self._type = 'ports'

    @staticmethod
    def convert_with_links(rpc_ports, limit, url=None, fields=None, **kwargs):
        collection = PortCollection()
        collection.ports = []
        for rpc_port in rpc_ports:
            try:
                port = Port.convert_with_links(rpc_port, fields=fields,
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
                port = Port.convert_with_links(rpc_port, fields=fields,
                                               sanitize=False)

            collection.ports.append(port)

        collection.next = collection.get_next(limit, url=url, fields=fields,
                                              **kwargs)

        for item in collection.ports:
            item.sanitize(fields=fields)

        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        sample.ports = [Port.sample(expand=False)]
        return sample


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
                              owner=None):

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
                                                      owner=owner)
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
                                                 owner=owner)
        elif address:
            ports = self._get_ports_by_address(address, owner=owner)
        else:
            ports = objects.Port.list(api.request.context, limit,
                                      marker_obj, sort_key=sort_key,
                                      sort_dir=sort_dir, owner=owner)
        parameters = {}

        if detail is not None:
            parameters['detail'] = detail

        return PortCollection.convert_with_links(ports, limit,
                                                 url=resource_url,
                                                 fields=fields,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir,
                                                 **parameters)

    def _get_ports_by_address(self, address, owner=None):
        """Retrieve a port by its address.

        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :returns: a list with the port, or an empty list if no port is found.

        """
        try:
            port = objects.Port.get_by_address(api.request.context, address,
                                               owner=owner)
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
    @expose.expose(PortCollection, types.uuid_or_name, types.uuid,
                   types.macaddress, types.uuid, int, str,
                   str, types.listtype, types.uuid_or_name,
                   types.boolean)
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
        owner = api_utils.check_port_list_policy()

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
                                          sort_dir, fields=fields,
                                          detail=detail, owner=owner)

    @METRICS.timer('PortsController.detail')
    @expose.expose(PortCollection, types.uuid_or_name, types.uuid,
                   types.macaddress, types.uuid, int, str,
                   str, types.uuid_or_name)
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
        owner = api_utils.check_port_list_policy()

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

        resource_url = '/'.join(['ports', 'detail'])
        return self._get_ports_collection(node_uuid or node, address,
                                          portgroup, marker, limit, sort_key,
                                          sort_dir, resource_url, owner=owner)

    @METRICS.timer('PortsController.get_one')
    @expose.expose(Port, types.uuid, types.listtype)
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

        return Port.convert_with_links(rpc_port, fields=fields)

    @METRICS.timer('PortsController.post')
    @expose.expose(Port, body=Port, status_code=http_client.CREATED)
    def post(self, port):
        """Create a new port.

        :param port: a port within the request body.
        :raises: NotAcceptable, HTTPNotFound, Conflict
        """
        if self.parent_node_ident or self.parent_portgroup_ident:
            raise exception.OperationNotPermitted()

        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:port:create', cdict, cdict)

        pdict = port.as_dict()
        self._check_allowed_port_fields(pdict)

        if (port.is_smartnic and not types.locallinkconnectiontype
                .validate_for_smart_nic(port.local_link_connection)):
            raise exception.Invalid(
                "Smart NIC port must have port_id "
                "and hostname in local_link_connection")

        create_remotely = api.request.rpcapi.can_send_create_port()
        if (not create_remotely and pdict.get('portgroup_uuid')):
            # NOTE(mgoddard): In RPC API v1.41, port creation was moved to the
            # conductor service to facilitate validation of the physical
            # network field of ports in portgroups. During a rolling upgrade,
            # the RPCAPI will reject the create_port method, so we need to
            # create the port locally. If the port is a member of a portgroup,
            # we are unable to perform the validation and must reject the
            # request.
            raise exception.NotAcceptable()

        vif = api_utils.handle_post_port_like_extra_vif(pdict)

        if (pdict.get('portgroup_uuid')
                and (pdict.get('pxe_enabled') or vif)):
            rpc_pg = objects.Portgroup.get_by_uuid(context,
                                                   pdict['portgroup_uuid'])
            if not rpc_pg.standalone_ports_supported:
                msg = _("Port group %s doesn't support standalone ports. "
                        "This port cannot be created as a member of that "
                        "port group because either 'extra/vif_port_id' "
                        "was specified or 'pxe_enabled' was set to True.")
                raise exception.Conflict(
                    msg % pdict['portgroup_uuid'])

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not pdict.get('uuid'):
            pdict['uuid'] = uuidutils.generate_uuid()

        rpc_port = objects.Port(context, **pdict)
        rpc_node = objects.Node.get_by_id(context, rpc_port.node_id)

        notify_extra = {'node_uuid': port.node_uuid,
                        'portgroup_uuid': port.portgroup_uuid}
        notify.emit_start_notification(context, rpc_port, 'create',
                                       **notify_extra)
        with notify.handle_error_notification(context, rpc_port, 'create',
                                              **notify_extra):
            # NOTE(mgoddard): In RPC API v1.41, port creation was moved to the
            # conductor service to facilitate validation of the physical
            # network field of ports in portgroups. During a rolling upgrade,
            # the RPCAPI will reject the create_port method, so we need to
            # create the port locally.
            if create_remotely:
                topic = api.request.rpcapi.get_topic_for(rpc_node)
                new_port = api.request.rpcapi.create_port(context, rpc_port,
                                                          topic)
            else:
                rpc_port.create()
                new_port = rpc_port
        notify.emit_end_notification(context, new_port, 'create',
                                     **notify_extra)
        # Set the HTTP Location Header
        api.response.location = link.build_url('ports', new_port.uuid)
        return Port.convert_with_links(new_port)

    @METRICS.timer('PortsController.patch')
    @expose.validate(types.uuid, [PortPatchType])
    @expose.expose(Port, types.uuid, body=[PortPatchType])
    def patch(self, port_uuid, patch):
        """Update an existing port.

        :param port_uuid: UUID of a port.
        :param patch: a json PATCH document to apply to this port.
        :raises: NotAcceptable, HTTPNotFound
        """
        if self.parent_node_ident or self.parent_portgroup_ident:
            raise exception.OperationNotPermitted()

        rpc_port, rpc_node = api_utils.check_port_policy_and_retrieve(
            'baremetal:port:update', port_uuid)

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

        port_dict = rpc_port.as_dict()
        # NOTE(lucasagomes):
        # 1) Remove node_id because it's an internal value and
        #    not present in the API object
        # 2) Add node_uuid
        port_dict['node_uuid'] = port_dict.pop('node_id', None)
        # NOTE(vsaienko):
        # 1) Remove portgroup_id because it's an internal value and
        #    not present in the API object
        # 2) Add portgroup_uuid
        port_dict['portgroup_uuid'] = port_dict.pop('portgroup_id', None)
        port = Port(**api_utils.apply_jsonpatch(port_dict, patch))

        api_utils.handle_patch_port_like_extra_vif(rpc_port, port, patch)

        if api_utils.is_path_removed(patch, '/portgroup_uuid'):
            rpc_port.portgroup_id = None

        # Update only the fields that have changed
        for field in objects.Port.fields:
            try:
                patch_val = getattr(port, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == atypes.Unset:
                patch_val = None
            if rpc_port[field] != patch_val:
                rpc_port[field] = patch_val

        if (rpc_node.provision_state == ir_states.INSPECTING
                and api_utils.allow_inspect_wait_state()):
            msg = _('Cannot update port "%(port)s" on "%(node)s" while it is '
                    'in state "%(state)s".') % {'port': rpc_port.uuid,
                                                'node': rpc_node.uuid,
                                                'state': ir_states.INSPECTING}
            raise exception.ClientSideError(msg,
                                            status_code=http_client.CONFLICT)

        notify_extra = {'node_uuid': rpc_node.uuid,
                        'portgroup_uuid': port.portgroup_uuid}
        notify.emit_start_notification(context, rpc_port, 'update',
                                       **notify_extra)
        with notify.handle_error_notification(context, rpc_port, 'update',
                                              **notify_extra):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_port = api.request.rpcapi.update_port(context, rpc_port,
                                                      topic)

        api_port = Port.convert_with_links(new_port)
        notify.emit_end_notification(context, new_port, 'update',
                                     **notify_extra)

        return api_port

    @METRICS.timer('PortsController.delete')
    @expose.expose(None, types.uuid, status_code=http_client.NO_CONTENT)
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
