# Copyright 2023 Red Hat Inc.
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

from ironic_lib import metrics_utils
from pecan import rest

from ironic import api
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)

_DEFAULT_RETURN_FIELDS = ('component', 'initial_version', 'current_version',
                          'last_version_flashed')


# NOTE(iurygregory): Keeping same parameters just in case we decide
# to support /v1/nodes/<node_uuid>/firmware/<component>
def convert_with_links(rpc_firmware, node_uuid, detail=None, fields=None):
    """Build a dict containing a firmware component."""

    fw_component = api_utils.object_to_dict(
        rpc_firmware,
        include_uuid=False,
        fields=fields,
    )
    return fw_component


def collection_from_list(node_ident, firmware_components, detail=None,
                         fields=None):
    firmware_list = []
    for fw_cmp in firmware_components:
        firmware_list.append(convert_with_links(fw_cmp, node_ident,
                             detail, fields))
    return {'firmware': firmware_list}


class NodeFirmwareController(rest.RestController):
    """REST controller for Firmware."""

    def __init__(self, node_ident=None):
        super(NodeFirmwareController, self).__init__()
        self.node_ident = node_ident

    @METRICS.timer('NodeFirmwareController.get_all')
    @method.expose()
    @args.validate(fields=args.string_list, detail=args.boolean)
    def get_all(self, detail=None, fields=None):
        """List node firmware components."""
        node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:firmware:get', self.node_ident)

        allow_query = api_utils.allow_firmware_interface
        fields = api_utils.get_request_return_fields(fields, detail,
                                                     _DEFAULT_RETURN_FIELDS,
                                                     allow_query, allow_query)
        components = objects.FirmwareComponentList.get_by_node_id(
            api.request.context, node.id)
        return collection_from_list(self.node_ident, components,
                                    detail, fields)
