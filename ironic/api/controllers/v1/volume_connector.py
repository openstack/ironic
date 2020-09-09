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

from http import client as http_client

from ironic_lib import metrics_utils
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
from ironic.common import policy
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ['uuid', 'node_uuid', 'type', 'connector_id']

CONNECTOR_SCHEMA = {
    'type': 'object',
    'properties': {
        'connector_id': {'type': 'string'},
        'extra': {'type': ['object', 'null']},
        'node_uuid': {'type': 'string'},
        'type': {'type': 'string'},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['connector_id', 'node_uuid', 'type'],
    'additionalProperties': False,
}

CONNECTOR_VALIDATOR_EXTRA = args.dict_valid(
    node_uuid=args.uuid,
    uuid=args.uuid,
)

CONNECTOR_VALIDATOR = args.and_valid(
    args.schema(CONNECTOR_SCHEMA),
    CONNECTOR_VALIDATOR_EXTRA
)

PATCH_ALLOWED_FIELDS = [
    'connector_id',
    'extra',
    'node_uuid',
    'type'
]


def convert_with_links(rpc_connector, fields=None, sanitize=True):
    connector = api_utils.object_to_dict(
        rpc_connector,
        link_resource='volume/connectors',
        fields=('connector_id', 'extra', 'type')
    )
    api_utils.populate_node_uuid(rpc_connector, connector)

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, connector)

    if not sanitize:
        return connector

    api_utils.sanitize_dict(connector, fields)

    return connector


def list_convert_with_links(rpc_connectors, limit, url=None, fields=None,
                            detail=None, **kwargs):
    if detail:
        kwargs['detail'] = detail
    return collection.list_convert_with_links(
        items=[convert_with_links(p, fields=fields, sanitize=False)
               for p in rpc_connectors],
        item_name='connectors',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=api_utils.sanitize_dict,
        **kwargs
    )


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
        return list_convert_with_links(connectors, limit,
                                       url=resource_url,
                                       fields=fields,
                                       sort_key=sort_key,
                                       sort_dir=sort_dir,
                                       detail=detail)

    @METRICS.timer('VolumeConnectorsController.get_all')
    @method.expose()
    @args.validate(node=args.uuid_or_name, marker=args.uuid,
                   limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
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
    @method.expose()
    @args.validate(connector_uuid=args.uuid, fields=args.string_list)
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
        return convert_with_links(rpc_connector, fields=fields)

    @METRICS.timer('VolumeConnectorsController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('connector')
    @args.validate(connector=CONNECTOR_VALIDATOR)
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

        # NOTE(hshiina): UUID is mandatory for notification payload
        if not connector.get('uuid'):
            connector['uuid'] = uuidutils.generate_uuid()

        node = api_utils.replace_node_uuid_with_id(connector)

        new_connector = objects.VolumeConnector(context, **connector)

        notify.emit_start_notification(context, new_connector, 'create',
                                       node_uuid=node.uuid)
        with notify.handle_error_notification(context, new_connector,
                                              'create',
                                              node_uuid=node.uuid):
            new_connector.create()
        notify.emit_end_notification(context, new_connector, 'create',
                                     node_uuid=node.uuid)
        # Set the HTTP Location Header
        api.response.location = link.build_url('volume/connectors',
                                               new_connector.uuid)
        return convert_with_links(new_connector)

    @METRICS.timer('VolumeConnectorsController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(connector_uuid=args.uuid, patch=args.patch)
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

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        for value in api_utils.get_patch_values(patch, '/node_uuid'):
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
        rpc_node = api_utils.replace_node_id_with_uuid(connector_dict)

        connector_dict = api_utils.apply_jsonpatch(connector_dict, patch)

        try:
            if connector_dict['node_uuid'] != rpc_node.uuid:
                rpc_node = objects.Node.get(
                    api.request.context, connector_dict['node_uuid'])
        except exception.NodeNotFound as e:
            # Change error code because 404 (NotFound) is inappropriate
            # response for a PATCH request to change a Port
            e.code = http_client.BAD_REQUEST  # BadRequest
            raise

        api_utils.patched_validate_with_schema(
            connector_dict, CONNECTOR_SCHEMA, CONNECTOR_VALIDATOR)

        api_utils.patch_update_changed_fields(
            connector_dict, rpc_connector,
            fields=objects.VolumeConnector.fields,
            schema=CONNECTOR_SCHEMA, id_map={'node_id': rpc_node.id}
        )

        notify.emit_start_notification(context, rpc_connector, 'update',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_connector, 'update',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_connector = api.request.rpcapi.update_volume_connector(
                context, rpc_connector, topic)

        api_connector = convert_with_links(new_connector)
        notify.emit_end_notification(context, new_connector, 'update',
                                     node_uuid=rpc_node.uuid)
        return api_connector

    @METRICS.timer('VolumeConnectorsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(connector_uuid=args.uuid)
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
