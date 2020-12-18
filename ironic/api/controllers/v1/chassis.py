# Copyright 2013 Red Hat, Inc.
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
from oslo_utils import uuidutils
from pecan import rest

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import node
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)

CHASSIS_SCHEMA = {
    'type': 'object',
    'properties': {
        'uuid': {'type': ['string', 'null']},
        'extra': {'type': ['object', 'null']},
        'description': {'type': ['string', 'null'], 'maxLength': 255},
    },
    'additionalProperties': False,
}

CHASSIS_VALIDATOR = args.and_valid(
    args.schema(CHASSIS_SCHEMA),
    args.dict_valid(uuid=args.uuid)
)

DEFAULT_RETURN_FIELDS = ['uuid', 'description']


def convert_with_links(rpc_chassis, fields=None, sanitize=True):
    chassis = api_utils.object_to_dict(
        rpc_chassis,
        fields=('description', 'extra'),
        link_resource='chassis'
    )

    url = api.request.public_url
    chassis['nodes'] = [
        link.make_link('self',
                       url,
                       'chassis',
                       rpc_chassis.uuid + "/nodes"),
        link.make_link('bookmark',
                       url,
                       'chassis',
                       rpc_chassis.uuid + "/nodes",
                       bookmark=True)],

    if fields is not None:
        api_utils.check_for_invalid_fields(fields, chassis)

    if sanitize:
        api_utils.sanitize_dict(chassis, fields)
    return chassis


def list_convert_with_links(rpc_chassis_list, limit, url=None, fields=None,
                            **kwargs):
    return collection.list_convert_with_links(
        items=[convert_with_links(ch, fields=fields,
                                  sanitize=False)
               for ch in rpc_chassis_list],
        item_name='chassis',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=api_utils.sanitize_dict,
        **kwargs
    )


class ChassisController(rest.RestController):
    """REST controller for Chassis."""

    nodes = node.NodesController()
    """Expose nodes as a sub-element of chassis"""

    # Set the flag to indicate that the requests to this resource are
    # coming from a top-level resource
    nodes.from_chassis = True

    _custom_actions = {
        'detail': ['GET'],
    }

    invalid_sort_key_list = ['extra']

    def _get_chassis_collection(self, marker, limit, sort_key, sort_dir,
                                resource_url=None, fields=None, detail=None):
        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)
        marker_obj = None
        if marker:
            marker_obj = objects.Chassis.get_by_uuid(api.request.context,
                                                     marker)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for sorting")
                % {'key': sort_key})

        chassis = objects.Chassis.list(api.request.context, limit,
                                       marker_obj, sort_key=sort_key,
                                       sort_dir=sort_dir)
        parameters = {}
        if detail is not None:
            parameters['detail'] = detail

        return list_convert_with_links(chassis, limit,
                                       url=resource_url,
                                       fields=fields,
                                       sort_key=sort_key,
                                       sort_dir=sort_dir,
                                       **parameters)

    @METRICS.timer('ChassisController.get_all')
    @method.expose()
    @args.validate(marker=args.uuid, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, fields=args.string_list,
                   detail=args.boolean)
    def get_all(self, marker=None, limit=None, sort_key='id', sort_dir='asc',
                fields=None, detail=None):
        """Retrieve a list of chassis.

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
        api_utils.check_policy('baremetal:chassis:get')

        api_utils.check_allow_specify_fields(fields)

        fields = api_utils.get_request_return_fields(fields, detail,
                                                     DEFAULT_RETURN_FIELDS)

        return self._get_chassis_collection(marker, limit, sort_key, sort_dir,
                                            fields=fields, detail=detail)

    @METRICS.timer('ChassisController.detail')
    @method.expose()
    @args.validate(marker=args.uuid, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string)
    def detail(self, marker=None, limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of chassis with detail.

        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        api_utils.check_policy('baremetal:chassis:get')

        # /detail should only work against collections
        parent = api.request.path.split('/')[:-1][-1]
        if parent != "chassis":
            raise exception.HTTPNotFound()

        resource_url = '/'.join(['chassis', 'detail'])
        return self._get_chassis_collection(marker, limit, sort_key, sort_dir,
                                            resource_url)

    @METRICS.timer('ChassisController.get_one')
    @method.expose()
    @args.validate(chassis_uuid=args.uuid, fields=args.string_list)
    def get_one(self, chassis_uuid, fields=None):
        """Retrieve information about the given chassis.

        :param chassis_uuid: UUID of a chassis.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        api_utils.check_policy('baremetal:chassis:get')

        api_utils.check_allow_specify_fields(fields)
        rpc_chassis = objects.Chassis.get_by_uuid(api.request.context,
                                                  chassis_uuid)
        return convert_with_links(rpc_chassis, fields=fields)

    @METRICS.timer('ChassisController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('chassis')
    @args.validate(chassis=CHASSIS_VALIDATOR)
    def post(self, chassis):
        """Create a new chassis.

        :param chassis: a chassis within the request body.
        """
        context = api.request.context
        api_utils.check_policy('baremetal:chassis:create')

        # NOTE(yuriyz): UUID is mandatory for notifications payload
        if not chassis.get('uuid'):
            chassis['uuid'] = uuidutils.generate_uuid()

        new_chassis = objects.Chassis(context, **chassis)
        notify.emit_start_notification(context, new_chassis, 'create')
        with notify.handle_error_notification(context, new_chassis, 'create'):
            new_chassis.create()
        notify.emit_end_notification(context, new_chassis, 'create')
        # Set the HTTP Location Header
        api.response.location = link.build_url('chassis', new_chassis.uuid)
        return convert_with_links(new_chassis)

    @METRICS.timer('ChassisController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(chassis_uuid=args.string, patch=args.patch)
    def patch(self, chassis_uuid, patch):
        """Update an existing chassis.

        :param chassis_uuid: UUID of a chassis.
        :param patch: a json PATCH document to apply to this chassis.
        """
        context = api.request.context
        api_utils.check_policy('baremetal:chassis:update')

        api_utils.patch_validate_allowed_fields(
            patch, CHASSIS_SCHEMA['properties'])

        rpc_chassis = objects.Chassis.get_by_uuid(context, chassis_uuid)
        chassis = api_utils.apply_jsonpatch(rpc_chassis.as_dict(), patch)

        api_utils.patched_validate_with_schema(
            chassis, CHASSIS_SCHEMA, CHASSIS_VALIDATOR)

        api_utils.patch_update_changed_fields(
            chassis, rpc_chassis, fields=objects.Chassis.fields,
            schema=CHASSIS_SCHEMA
        )

        notify.emit_start_notification(context, rpc_chassis, 'update')
        with notify.handle_error_notification(context, rpc_chassis, 'update'):
            rpc_chassis.save()
        notify.emit_end_notification(context, rpc_chassis, 'update')
        return convert_with_links(rpc_chassis)

    @METRICS.timer('ChassisController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(chassis_uuid=args.uuid)
    def delete(self, chassis_uuid):
        """Delete a chassis.

        :param chassis_uuid: UUID of a chassis.
        """
        context = api.request.context
        api_utils.check_policy('baremetal:chassis:delete')

        rpc_chassis = objects.Chassis.get_by_uuid(context, chassis_uuid)
        notify.emit_start_notification(context, rpc_chassis, 'delete')
        with notify.handle_error_notification(context, rpc_chassis, 'delete'):
            rpc_chassis.destroy()
        notify.emit_end_notification(context, rpc_chassis, 'delete')
