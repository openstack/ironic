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
import wsme
from wsme import types as wtypes

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common import policy
from ironic import objects

METRICS = metrics_utils.get_metrics_logger(__name__)


class BIOSSetting(base.APIBase):
    """API representation of a BIOS setting."""

    name = wsme.wsattr(wtypes.text)

    value = wsme.wsattr(wtypes.text)

    links = wsme.wsattr([link.Link], readonly=True)

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.BIOSSetting.fields)
        for k in fields:
            if hasattr(self, k):
                self.fields.append(k)
                value = kwargs.get(k, wtypes.Unset)
                setattr(self, k, value)

    @staticmethod
    def _convert_with_links(bios, node_uuid, url):
        """Add links to the bios setting."""
        name = bios.name
        bios.links = [link.Link.make_link('self', url, 'nodes',
                                          "%s/bios/%s" % (node_uuid, name)),
                      link.Link.make_link('bookmark', url, 'nodes',
                                          "%s/bios/%s" % (node_uuid, name),
                                          bookmark=True)]
        return bios

    @classmethod
    def convert_with_links(cls, rpc_bios, node_uuid):
        """Add links to the bios setting."""
        bios = BIOSSetting(**rpc_bios.as_dict())
        return cls._convert_with_links(bios, node_uuid, api.request.host_url)


class BIOSSettingsCollection(wtypes.Base):
    """API representation of the bios settings for a node."""

    bios = [BIOSSetting]
    """Node bios settings list"""

    @staticmethod
    def collection_from_list(node_ident, bios_settings):
        col = BIOSSettingsCollection()

        bios_list = []
        for bios_setting in bios_settings:
            bios_list.append(BIOSSetting.convert_with_links(bios_setting,
                                                            node_ident))
        col.bios = bios_list
        return col


class NodeBiosController(rest.RestController):
    """REST controller for bios."""

    def __init__(self, node_ident=None):
        super(NodeBiosController, self).__init__()
        self.node_ident = node_ident

    @METRICS.timer('NodeBiosController.get_all')
    @expose.expose(BIOSSettingsCollection)
    def get_all(self):
        """List node bios settings."""
        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:node:bios:get', cdict, cdict)

        node = api_utils.get_rpc_node(self.node_ident)
        settings = objects.BIOSSettingList.get_by_node_id(
            api.request.context, node.id)
        return BIOSSettingsCollection.collection_from_list(self.node_ident,
                                                           settings)

    @METRICS.timer('NodeBiosController.get_one')
    @expose.expose({wtypes.text: BIOSSetting}, types.name)
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

        return {setting_name: BIOSSetting.convert_with_links(setting,
                                                             node.uuid)}
