# Copyright 2018 Red Hat Inc.
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
from ironic.common import exception
from ironic.common import policy
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)


def convert_with_links(rpc_bios, node_uuid):
    """Build a dict containing a bios setting value."""
    bios = api_utils.object_to_dict(
        rpc_bios,
        include_uuid=False,
        fields=('name', 'value'),
        link_resource='nodes',
        link_resource_args="%s/bios/%s" % (node_uuid, rpc_bios.name),
    )
    return bios


def collection_from_list(node_ident, bios_settings):
    bios_list = []
    for bios_setting in bios_settings:
        bios_list.append(convert_with_links(bios_setting, node_ident))
    return {'bios': bios_list}


class NodeBiosController(rest.RestController):
    """REST controller for bios."""

    def __init__(self, node_ident=None):
        super(NodeBiosController, self).__init__()
        self.node_ident = node_ident

    @METRICS.timer('NodeBiosController.get_all')
    @method.expose()
    def get_all(self):
        """List node bios settings."""
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:node:bios:get', cdict, cdict)

        node = api_utils.get_rpc_node(self.node_ident)
        settings = objects.BIOSSettingList.get_by_node_id(
            api.request.context, node.id)
        return collection_from_list(self.node_ident, settings)

    @METRICS.timer('NodeBiosController.get_one')
    @method.expose()
    @args.validate(setting_name=args.name)
    def get_one(self, setting_name):
        """Retrieve information about the given bios setting.

        :param setting_name: Logical name of the setting to retrieve.
        """
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:node:bios:get', cdict, cdict)

        node = api_utils.get_rpc_node(self.node_ident)
        try:
            setting = objects.BIOSSetting.get(api.request.context, node.id,
                                              setting_name)
        except exception.BIOSSettingNotFound:
            raise exception.BIOSSettingNotFound(node=node.uuid,
                                                name=setting_name)

        return {setting_name: convert_with_links(setting, node.uuid)}
