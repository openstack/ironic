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

"""Networking service manager for Ironic.

The networking service handles network-related operations for Ironic,
providing RPC interfaces for configuring switch ports and network settings.
"""

from oslo_log import log
import oslo_messaging as messaging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import metrics_utils
from ironic.common import rpc
from ironic.conf import CONF

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class NetworkingManager(object):
    """Ironic Networking service manager."""

    # NOTE(alegacy): This must be in sync with rpcapi.NetworkingAPI's.
    RPC_API_VERSION = "1.0"

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, host, topic=None):
        if not host:
            host = CONF.host
        self.host = host
        if topic is None:
            topic = rpc.NETWORKING_TOPIC
        self.topic = topic

        # Tell the RPC service which json-rpc config group to use for
        # networking. This enables separate listener configuration.
        self.json_rpc_conf_group = "ironic_networking_json_rpc"

    def prepare_host(self):
        """Prepare host for networking service initialization.

        This method is called by the RPC service before starting the listener.
        """
        pass

    def init_host(self, admin_context=None):
        """Initialize the networking service host.

        :param admin_context: admin context (unused but kept for compatibility)
        """
        LOG.info("Initializing networking service on host %s", self.host)
        LOG.warning(
            "Networking service initialized with stub implementations. "
            "Driver framework not yet loaded."
        )

    @METRICS.timer("NetworkingManager.update_port")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
    )
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
    ):
        """Update a network switch port configuration (stub).

        :param context: request context.
        :param switch_id: Identifier of the network switch.
        :param port_name: Name of the port to update.
        :param description: Description for the port.
        :param mode: Port mode (e.g., 'access', 'trunk').
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :param lag_name: Name of the LAG if port is part of a link aggregation
                         group (optional).
        :raises: NotImplementedError - Implementation not loaded
        """
        LOG.warning(
            "update_port called but driver framework not loaded: "
            "switch=%s, port=%s",
            switch_id,
            port_name,
        )
        raise exception.NetworkError(
            _("Network driver framework not yet loaded")
        )

    @METRICS.timer("NetworkingManager.reset_port")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
    )
    def reset_port(
        self,
        context,
        switch_id,
        port_name,
        native_vlan,
        allowed_vlans=None,
        default_vlan=None,
    ):
        """Reset a network switch port to default configuration (stub).

        :param context: request context.
        :param switch_id: Identifier of the network switch.
        :param port_name: Name of the port to reset.
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :raises: NotImplementedError - Implementation not loaded
        """
        LOG.warning(
            "reset_port called but driver framework not loaded: "
            "switch=%s, port=%s",
            switch_id,
            port_name,
        )
        raise exception.NetworkError(
            _("Network driver framework not yet loaded")
        )

    @METRICS.timer("NetworkingManager.update_lag")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
        exception.Invalid,
    )
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
    ):
        """Update a link aggregation group (LAG) configuration (stub).

        :param context: request context.
        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to update.
        :param description: Description for the LAG.
        :param mode: LAG mode (e.g., 'access', 'trunk').
        :param native_vlan: VLAN ID to be removed from the port.
        :param aggregation_mode: Aggregation mode (e.g., 'lacp', 'static').
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :raises: Invalid - LAG operations are not yet supported.
        """
        raise exception.Invalid(
            _("LAG operations are not yet supported")
        )

    @METRICS.timer("NetworkingManager.delete_lag")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
        exception.Invalid,
    )
    def delete_lag(self, context, switch_ids, lag_name):
        """Delete a link aggregation group (LAG) configuration (stub).

        :param context: request context.
        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to delete.
        :raises: Invalid - LAG operations are not yet supported.
        """
        raise exception.Invalid(
            _("LAG operations are not yet supported")
        )

    @METRICS.timer("NetworkingManager.get_switches")
    @messaging.expected_exceptions(exception.NetworkError)
    def get_switches(self, context):
        """Get information about all switches (stub).

        :param context: Request context
        :returns: Empty dictionary (no drivers loaded)
        """
        LOG.warning("get_switches called but driver framework not loaded")
        return {}

    def cleanup(self):
        """Clean up resources."""
        pass
