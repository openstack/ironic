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
import wsme
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import utils as common_utils
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ('uuid', 'address', 'name')


class Portgroup(base.APIBase):
    """API representation of a portgroup.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a
    portgroup.
    """

    _node_uuid = None

    def _get_node_uuid(self):
        return self._node_uuid

    def _set_node_uuid(self, value):
        if value and self._node_uuid != value:
            if not api_utils.allow_portgroups():
                self._node_uuid = wtypes.Unset
                return
            try:
                node = objects.Node.get(pecan.request.context, value)
                self._node_uuid = node.uuid
                # NOTE: Create the node_id attribute on-the-fly
                #       to satisfy the api -> rpc object
                #       conversion.
                self.node_id = node.id
            except exception.NodeNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Portgroup
                e.code = http_client.BAD_REQUEST
                raise e
        elif value == wtypes.Unset:
            self._node_uuid = wtypes.Unset

    uuid = types.uuid
    """Unique UUID for this portgroup"""

    address = wsme.wsattr(types.macaddress)
    """MAC Address for this portgroup"""

    extra = {wtypes.text: types.jsontype}
    """This portgroup's meta data"""

    internal_info = wsme.wsattr({wtypes.text: types.jsontype}, readonly=True)
    """This portgroup's internal info"""

    node_uuid = wsme.wsproperty(types.uuid, _get_node_uuid, _set_node_uuid,
                                mandatory=True)
    """The UUID of the node this portgroup belongs to"""

    name = wsme.wsattr(wtypes.text)
    """The logical name for this portgroup"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated portgroup links"""

    standalone_ports_supported = types.boolean
    """Indicates whether ports of this portgroup may be used as
       single NIC ports"""

    mode = wsme.wsattr(wtypes.text)
    """The mode for this portgroup. See linux bonding
    documentation for details:
    https://www.kernel.org/doc/Documentation/networking/bonding.txt"""

    properties = {wtypes.text: types.jsontype}
    """This portgroup's properties"""

    ports = wsme.wsattr([link.Link], readonly=True)
    """Links to the collection of ports of this portgroup"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Portgroup.fields)
        # NOTE: node_uuid is not part of objects.Portgroup.fields
        #       because it's an API-only attribute
        fields.append('node_uuid')
        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue
            self.fields.append(field)
            setattr(self, field, kwargs.get(field, wtypes.Unset))

        # NOTE: node_id is an attribute created on-the-fly
        # by _set_node_uuid(), it needs to be present in the fields so
        # that as_dict() will contain node_id field when converting it
        # before saving it in the database.
        self.fields.append('node_id')
        setattr(self, 'node_uuid', kwargs.get('node_id', wtypes.Unset))

    @staticmethod
    def _convert_with_links(portgroup, url, fields=None):
        """Add links to the portgroup."""
        # NOTE(lucasagomes): Since we are able to return a specified set of
        # fields the "uuid" can be unset, so we need to save it in another
        # variable to use when building the links
        portgroup_uuid = portgroup.uuid
        if fields is not None:
            portgroup.unset_fields_except(fields)
        else:
            portgroup.ports = [
                link.Link.make_link('self', url, 'portgroups',
                                    portgroup_uuid + "/ports"),
                link.Link.make_link('bookmark', url, 'portgroups',
                                    portgroup_uuid + "/ports", bookmark=True)
            ]

        # never expose the node_id attribute
        portgroup.node_id = wtypes.Unset

        portgroup.links = [link.Link.make_link('self', url,
                                               'portgroups', portgroup_uuid),
                           link.Link.make_link('bookmark', url,
                                               'portgroups', portgroup_uuid,
                                               bookmark=True)
                           ]
        return portgroup

    @classmethod
    def convert_with_links(cls, rpc_portgroup, fields=None):
        """Add links to the portgroup."""
        portgroup = Portgroup(**rpc_portgroup.as_dict())

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, portgroup.as_dict())

        return cls._convert_with_links(portgroup, pecan.request.host_url,
                                       fields=fields)

    @classmethod
    def sample(cls, expand=True):
        """Return a sample of the portgroup."""
        sample = cls(uuid='a594544a-2daf-420c-8775-17a8c3e0852f',
                     address='fe:54:00:77:07:d9',
                     name='node1-portgroup-01',
                     extra={'foo': 'bar'},
                     internal_info={'baz': 'boo'},
                     standalone_ports_supported=True,
                     mode='active-backup',
                     properties={},
                     created_at=datetime.datetime(2000, 1, 1, 12, 0, 0),
                     updated_at=datetime.datetime(2000, 1, 1, 12, 0, 0))
        # NOTE(lucasagomes): node_uuid getter() method look at the
        # _node_uuid variable
        sample._node_uuid = '7ae81bb3-dec3-4289-8d6c-da80bd8001ae'
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class PortgroupPatchType(types.JsonPatchType):

    _api_base = Portgroup
    _extra_non_removable_attrs = {'/mode'}

    @staticmethod
    def internal_attrs():
        defaults = types.JsonPatchType.internal_attrs()
        return defaults + ['/internal_info']


class PortgroupCollection(collection.Collection):
    """API representation of a collection of portgroups."""

    portgroups = [Portgroup]
    """A list containing portgroup objects"""

    def __init__(self, **kwargs):
        self._type = 'portgroups'

    @staticmethod
    def convert_with_links(rpc_portgroups, limit, url=None, fields=None,
                           **kwargs):
        collection = PortgroupCollection()
        collection.portgroups = [Portgroup.convert_with_links(p, fields=fields)
                                 for p in rpc_portgroups]
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection

    @classmethod
    def sample(cls):
        """Return a sample of the portgroup."""
        sample = cls()
        sample.portgroups = [Portgroup.sample(expand=False)]
        return sample


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
            ident = types.uuid_or_name.validate(ident)
        except exception.InvalidUuidOrName as e:
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
                                   resource_url=None, fields=None):
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
        """
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Portgroup.get_by_uuid(pecan.request.context,
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
                pecan.request.context, node.id, limit,
                marker_obj, sort_key=sort_key, sort_dir=sort_dir)
        elif address:
            portgroups = self._get_portgroups_by_address(address)
        else:
            portgroups = objects.Portgroup.list(pecan.request.context, limit,
                                                marker_obj, sort_key=sort_key,
                                                sort_dir=sort_dir)

        return PortgroupCollection.convert_with_links(portgroups, limit,
                                                      url=resource_url,
                                                      fields=fields,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)

    def _get_portgroups_by_address(self, address):
        """Retrieve a portgroup by its address.

        :param address: MAC address of a portgroup, to get the portgroup
                        which has this MAC address.
        :returns: a list with the portgroup, or an empty list if no portgroup
                  is found.

        """
        try:
            portgroup = objects.Portgroup.get_by_address(pecan.request.context,
                                                         address)
            return [portgroup]
        except exception.PortgroupNotFound:
            return []

    @METRICS.timer('PortgroupsController.get_all')
    @expose.expose(PortgroupCollection, types.uuid_or_name, types.macaddress,
                   types.uuid, int, wtypes.text, wtypes.text, types.listtype)
    def get_all(self, node=None, address=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc', fields=None):
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

        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:portgroup:get', cdict, cdict)

        api_utils.check_allowed_portgroup_fields(fields)
        api_utils.check_allowed_portgroup_fields([sort_key])

        if fields is None:
            fields = _DEFAULT_RETURN_FIELDS

        return self._get_portgroups_collection(node, address,
                                               marker, limit,
                                               sort_key, sort_dir,
                                               fields=fields)

    @METRICS.timer('PortgroupsController.detail')
    @expose.expose(PortgroupCollection, types.uuid_or_name, types.macaddress,
                   types.uuid, int, wtypes.text, wtypes.text)
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

        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:portgroup:get', cdict, cdict)
        api_utils.check_allowed_portgroup_fields([sort_key])

        # NOTE: /detail should only work against collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "portgroups":
            raise exception.HTTPNotFound()

        resource_url = '/'.join(['portgroups', 'detail'])
        return self._get_portgroups_collection(
            node, address, marker, limit, sort_key, sort_dir,
            resource_url=resource_url)

    @METRICS.timer('PortgroupsController.get_one')
    @expose.expose(Portgroup, types.uuid_or_name, types.listtype)
    def get_one(self, portgroup_ident, fields=None):
        """Retrieve information about the given portgroup.

        :param portgroup_ident: UUID or logical name of a portgroup.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:portgroup:get', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        api_utils.check_allowed_portgroup_fields(fields)

        rpc_portgroup = api_utils.get_rpc_portgroup(portgroup_ident)
        return Portgroup.convert_with_links(rpc_portgroup, fields=fields)

    @METRICS.timer('PortgroupsController.post')
    @expose.expose(Portgroup, body=Portgroup, status_code=http_client.CREATED)
    def post(self, portgroup):
        """Create a new portgroup.

        :param portgroup: a portgroup within the request body.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        context = pecan.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:portgroup:create', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        if (not api_utils.allow_portgroup_mode_properties() and
                (portgroup.mode is not wtypes.Unset or
                 portgroup.properties is not wtypes.Unset)):
            raise exception.NotAcceptable()

        if (portgroup.name and
                not api_utils.is_valid_logical_name(portgroup.name)):
            error_msg = _("Cannot create portgroup with invalid name "
                          "'%(name)s'") % {'name': portgroup.name}
            raise wsme.exc.ClientSideError(
                error_msg, status_code=http_client.BAD_REQUEST)

        pg_dict = portgroup.as_dict()
        vif = pg_dict.get('extra', {}).get('vif_port_id')
        if vif:
            common_utils.warn_about_deprecated_extra_vif_port_id()

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not pg_dict.get('uuid'):
            pg_dict['uuid'] = uuidutils.generate_uuid()

        new_portgroup = objects.Portgroup(context, **pg_dict)

        notify.emit_start_notification(context, new_portgroup, 'create',
                                       node_uuid=portgroup.node_uuid)
        with notify.handle_error_notification(context, new_portgroup, 'create',
                                              node_uuid=portgroup.node_uuid):
            new_portgroup.create()
        notify.emit_end_notification(context, new_portgroup, 'create',
                                     node_uuid=portgroup.node_uuid)

        # Set the HTTP Location Header
        pecan.response.location = link.build_url('portgroups',
                                                 new_portgroup.uuid)
        return Portgroup.convert_with_links(new_portgroup)

    @METRICS.timer('PortgroupsController.patch')
    @wsme.validate(types.uuid_or_name, [PortgroupPatchType])
    @expose.expose(Portgroup, types.uuid_or_name, body=[PortgroupPatchType])
    def patch(self, portgroup_ident, patch):
        """Update an existing portgroup.

        :param portgroup_ident: UUID or logical name of a portgroup.
        :param patch: a json PATCH document to apply to this portgroup.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        context = pecan.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:portgroup:update', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        if (not api_utils.allow_portgroup_mode_properties() and
                (api_utils.is_path_updated(patch, '/mode') or
                 api_utils.is_path_updated(patch, '/properties'))):
            raise exception.NotAcceptable()

        rpc_portgroup = api_utils.get_rpc_portgroup(portgroup_ident)

        names = api_utils.get_patch_values(patch, '/name')
        for name in names:
            if (name and
                    not api_utils.is_valid_logical_name(name)):
                error_msg = _("Portgroup %(portgroup)s: Cannot change name to"
                              " invalid name '%(name)s'") % {'portgroup':
                                                             portgroup_ident,
                                                             'name': name}
                raise wsme.exc.ClientSideError(
                    error_msg, status_code=http_client.BAD_REQUEST)

        try:
            portgroup_dict = rpc_portgroup.as_dict()
            # NOTE:
            # 1) Remove node_id because it's an internal value and
            #    not present in the API object
            # 2) Add node_uuid
            portgroup_dict['node_uuid'] = portgroup_dict.pop('node_id', None)
            portgroup = Portgroup(**api_utils.apply_jsonpatch(portgroup_dict,
                                                              patch))
        except api_utils.JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch, reason=e)

        # Update only the fields that have changed
        for field in objects.Portgroup.fields:
            try:
                patch_val = getattr(portgroup, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_portgroup[field] != patch_val:
                rpc_portgroup[field] = patch_val

        rpc_node = objects.Node.get_by_id(context, rpc_portgroup.node_id)

        notify.emit_start_notification(context, rpc_portgroup, 'update',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_portgroup, 'update',
                                              node_uuid=rpc_node.uuid):
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            new_portgroup = pecan.request.rpcapi.update_portgroup(
                context, rpc_portgroup, topic)

        api_portgroup = Portgroup.convert_with_links(new_portgroup)
        notify.emit_end_notification(context, new_portgroup, 'update',
                                     node_uuid=api_portgroup.node_uuid)

        return api_portgroup

    @METRICS.timer('PortgroupsController.delete')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
    def delete(self, portgroup_ident):
        """Delete a portgroup.

        :param portgroup_ident: UUID or logical name of a portgroup.
        """
        if not api_utils.allow_portgroups():
            raise exception.NotFound()

        context = pecan.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:portgroup:delete', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        rpc_portgroup = api_utils.get_rpc_portgroup(portgroup_ident)
        rpc_node = objects.Node.get_by_id(pecan.request.context,
                                          rpc_portgroup.node_id)

        notify.emit_start_notification(context, rpc_portgroup, 'delete',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_portgroup, 'delete',
                                              node_uuid=rpc_node.uuid):
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            pecan.request.rpcapi.destroy_portgroup(context, rpc_portgroup,
                                                   topic)
        notify.emit_end_notification(context, rpc_portgroup, 'delete',
                                     node_uuid=rpc_node.uuid)
