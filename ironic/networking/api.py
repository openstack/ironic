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
Networking API for other parts of Ironic to use.
"""

from ironic.networking import rpcapi

# Global networking API instance
_NETWORKING_API = None


def get_networking_api():
    """Get the networking API instance.

    :returns: NetworkingAPI instance
    """
    global _NETWORKING_API
    if _NETWORKING_API is None:
        _NETWORKING_API = rpcapi.NetworkingAPI()
    return _NETWORKING_API


def update_port(
    context,
    switch_id,
    port_name,
    description,
    mode,
    native_vlan,
    allowed_vlans=None,
    lag_name=None,
    default_vlan=None
):
    """Update a network switch port configuration.

    This is a convenience function that other parts of Ironic can use
    to update network switch port configurations.

    :param context: request context.
    :param switch_id: Identifier for the switch.
    :param port_name: Name of the port on the switch.
    :param description: Description to set for the port.
    :param mode: Port mode ('access', 'trunk', or 'hybrid').
    :param native_vlan: VLAN ID to be set on the port.
    :param allowed_vlans: List of allowed VLAN IDs to be added(optional).
    :param default_vlan: VLAN ID to removed from the port(optional).
    :param lag_name: LAG name if port is part of a link aggregation group.
    :raises: InvalidParameterValue if validation fails.
    :raises: NetworkError if the network operation fails.
    :returns: Dictionary containing the updated port configuration.
    """
    api = get_networking_api()
    return api.update_port(
        context,
        switch_id,
        port_name,
        description,
        mode,
        native_vlan,
        allowed_vlans=allowed_vlans,
        lag_name=lag_name,
        default_vlan=default_vlan
    )


def reset_port(
    context,
    switch_id,
    port_name,
    native_vlan=None,
    allowed_vlans=None,
    default_vlan=None,
):
    """Reset a network switch port to default configuration.

    This is a convenience function that other parts of Ironic can use
    to reset network switch ports to their default configurations.

    :param context: request context.
    :param switch_id: Identifier for the switch.
    :param port_name: Name of the port on the switch.
    :param native_vlan: VLAN ID to be removed from the port.
    :param allowed_vlans: List of allowed VLAN IDs to be removed(optional).
    :param default_vlan: VLAN ID to restore onto the port(optional).
    :raises: InvalidParameterValue if validation fails.
    :raises: NetworkError if the network operation fails.
    :returns: Dictionary containing the reset port configuration.
    """
    api = get_networking_api()
    return api.reset_port(
        context,
        switch_id,
        port_name,
        native_vlan,
        allowed_vlans=allowed_vlans,
        default_vlan=default_vlan
    )


def update_lag(
    context,
    switch_ids,
    lag_name,
    description,
    mode,
    native_vlan,
    aggregation_mode,
    allowed_vlans=None,
    default_vlan=None
):
    """Update a link aggregation group (LAG) configuration.

    This is a convenience function that other parts of Ironic can use
    to update LAG configurations.

    :param context: request context.
    :param switch_ids: List of switch identifiers.
    :param lag_name: Name of the LAG.
    :param description: Description for the LAG.
    :param mode: LAG mode ('access' or 'trunk').
    :param native_vlan: VLAN ID to be set for the LAG.
    :param aggregation_mode: Aggregation mode (e.g., 'lacp', 'static').
    :param allowed_vlans: List of allowed VLAN IDs to be added (optional).
    :param default_vlan: VLAN ID to removed from the port(optional).
    :raises: InvalidParameterValue if validation fails.
    :raises: NetworkError if the network operation fails.
    :returns: Dictionary containing the updated LAG configuration.
    """
    api = get_networking_api()
    return api.update_lag(
        context,
        switch_ids,
        lag_name,
        description,
        mode,
        native_vlan,
        aggregation_mode,
        allowed_vlans=allowed_vlans,
        default_vlan=default_vlan
    )


def delete_lag(context, switch_ids, lag_name):
    """Delete a link aggregation group (LAG) configuration.

    This is a convenience function that other parts of Ironic can use
    to delete LAG configurations.

    :param context: request context.
    :param switch_ids: List of switch identifiers.
    :param lag_name: Name of the LAG to delete.
    :raises: InvalidParameterValue if validation fails.
    :raises: NetworkError if the network operation fails.
    :returns: Dictionary containing the deletion status.
    """
    api = get_networking_api()
    return api.delete_lag(context, switch_ids, lag_name)
