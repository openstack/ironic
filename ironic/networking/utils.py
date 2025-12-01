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
Utilities for networking service operations.
"""

from oslo_config import cfg
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _

LOG = log.getLogger(__name__)
CONF = cfg.CONF


def rpc_transport():
    """Get the RPC transport type."""
    if CONF.ironic_networking.rpc_transport is None:
        return CONF.rpc_transport
    else:
        return CONF.ironic_networking.rpc_transport


def parse_vlan_ranges(vlan_spec):
    """Parse VLAN specification into a set of VLAN IDs.

    :param vlan_spec: List of VLAN IDs or ranges (e.g., ['100', '102-104'])
    :returns: Set of integer VLAN IDs
    :raises: InvalidParameterValue if the specification is invalid
    """
    if vlan_spec is None:
        return None

    vlan_set = set()
    for item in vlan_spec:
        item = item.strip()
        if '-' in item:
            # Handle range (e.g., "102-104")
            try:
                start, end = item.split('-', 1)
                start_vlan = int(start.strip())
                end_vlan = int(end.strip())
                if start_vlan < 1 or end_vlan > 4094:
                    raise exception.InvalidParameterValue(
                        _('VLAN IDs must be between 1 and 4094, got range '
                          '%(start)s-%(end)s') % {'start': start_vlan,
                                                  'end': end_vlan})
                if start_vlan > end_vlan:
                    raise exception.InvalidParameterValue(
                        _('Invalid VLAN range %(start)s-%(end)s: start must '
                          'be less than or equal to end') %
                        {'start': start_vlan, 'end': end_vlan})
                vlan_set.update(range(start_vlan, end_vlan + 1))
            except (ValueError, AttributeError) as e:
                raise exception.InvalidParameterValue(
                    _('Invalid VLAN range format "%(item)s": %(error)s') %
                    {'item': item, 'error': str(e)})
        else:
            # Handle single VLAN ID
            try:
                vlan_id = int(item)
                if vlan_id < 1 or vlan_id > 4094:
                    raise exception.InvalidParameterValue(
                        _('VLAN ID must be between 1 and 4094, got %s') %
                        vlan_id)
                vlan_set.add(vlan_id)
            except ValueError as e:
                raise exception.InvalidParameterValue(
                    _('Invalid VLAN ID "%(item)s": %(error)s') %
                    {'item': item, 'error': str(e)})

    return vlan_set


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
    if isinstance(allowed_spec, list) and len(allowed_spec) == 0:
        raise exception.InvalidParameterValue(
            _('VLAN %(vlan)s is not allowed: no VLANs are permitted by '
              'configuration') % {'vlan': vlan_id})

    # Parse and check against allowed VLANs
    try:
        allowed_vlans = parse_vlan_ranges(allowed_spec)
        if vlan_id not in allowed_vlans:
            raise exception.InvalidParameterValue(
                _('VLAN %(vlan)s is not in the list of allowed VLANs') %
                {'vlan': vlan_id})
    except exception.InvalidParameterValue:
        # Re-raise validation errors from parse_vlan_ranges
        raise

    return True
