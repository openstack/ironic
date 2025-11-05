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
Utilities for switch configuration and VLAN management.
"""

from oslo_config import cfg
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.networking import utils

LOG = log.getLogger(__name__)
CONF = cfg.CONF


def validate_vlan_allowed(vlan_id, allowed_vlans_config=None,
                          switch_config=None):
    """Validate that a VLAN ID is allowed.

    :param vlan_id: The VLAN ID to validate
    :param allowed_vlans_config: Global list of allowed vlans from config
    :param switch_config: Optional switch-specific configuration dict that
                          may contain an 'allowed_vlans' key
    :returns: True if the VLAN is allowed
    :raises: InvalidParameterValue if the VLAN is not allowed
    """
    # Check switch-specific configuration first (if provided)
    if switch_config and 'allowed_vlans' in switch_config:
        allowed_spec = switch_config['allowed_vlans']
    else:
        # Fall back to global configuration
        if allowed_vlans_config is not None:
            allowed_spec = allowed_vlans_config
        else:
            allowed_spec = CONF.ironic_networking.allowed_vlans

    # None means all VLANs are allowed
    if allowed_spec is None:
        return True

    # Empty list means no VLANs are allowed
    if isinstance(allowed_spec, list) and not allowed_spec:
        raise exception.InvalidParameterValue(
            _('VLAN %(vlan)s is not allowed: no VLANs are permitted by '
              'configuration') % {'vlan': vlan_id})

    # Parse and check against allowed VLANs
    allowed_vlans = utils.parse_vlan_ranges(allowed_spec)
    if vlan_id not in allowed_vlans:
        raise exception.InvalidParameterValue(
            _('VLAN %(vlan)s is not in the list of allowed VLANs') %
            {'vlan': vlan_id})

    return True


def get_switch_vlan_config(switch_driver, switch_id):
    """Get VLAN configuration for a switch.

    Retrieves switch-specific VLAN configuration from the driver, with
    fallback to global configuration options.

    :param switch_driver: The switch driver instance.
    :param switch_id: Identifier of the switch.
    :returns: Dictionary containing allowed_vlans
    :raises: Any exceptions from switch_driver.get_switch_info()
    """
    config = {
        "allowed_vlans": set(),
    }

    # Get switch-specific configuration from driver
    switch_info = switch_driver.get_switch_info(switch_id)
    # Process switch-specific allowed_vlans
    if switch_info and "allowed_vlans" in switch_info:
        switch_allowed = switch_info["allowed_vlans"]
        config["allowed_vlans"] = (
            utils.parse_vlan_ranges(switch_allowed))

    # Use global config if switch-specific config is not available
    if not config["allowed_vlans"] and CONF.ironic_networking.allowed_vlans:
        config["allowed_vlans"] = utils.parse_vlan_ranges(
            CONF.ironic_networking.allowed_vlans
        )

    return config


def validate_vlan_configuration(
    vlans_to_check, switch_driver, switch_id, operation_description="operation"
):
    """Validate VLAN configuration against allowed lists.

    Checks if the specified VLANs are allowed according to the switch-specific
    or global configuration.

    :param vlans_to_check: List of VLAN IDs to validate.
    :param switch_driver: The switch driver instance.
    :param switch_id: Identifier of the switch.
    :param operation_description: Description of the operation for error
                                 messages.
    :raises: InvalidParameterValue if any VLAN is not allowed.
    """
    if not vlans_to_check:
        return

    # Get switch-specific configuration
    config = get_switch_vlan_config(switch_driver, switch_id)
    allowed_vlans = config["allowed_vlans"]

    # Convert to set for easier processing
    vlans_set = set(vlans_to_check)

    # Check allowed VLANs if specified
    if allowed_vlans:
        disallowed_requested = vlans_set - allowed_vlans
        if disallowed_requested:
            raise exception.InvalidParameterValue(
                _("VLANs %(vlans)s are not allowed for %(operation)s on "
                  "switch %(switch)s. Allowed VLANs: %(allowed)s"
                  ) % {
                    "vlans": sorted(disallowed_requested),
                    "operation": operation_description,
                    "switch": switch_id,
                    "allowed": sorted(allowed_vlans),
                }
            )
