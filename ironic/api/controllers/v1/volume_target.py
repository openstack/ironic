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

_DEFAULT_RETURN_FIELDS = ['uuid', 'node_uuid', 'volume_type',
                          'boot_index', 'volume_id']

TARGET_SCHEMA = {
    'type': 'object',
    'properties': {
        'boot_index': {'type': 'integer'},
        'extra': {'type': ['object', 'null']},
        'node_uuid': {'type': 'string'},
        'properties': {'type': ['object', 'null']},
        'volume_id': {'type': 'string'},
        'volume_type': {'type': 'string'},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['boot_index', 'node_uuid', 'volume_id', 'volume_type'],
    'additionalProperties': False,
}

TARGET_VALIDATOR_EXTRA = args.dict_valid(
    node_uuid=args.uuid,
    uuid=args.uuid,
)

TARGET_VALIDATOR = args.and_valid(
    args.schema(TARGET_SCHEMA),
    TARGET_VALIDATOR_EXTRA
)

PATCH_ALLOWED_FIELDS = [
    'boot_index',
    'extra',
    'node_uuid',
    'properties',
    'volume_id',
    'volume_type'
]


def convert_with_links(rpc_target, fields=None, sanitize=True):
    target = api_utils.object_to_dict(
        rpc_target,
        link_resource='volume/targets',
        fields=(
            'boot_index',
            'extra',
            'properties',
            'volume_id',
            'volume_type'
        )
    )
    api_utils.populate_node_uuid(rpc_target, target)

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, target)

    if not sanitize:
        return target

    api_utils.sanitize_dict(target, fields)

    return target


def list_convert_with_links(rpc_targets, limit, url=None, fields=None,
                            detail=None, **kwargs):
    if detail:
        kwargs['detail'] = detail
    return collection.list_convert_with_links(
        items=[convert_with_links(p, fields=fields, sanitize=False)
               for p in rpc_targets],
        item_name='targets',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=api_utils.sanitize_dict,
        **kwargs
    )


class VolumeTargetsController(rest.RestController):
    """REST controller for VolumeTargets."""

    invalid_sort_key_list = ['extra', 'properties']

    def __init__(self, node_ident=None):
        super(VolumeTargetsController, self).__init__()
        self.parent_node_ident = node_ident

    def _redact_target_properties(self, target):
        # Filters what could contain sensitive information. For iSCSI
        # volumes this can include iscsi connection details which may
        # be sensitive.
        redacted = ('** Value redacted: Requires permission '
                    'baremetal:volume:view_target_properties '
                    'access. Permission denied. **')
        redacted_message = {
            'redacted_contents': redacted
        }
        target.properties = redacted_message

    def _get_volume_targets_collection(self, node_ident, marker, limit,
                                       sort_key, sort_dir, resource_url=None,
                                       fields=None, detail=None,
                                       project=None):
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.VolumeTarget.get_by_uuid(
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
            targets = objects.VolumeTarget.list_by_node_id(
                api.request.context, node.id, limit, marker_obj,
                sort_key=sort_key, sort_dir=sort_dir, project=project)
        else:
            targets = objects.VolumeTarget.list(api.request.context,
                                                limit, marker_obj,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir,
                                                project=project)
        cdict = api.request.context.to_policy_values()
        if not policy.check_policy('baremetal:volume:view_target_properties',
                                   cdict, cdict):
            for target in targets:
                self._redact_target_properties(target)

        return list_convert_with_links(targets, limit,
                                       url=resource_url,
                                       fields=fields,
                                       sort_key=sort_key,
                                       sort_dir=sort_dir,
                                       detail=detail)

    @METRICS.timer('VolumeTargetsController.get_all')
    @method.expose()
    @args.validate(node=args.uuid_or_name, marker=args.uuid,
                   limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
    def get_all(self, node=None, marker=None, limit=None, sort_key='id',
                sort_dir='asc', fields=None, detail=None, project=None):
        """Retrieve a list of volume targets.

        :param node: UUID or name of a node, to get only volume targets
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
        :param project: Optional, an associated node project (owner,
                        or lessee) to filter the query upon.

        :returns: a list of volume targets, or an empty list if no volume
                  target is found.

        :raises: InvalidParameterValue if sort_key does not exist
        :raises: InvalidParameterValue if sort key is invalid for sorting.
        :raises: InvalidParameterValue if both fields and detail are specified.
        """
        project = api_utils.check_volume_list_policy(
            parent_node=self.parent_node_ident)
        if fields is None and not detail:
            fields = _DEFAULT_RETURN_FIELDS

        if fields and detail:
            raise exception.InvalidParameterValue(
                _("Can't fetch a subset of fields with 'detail' set"))

        resource_url = 'volume/targets'
        return self._get_volume_targets_collection(node, marker, limit,
                                                   sort_key, sort_dir,
                                                   resource_url=resource_url,
                                                   fields=fields,
                                                   detail=detail,
                                                   project=project)

    @METRICS.timer('VolumeTargetsController.get_one')
    @method.expose()
    @args.validate(target_uuid=args.uuid, fields=args.string_list)
    def get_one(self, target_uuid, fields=None):
        """Retrieve information about the given volume target.

        :param target_uuid: UUID of a volume target.
        :param fields: Optional, a list with a specified set of fields
               of the resource to be returned.

        :returns: API-serializable volume target object.

        :raises: OperationNotPermitted if accessed with specifying a parent
                 node.
        :raises: VolumeTargetNotFound if no volume target with this UUID exists
        """

        rpc_target, _ = api_utils.check_volume_policy_and_retrieve(
            'baremetal:volume:get',
            target_uuid,
            target=True)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        cdict = api.request.context.to_policy_values()
        if not policy.check_policy('baremetal:volume:view_target_properties',
                                   cdict, cdict):
            self._redact_target_properties(rpc_target)

        return convert_with_links(rpc_target, fields=fields)

    @METRICS.timer('VolumeTargetsController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('target')
    @args.validate(target=TARGET_VALIDATOR)
    def post(self, target):
        """Create a new volume target.

        :param target: a volume target within the request body.

        :returns: API-serializable volume target object.

        :raises: OperationNotPermitted if accessed with specifying a parent
                 node.
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same node ID and boot index
        :raises: VolumeTargetAlreadyExists if a volume target with the same
                 UUID exists
        """
        context = api.request.context
        raise_node_not_found = False
        node = None
        owner = None
        lessee = None
        node_uuid = target.get('node_uuid')
        try:
            node = api_utils.replace_node_uuid_with_id(target)
            owner = node.owner
            lessee = node.lessee
        except exception.NotFound:
            raise_node_not_found = True
        api_utils.check_owner_policy('node', 'baremetal:volume:create',
                                     owner, lessee=lessee,
                                     conceal_node=False)
        if raise_node_not_found:
            raise exception.InvalidInput(fieldname='node_uuid',
                                         value=node_uuid)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        # NOTE(hshiina): UUID is mandatory for notification payload
        if not target.get('uuid'):
            target['uuid'] = uuidutils.generate_uuid()
        new_target = objects.VolumeTarget(context, **target)

        notify.emit_start_notification(context, new_target, 'create',
                                       node_uuid=node.uuid)
        with notify.handle_error_notification(context, new_target, 'create',
                                              node_uuid=node.uuid):
            new_target.create()
        notify.emit_end_notification(context, new_target, 'create',
                                     node_uuid=node.uuid)
        # Set the HTTP Location Header
        api.response.location = link.build_url('volume/targets',
                                               new_target.uuid)
        return convert_with_links(new_target)

    @METRICS.timer('VolumeTargetsController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(target_uuid=args.uuid, patch=args.patch)
    def patch(self, target_uuid, patch):
        """Update an existing volume target.

        :param target_uuid: UUID of a volume target.
        :param patch: a json PATCH document to apply to this volume target.

        :returns: API-serializable volume target object.

        :raises: OperationNotPermitted if accessed with specifying a
                 parent node.
        :raises: PatchError if a given patch can not be applied.
        :raises: InvalidParameterValue if the volume target's UUID is being
                 changed
        :raises: NodeLocked if the node is already locked
        :raises: NodeNotFound if the node associated with the volume target
                 does not exist
        :raises: VolumeTargetNotFound if the volume target cannot be found
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same node ID and boot index values
        :raises: InvalidUUID if invalid node UUID is passed in the patch.
        :raises: InvalidStateRequested If a node associated with the
                 volume target is not powered off.
        """
        context = api.request.context

        api_utils.check_volume_policy_and_retrieve('baremetal:volume:update',
                                                   target_uuid,
                                                   target=True)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        values = api_utils.get_patch_values(patch, '/node_uuid')
        for value in values:
            if not uuidutils.is_uuid_like(value):
                message = _("Expected a UUID for node_uuid, but received "
                            "%(uuid)s.") % {'uuid': str(value)}
                raise exception.InvalidUUID(message=message)

        rpc_target = objects.VolumeTarget.get_by_uuid(context, target_uuid)
        target_dict = rpc_target.as_dict()
        # NOTE(smoriya):
        # 1) Remove node_id because it's an internal value and
        #    not present in the API object
        # 2) Add node_uuid
        rpc_node = api_utils.replace_node_id_with_uuid(target_dict)

        target_dict = api_utils.apply_jsonpatch(target_dict, patch)

        try:
            if target_dict['node_uuid'] != rpc_node.uuid:

                # TODO(TheJulia): I guess the intention is to
                # permit the mapping to be changed
                # should we even allow this at all?
                rpc_node = objects.Node.get(
                    api.request.context, target_dict['node_uuid'])
        except exception.NodeNotFound as e:
            # Change error code because 404 (NotFound) is inappropriate
            # response for a PATCH request to change a volume target
            e.code = http_client.BAD_REQUEST  # BadRequest
            raise

        api_utils.patched_validate_with_schema(
            target_dict, TARGET_SCHEMA, TARGET_VALIDATOR)

        api_utils.patch_update_changed_fields(
            target_dict, rpc_target, fields=objects.VolumeTarget.fields,
            schema=TARGET_SCHEMA, id_map={'node_id': rpc_node.id}
        )

        notify.emit_start_notification(context, rpc_target, 'update',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_target, 'update',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_target = api.request.rpcapi.update_volume_target(
                context, rpc_target, topic)

        api_target = convert_with_links(new_target)
        notify.emit_end_notification(context, new_target, 'update',
                                     node_uuid=rpc_node.uuid)
        return api_target

    @METRICS.timer('VolumeTargetsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(target_uuid=args.uuid)
    def delete(self, target_uuid):
        """Delete a volume target.

        :param target_uuid: UUID of a volume target.

        :raises: OperationNotPermitted if accessed with specifying a
                 parent node.
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the target does
                 not exist
        :raises: VolumeTargetNotFound if the volume target cannot be found
        :raises: InvalidStateRequested If a node associated with the
                 volume target is not powered off.
        """
        context = api.request.context

        api_utils.check_volume_policy_and_retrieve('baremetal:volume:delete',
                                                   target_uuid,
                                                   target=True)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        rpc_target = objects.VolumeTarget.get_by_uuid(context, target_uuid)
        rpc_node = objects.Node.get_by_id(context, rpc_target.node_id)
        notify.emit_start_notification(context, rpc_target, 'delete',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_target, 'delete',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            api.request.rpcapi.destroy_volume_target(context,
                                                     rpc_target, topic)
        notify.emit_end_notification(context, rpc_target, 'delete',
                                     node_uuid=rpc_node.uuid)
