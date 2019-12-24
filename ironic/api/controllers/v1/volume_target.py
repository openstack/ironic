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

_DEFAULT_RETURN_FIELDS = ('uuid', 'node_uuid', 'volume_type',
                          'boot_index', 'volume_id')


class VolumeTarget(base.APIBase):
    """API representation of a volume target.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a volume
    target.
    """

    _node_uuid = None

    def _get_node_uuid(self):
        return self._node_uuid

    def _set_node_identifiers(self, value):
        """Set both UUID and ID of a node for VolumeTarget object

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
                # response for a POST request to create a VolumeTarget
                e.code = http_client.BAD_REQUEST  # BadRequest
                raise

    uuid = types.uuid
    """Unique UUID for this volume target"""

    volume_type = wsme.wsattr(wtypes.text, mandatory=True)
    """The volume_type of volume target"""

    properties = {wtypes.text: types.jsontype}
    """The properties for this volume target"""

    boot_index = wsme.wsattr(int, mandatory=True)
    """The boot_index of volume target"""

    volume_id = wsme.wsattr(wtypes.text, mandatory=True)
    """The volume_id for this volume target"""

    extra = {wtypes.text: types.jsontype}
    """The metadata for this volume target"""

    node_uuid = wsme.wsproperty(types.uuid, _get_node_uuid,
                                _set_node_identifiers, mandatory=True)
    """The UUID of the node this volume target belongs to"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated volume target links"""

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.VolumeTarget.fields)
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
        # NOTE(smoriya): node_uuid is not part of objects.VolumeTarget.-
        #                fields because it's an API-only attribute
        self.fields.append('node_uuid')
        # NOTE(jtaryma): Additionally to node_uuid, node_id is handled as a
        # secondary identifier in case RPC volume target object dictionary
        # was passed to the constructor.
        self.node_uuid = kwargs.get('node_uuid') or kwargs.get('node_id',
                                                               wtypes.Unset)

    @staticmethod
    def _convert_with_links(target, url):

        target.links = [link.Link.make_link('self', url,
                                            'volume/targets',
                                            target.uuid),
                        link.Link.make_link('bookmark', url,
                                            'volume/targets',
                                            target.uuid,
                                            bookmark=True)
                        ]
        return target

    @classmethod
    def convert_with_links(cls, rpc_target, fields=None, sanitize=True):
        target = VolumeTarget(**rpc_target.as_dict())

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, target.as_dict())

        target = cls._convert_with_links(target, api.request.public_url)

        if not sanitize:
            return target

        target.sanitize(fields)

        return target

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
        properties = {"auth_method": "CHAP",
                      "auth_username": "XXX",
                      "auth_password": "XXX",
                      "target_iqn": "iqn.2010-10.com.example:vol-X",
                      "target_portal": "192.168.0.123:3260",
                      "volume_id": "a2f3ff15-b3ea-4656-ab90-acbaa1a07607",
                      "target_lun": 0,
                      "access_mode": "rw"}

        sample = cls(uuid='667808d4-622f-4629-b629-07753a19e633',
                     volume_type='iscsi',
                     boot_index=0,
                     volume_id='a2f3ff15-b3ea-4656-ab90-acbaa1a07607',
                     properties=properties,
                     extra={'foo': 'bar'},
                     created_at=time,
                     updated_at=time)
        sample._node_uuid = '7ae81bb3-dec3-4289-8d6c-da80bd8001ae'
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class VolumeTargetPatchType(types.JsonPatchType):

    _api_base = VolumeTarget


class VolumeTargetCollection(collection.Collection):
    """API representation of a collection of volume targets."""

    targets = [VolumeTarget]
    """A list containing volume target objects"""

    def __init__(self, **kwargs):
        self._type = 'targets'

    @staticmethod
    def convert_with_links(rpc_targets, limit, url=None, fields=None,
                           detail=None, **kwargs):
        collection = VolumeTargetCollection()
        collection.targets = [
            VolumeTarget.convert_with_links(p, fields=fields, sanitize=False)
            for p in rpc_targets]
        if detail:
            kwargs['detail'] = detail
        collection.next = collection.get_next(limit, url=url, fields=fields,
                                              **kwargs)
        for target in collection.targets:
            target.sanitize(fields)
        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        sample.targets = [VolumeTarget.sample(expand=False)]
        return sample


class VolumeTargetsController(rest.RestController):
    """REST controller for VolumeTargets."""

    invalid_sort_key_list = ['extra', 'properties']

    def __init__(self, node_ident=None):
        super(VolumeTargetsController, self).__init__()
        self.parent_node_ident = node_ident

    def _get_volume_targets_collection(self, node_ident, marker, limit,
                                       sort_key, sort_dir, resource_url=None,
                                       fields=None, detail=None):
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
                sort_key=sort_key, sort_dir=sort_dir)
        else:
            targets = objects.VolumeTarget.list(api.request.context,
                                                limit, marker_obj,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir)
        return VolumeTargetCollection.convert_with_links(targets, limit,
                                                         url=resource_url,
                                                         fields=fields,
                                                         sort_key=sort_key,
                                                         sort_dir=sort_dir,
                                                         detail=detail)

    @METRICS.timer('VolumeTargetsController.get_all')
    @expose.expose(VolumeTargetCollection, types.uuid_or_name, types.uuid,
                   int, wtypes.text, wtypes.text, types.listtype,
                   types.boolean)
    def get_all(self, node=None, marker=None, limit=None, sort_key='id',
                sort_dir='asc', fields=None, detail=None):
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

        :returns: a list of volume targets, or an empty list if no volume
                  target is found.

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

        resource_url = 'volume/targets'
        return self._get_volume_targets_collection(node, marker, limit,
                                                   sort_key, sort_dir,
                                                   resource_url=resource_url,
                                                   fields=fields,
                                                   detail=detail)

    @METRICS.timer('VolumeTargetsController.get_one')
    @expose.expose(VolumeTarget, types.uuid, types.listtype)
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
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:volume:get', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        rpc_target = objects.VolumeTarget.get_by_uuid(
            api.request.context, target_uuid)
        return VolumeTarget.convert_with_links(rpc_target, fields=fields)

    @METRICS.timer('VolumeTargetsController.post')
    @expose.expose(VolumeTarget, body=VolumeTarget,
                   status_code=http_client.CREATED)
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
        cdict = context.to_policy_values()
        policy.authorize('baremetal:volume:create', cdict, cdict)

        if self.parent_node_ident:
            raise exception.OperationNotPermitted()

        target_dict = target.as_dict()
        # NOTE(hshiina): UUID is mandatory for notification payload
        if not target_dict.get('uuid'):
            target_dict['uuid'] = uuidutils.generate_uuid()

        new_target = objects.VolumeTarget(context, **target_dict)

        notify.emit_start_notification(context, new_target, 'create',
                                       node_uuid=target.node_uuid)
        with notify.handle_error_notification(context, new_target, 'create',
                                              node_uuid=target.node_uuid):
            new_target.create()
        notify.emit_end_notification(context, new_target, 'create',
                                     node_uuid=target.node_uuid)
        # Set the HTTP Location Header
        api.response.location = link.build_url('volume/targets',
                                               new_target.uuid)
        return VolumeTarget.convert_with_links(new_target)

    @METRICS.timer('VolumeTargetsController.patch')
    @wsme.validate(types.uuid, [VolumeTargetPatchType])
    @expose.expose(VolumeTarget, types.uuid,
                   body=[VolumeTargetPatchType])
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

        rpc_target = objects.VolumeTarget.get_by_uuid(context, target_uuid)
        target_dict = rpc_target.as_dict()
        # NOTE(smoriya):
        # 1) Remove node_id because it's an internal value and
        #    not present in the API object
        # 2) Add node_uuid
        target_dict['node_uuid'] = target_dict.pop('node_id', None)
        target = VolumeTarget(
            **api_utils.apply_jsonpatch(target_dict, patch))

        # Update only the fields that have changed.
        for field in objects.VolumeTarget.fields:
            try:
                patch_val = getattr(target, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_target[field] != patch_val:
                rpc_target[field] = patch_val

        rpc_node = objects.Node.get_by_id(context, rpc_target.node_id)
        notify.emit_start_notification(context, rpc_target, 'update',
                                       node_uuid=rpc_node.uuid)
        with notify.handle_error_notification(context, rpc_target, 'update',
                                              node_uuid=rpc_node.uuid):
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            new_target = api.request.rpcapi.update_volume_target(
                context, rpc_target, topic)

        api_target = VolumeTarget.convert_with_links(new_target)
        notify.emit_end_notification(context, new_target, 'update',
                                     node_uuid=rpc_node.uuid)
        return api_target

    @METRICS.timer('VolumeTargetsController.delete')
    @expose.expose(None, types.uuid, status_code=http_client.NO_CONTENT)
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
        cdict = context.to_policy_values()
        policy.authorize('baremetal:volume:delete', cdict, cdict)

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
