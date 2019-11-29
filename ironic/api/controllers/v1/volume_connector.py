# Copyright (c) 2017 Hitachi, Ltd.
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
from oslo_utils import uuidutils
from pecan import rest
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
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ('uuid', 'node_uuid', 'type', 'connector_id')


class VolumeConnector(base.APIBase):
    """API representation of a volume connector.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a volume
    connector.
    """

    _node_uuid = None

    def _get_node_uuid(self):
        return self._node_uuid

    def _set_node_identifiers(self, value):
        """Set both UUID and ID of a node for VolumeConnector object

        :param value: UUID, ID of a node, or wtypes.Unset
        """
        if value == wtypes.Unset:
            self._node_uuid = wtypes.Unset
        elif value and self._node_uuid != value:
            try:
                node = objects.Node.get(api.request.context, value)
                self._node_uuid = node.uuid
                # NOTE(smoriya): Create the node_id attribute on-the-fly
                #                to satisfy the api -> rpc object conversion.
                self.node_id = node.id
            except exception.NodeNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a VolumeConnector
                e.code = http_client.BAD_REQUEST  # BadRequest
                raise

    uuid = types.uuid
    """Unique UUID for this volume connector"""

    type = wsme.wsattr(wtypes.text, mandatory=True)
    """The type of volume connector"""

    connector_id = wsme.wsattr(wtypes.text, mandatory=True)
    """The connector_id for this volume connector"""

    extra = {wtypes.text: types.jsontype}
    """The metadata for this volume connector"""

    node_uuid = wsme.wsproperty(types.uuid, _get_node_uuid,
                                _set_node_identifiers, mandatory=True)
    """The UUID of the node this volume connector belongs to"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated volume connector links"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.VolumeConnector.fields)
        for field in fields:
            # Skip fields we do not expose.
            if not hasattr(self, field):
                continue
            self.fields.append(field)
            setattr(self, field, kwargs.get(field, wtypes.Unset))

        # NOTE(smoriya): node_id is an attribute created on-the-fly
        # by _set_node_uuid(), it needs to be present in the fields so
        # that as_dict() will contain node_id field when converting it
        # before saving it in the database.
        self.fields.append('node_id')
        # NOTE(smoriya): node_uuid is not part of objects.VolumeConnector.-
        #                fields because it's an API-only attribute
        self.fields.append('node_uuid')
        # NOTE(jtaryma): Additionally to node_uuid, node_id is handled as a
        # secondary identifier in case RPC volume connector object dictionary
        # was passed to the constructor.
        self.node_uuid = kwargs.get('node_uuid') or kwargs.get('node_id',
                                                               wtypes.Unset)

    @staticmethod
    def _convert_with_links(connector, url):

        connector.links = [link.Link.make_link('self', url,
                                               'volume/connectors',
                                               connector.uuid),
                           link.Link.make_link('bookmark', url,
                                               'volume/connectors',
                                               connector.uuid,
                                               bookmark=True)
                           ]
        return connector

    @classmethod
    def convert_with_links(cls, rpc_connector, fields=None, sanitize=True):
        connector = VolumeConnector(**rpc_connector.as_dict())

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, connector.as_dict())

        connector = cls._convert_with_links(connector,
                                            api.request.public_url)

        if not sanitize:
            return connector

        connector.sanitize(fields)

        return connector

    def sanitize(self, fields=None):
        """Removes sensitive and unrequested data.

        Will only keep the fields specified in the ``fields`` parameter.

        :param fields:
            list of fields to preserve, or ``None`` to preserve them all
        :type fields: list of str
        """

        if fields is not None:
            self.unset_fields_except(fields)

        # never expose the node_id attribute
        self.node_id = wtypes.Unset

    @classmethod
    def sample(cls, expand=True):
        time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        sample = cls(uuid='86cfd480-0842-4abb-8386-e46149beb82f',
                     type='iqn',
                     connector_id='iqn.2010-10.org.openstack:51332b70524',
                     extra={'foo': 'bar'},
                     created_at=time,
                     updated_at=time)
        sample._node_uuid = '7ae81bb3-dec3-4289-8d6c-da80bd8001ae'
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class VolumeConnectorPatchType(types.JsonPatchType):

    _api_base = VolumeConnector


class VolumeConnectorCollection(collection.Collection):
    """API representation of a collection of volume connectors."""

    connectors = [VolumeConnector]
    """A list containing volume connector objects"""

    def __init__(self, **kwargs):
        self._type = 'connectors'

    @staticmethod
    def convert_with_links(rpc_connectors, limit, url=None, fields=None,
                           detail=None, **kwargs):
        collection = VolumeConnectorCollection()
        collection.connectors = [
            VolumeConnector.convert_with_links(p, fields=fields,
                                               sanitize=False)
            for p in rpc_connectors]
        if detail:
            kwargs['detail'] = detail
        collection.next = collection.get_next(limit, url=url, fields=fields,
                                              **kwargs)
        for connector in collection.connectors:
            connector.sanitize(fields)
        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        sample.connectors = [VolumeConnector.sample(expand=False)]
        return sample


class VolumeConnectorsController(rest.RestController):
    """REST controller for VolumeConnectors."""

    invalid_sort_key_list = ['extra']

    def __init__(self, node_ident=None):
        super(VolumeConnectorsController, self).__init__()
        self.parent_node_ident = node_ident

    def _get_volume_connectors_collection(self, node_ident, marker, limit,
                                          sort_key, sort_dir,
                                          resource_url=None,
                                          fields=None, detail=None):
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.VolumeConnector.get_by_uuid(
                api.request.context, marker)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        node_ident = self.parent_node_ident or node_ident

        if node_ident:
            # FIXME(comstud): Since all we need is the node ID, we can
            #                 make this more efficient by only querying
            #                 for that column. This will get cleaned up
            #                 as we move to the object interface.
            node = api_utils.get_rpc_node(node_ident)
            connectors = objects.VolumeConnector.list_by_node_id(
                api.request.context, node.id, limit, marker_obj,
                sort_key=sort_key, sort_dir=sort_dir)
        else:
            connectors = objects.VolumeConnector.list(api.request.context,
                                                      limit,
                                                      marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)
        return VolumeConnectorCollection.convert_with_links(connectors, limit,
                                                            url=resource_url,
                                                            fields=fields,
                                                            sort_key=sort_key,
                                                            sort_dir=sort_dir,
                                                            detail=detail)

    @METRICS.timer('VolumeConnectorsController.get_all')
    @expose.expose(VolumeConnectorCollection, types.uuid_or_name, types.uuid,
                   int, wtypes.text, wtypes.text, types.listtype,
                   types.boolean)
    def get_all(self, node=None, marker=None, limit=None, sort_key='id',
                sort_dir='asc', fields=None, detail=None):
        """Retrieve a list of volume connectors.

        :param node: UUID or name of a node, to get only volume connectors
                     for that node.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: "asc".
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        :param detail: Optional, whether to retrieve with detail.

        :returns: a list of volume connectors, or an empty list if no volume
                  connector is found.

        :raises: InvalidParameterValue if sort_key does not exist
        :raises: InvalidParameterValue if sort key is invalid for sorting.
        :raises: InvalidParameterValue if both fields and detail are specified.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:volume:get', cdict, cdict)

        if fields is None and not detail:
            fields = _DEFAULT_RETURN_FIELDS

        if fields and detail:
            raise exception.InvalidParameterValue(
                _("Can't fetch a subset of fields with 'detail' set"))

        resource_url = 'volume/connectors'
        return self._get_volume_connectors_collection(
            node, marker, limit, sort_key, sort_dir, resource_url=resource_url,
            fields=fields, detail=detail)

    @METRICS.timer('VolumeConnectorsController.get_one')
    @expose.expose(VolumeConnector, types.uuid, types.listtype)
    def get_one(self, connector_uuid, fields=None):
        """Retrieve information about the given volume connector.

        :param connector_uuid: UUID of a volume connector.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.

        :returns: API-serializable volume connector object.

        :raises: OperationNotPermitted if accessed with specifying a parent
                 node.
        :raises: VolumeConnectorNotFound if no volume connector exists with
                 the specified UUID.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:volume:get', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        rpc_connector = objects.VolumeConnector.get_by_uuid(
            api.request.context, connector_uuid)
        return VolumeConnector.convert_with_links(rpc_connector, fields=fields)

    @METRICS.timer('VolumeConnectorsController.post')
    @expose.expose(VolumeConnector, body=VolumeConnector,
                   status_code=http_client.CREATED)
    def post(self, connector):
        """Create a new volume connector.

        :param connector: a volume connector within the request body.

        :returns: API-serializable volume connector object.

        :raises: OperationNotPermitted if accessed with specifying a parent
                 node.
        :raises: VolumeConnectorTypeAndIdAlreadyExists if a volume
                 connector already exists with the same type and connector_id
        :raises: VolumeConnectorAlreadyExists if a volume connector with the
                 same UUID already exists
        """
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:volume:create', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        connector_dict = connector.as_dict()
        # NOTE(hshiina): UUID is mandatory for notification payload
        if not connector_dict.get('uuid'):
            connector_dict['uuid'] = uuidutils.generate_uuid()

        new_connector = objects.VolumeConnector(context, **connector_dict)

        notify.emit_start_notification(context, new_connector, 'create',
                                       node_uuid=connector.node_uuid)
        with notify.handle_error_notification(context, new_connector,
                                              'create',
                                              node_uuid=connector.node_uuid):
            new_connector.create()
        notify.emit_end_notification(context, new_connector, 'create',
                                     node_uuid=connector.node_uuid)
        # Set the HTTP Location Header
        api.response.location = link.build_url('volume/connectors',
                                               new_connector.uuid)
        return VolumeConnector.convert_with_links(new_connector)

    @METRICS.timer('VolumeConnectorsController.patch')
    @wsme.validate(types.uuid, [VolumeConnectorPatchType])
    @expose.expose(VolumeConnector, types.uuid,
                   body=[VolumeConnectorPatchType])
    def patch(self, connector_uuid, patch):
        """Update an existing volume connector.

        :param connector_uuid: UUID of a volume connector.
        :param patch: a json PATCH document to apply to this volume connector.

        :returns: API-serializable volume connector object.

        :raises: OperationNotPermitted if accessed with specifying a
                 parent node.
        :raises: PatchError if a given patch can not be applied.
        :raises: VolumeConnectorNotFound if no volume connector exists with
                 the specified UUID.
        :raises: InvalidParameterValue if the volume connector's UUID is being
                 changed
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the connector does
                 not exist
        :raises: VolumeConnectorTypeAndIdAlreadyExists if another connector
                 already exists with the same values for type and connector_id
                 fields
        :raises: InvalidUUID if invalid node UUID is passed in the patch.
        :raises: InvalidStateRequested If a node associated with the
                 volume connector is not powered off.
        """
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:volume:update', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        values = api_utils.get_patch_values(patch, '/node_uuid')
        for value in values:
            if not uuidutils.is_uuid_like(value):
                message = _("Expected a UUID for node_uuid, but received "
                            "%(uuid)s.") % {'uuid': str(value)}
                raise exception.InvalidUUID(message=message)

        rpc_connector = objects.VolumeConnector.get_by_uuid(context,
                                                            connector_uuid)
        connector_dict = rpc_connector.as_dict()
        # NOTE(smoriya):
        # 1) Remove node_id because it's an internal value and
        #    not present in the API object
        # 2) Add node_uuid
        connector_dict['node_uuid'] = connector_dict.pop('node_id', None)
        connector = VolumeConnector(
            **api_utils.apply_jsonpatch(connector_dict, patch))

        # Update only the fields that have changed.
        for field in objects.VolumeConnector.fields:
            try:
                patch_val = getattr(connector, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_connector[field] != patch_val:
                rpc_connector[field] = patch_val

        rpc_node = objects.Node.get_by_id(context,
                                          rpc_connector.node_id)
        notify.emit_start_notification(context, rpc_connector, 'update',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_connector, 'update',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_connector = api.request.rpcapi.update_volume_connector(
                context, rpc_connector, topic)

        api_connector = VolumeConnector.convert_with_links(new_connector)
        notify.emit_end_notification(context, new_connector, 'update',
                                     node_uuid=rpc_node.uuid)
        return api_connector

    @METRICS.timer('VolumeConnectorsController.delete')
    @expose.expose(None, types.uuid, status_code=http_client.NO_CONTENT)
    def delete(self, connector_uuid):
        """Delete a volume connector.

        :param connector_uuid: UUID of a volume connector.

        :raises: OperationNotPermitted if accessed with specifying a
                 parent node.
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the connector does
                 not exist
        :raises: VolumeConnectorNotFound if the volume connector cannot be
                 found
        :raises: InvalidStateRequested If a node associated with the
                 volume connector is not powered off.
        """
        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:volume:delete', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        rpc_connector = objects.VolumeConnector.get_by_uuid(context,
                                                            connector_uuid)
        rpc_node = objects.Node.get_by_id(context, rpc_connector.node_id)
        notify.emit_start_notification(context, rpc_connector, 'delete',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_connector,
                                              'delete',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            api.request.rpcapi.destroy_volume_connector(context,
                                                        rpc_connector, topic)
        notify.emit_end_notification(context, rpc_connector, 'delete',
                                     node_uuid=rpc_node.uuid)
