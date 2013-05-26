# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
Client side of the manager RPC API.
"""

import ironic.openstack.common.rpc.proxy

MANAGER_TOPIC = 'ironic.manager'


class ManagerAPI(ironic.openstack.common.rpc.proxy.RpcProxy):
    """Client side of the manager RPC API.

    API version history:

        1.0 - Initial version.
    """

    RPC_API_VERSION = '1.0'

    def __init__(self, topic=None):
        if topic is None:
            topic = MANAGER_TOPIC

        super(ManagerAPI, self).__init__(
                topic=topic,
                default_version=self.RPC_API_VERSION)

    def get_node_power_state(self, context, node_id):
        """Ask a manager for the node power state.

        :param context: request context.
        :param node_id: node id or uuid.
        :returns: power status.
        """
        return self.call(context,
                         self.make_msg('get_node_power_state',
                                       node_id=node_id))
