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
Client side of the networking RPC API.
"""

from oslo_log import log
import oslo_messaging as messaging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.json_rpc import client as json_rpc
from ironic.common import release_mappings as versions
from ironic.common import rpc
from ironic.conf import CONF
from ironic.networking import utils as networking_utils
from ironic.objects import base as objects_base

LOG = log.getLogger(__name__)


class NetworkingAPI(object):
    """Client side of the networking RPC API.

    API version history:

    |    1.0 - Initial version.
    """

    # NOTE(alegacy): This must be in sync with manager.NetworkingManager's.
    RPC_API_VERSION = "1.0"

    def __init__(self, topic=None):
        super(NetworkingAPI, self).__init__()
        self.topic = topic
        if self.topic is None:
            if networking_utils.rpc_transport() == "json-rpc":
                # Use host_ip and port from the JSON-RPC config for topic
                host_ip = CONF.ironic_networking_json_rpc.host_ip
                port = CONF.ironic_networking_json_rpc.port
                topic_host = f"{host_ip}:{port}"
                self.topic = f"ironic.{topic_host}"
            else:
                self.topic = rpc.NETWORKING_TOPIC

        serializer = objects_base.IronicObjectSerializer()
        release_ver = versions.RELEASE_MAPPING.get(CONF.pin_release_version)
        version_cap = (
            release_ver.get("networking_rpc")
            if release_ver else self.RPC_API_VERSION
        )

        if networking_utils.rpc_transport() == "json-rpc":
            # Use a dedicated configuration group for networking JSON-RPC
            self.client = json_rpc.Client(
                serializer=serializer,
                version_cap=version_cap,
                conf_group="ironic_networking_json_rpc",
            )
            # Keep the original topic for JSON-RPC (needed for host extraction)
        elif networking_utils.rpc_transport() != "none":
            target = messaging.Target(topic=self.topic, version="1.0")
            self.client = rpc.get_client(
                target, version_cap=version_cap, serializer=serializer
            )
        else:
            self.client = None

    def _prepare_call(self, topic, version=None):
        """Prepare an RPC call.

        :param topic: RPC topic to send to.
        :param version: RPC API version to require.
        """
        topic = topic or self.topic

        # A safeguard for the case someone uses rpc_transport=None
        if self.client is None:
            raise exception.ServiceUnavailable(
                _("Cannot use 'none' RPC to connect to networking service")
            )

        # Normal RPC path
        return self.client.prepare(topic=topic, version=version)

    def get_topic(self):
        """Get RPC topic name for the networking service."""
        return self.topic

    def update_port(
        self,
        context,
        switch_id,
        port_name,
        description,
        mode,
        native_vlan,
        allowed_vlans=None,
        default_vlan=None,
        lag_name=None,
        topic=None,
    ):
        """Update a port configuration on a switch.

        :param context: request context.
        :param switch_id: Identifier for the switch.
        :param port_name: Name of the port on the switch.
        :param description: Description to set for the port.
        :param mode: Port mode ('access', 'trunk', or 'hybrid').
        :param native_vlan: VLAN ID to be set on the port.
        :param allowed_vlans: List of allowed VLAN IDs to be added(optional).
        :param default_vlan: VLAN ID to removed from the port(optional).
        :param lag_name: LAG name if port is part of a link aggregation group.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary containing the updated port configuration.
        """
        cctxt = self._prepare_call(topic=topic, version="1.0")
        return cctxt.call(
            context,
            "update_port",
            switch_id=switch_id,
            port_name=port_name,
            description=description,
            mode=mode,
            native_vlan=native_vlan,
            allowed_vlans=allowed_vlans,
            lag_name=lag_name,
            default_vlan=default_vlan,
        )

    def reset_port(
        self,
        context,
        switch_id,
        port_name,
        native_vlan,
        allowed_vlans=None,
        default_vlan=None,
        topic=None,
    ):
        """Reset a network switch port to default configuration.

        :param context: request context.
        :param switch_id: Identifier for the switch.
        :param port_name: Name of the port on the switch.
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: List of allowed VLAN IDs to be removed(optional).
        :param default_vlan: VLAN ID to restore onto the port(optional).
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary containing the reset port configuration.
        """
        cctxt = self._prepare_call(topic=topic, version="1.0")
        return cctxt.call(
            context,
            "reset_port",
            switch_id=switch_id,
            port_name=port_name,
            native_vlan=native_vlan,
            allowed_vlans=allowed_vlans,
            default_vlan=default_vlan,
        )

    def get_switches(self, context, topic=None):
        """Get information about all configured switches.

        :param context: request context.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary with switch_id as key and switch_info as value.
        """
        cctxt = self._prepare_call(topic=topic, version="1.0")
        return cctxt.call(context, "get_switches")

    def update_lag(
        self,
        context,
        switch_ids,
        lag_name,
        description,
        mode,
        native_vlan,
        aggregation_mode,
        allowed_vlans=None,
        default_vlan=None,
        topic=None,
    ):
        """Update a link aggregation group (LAG) configuration.

        :param context: request context.
        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG.
        :param description: Description for the LAG.
        :param mode: LAG mode ('access' or 'trunk').
        :param native_vlan: VLAN ID to be set for the LAG.
        :param aggregation_mode: Aggregation mode (e.g., 'lacp', 'static').
        :param allowed_vlans: List of allowed VLAN IDs to be added (optional).
        :param default_vlan: VLAN ID to removed from the port(optional).
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary containing the updated LAG configuration.
        """
        cctxt = self._prepare_call(topic=topic, version="1.0")
        return cctxt.call(
            context,
            "update_lag",
            switch_ids=switch_ids,
            lag_name=lag_name,
            description=description,
            mode=mode,
            native_vlan=native_vlan,
            aggregation_mode=aggregation_mode,
            allowed_vlans=allowed_vlans,
            default_vlan=default_vlan,
        )

    def delete_lag(
        self, context, switch_ids, lag_name, topic=None
    ):
        """Delete a link aggregation group (LAG) configuration.

        :param context: request context.
        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to delete.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary containing the deletion status.
        """
        cctxt = self._prepare_call(topic=topic, version="1.0")
        return cctxt.call(
            context,
            "delete_lag",
            switch_ids=switch_ids,
            lag_name=lag_name,
        )
