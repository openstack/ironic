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

    :param vlan_spec: List of VLAN IDs or ranges (e.g., ['100', '102-104']) or
        a string representing a list of VLAN IDs (e.g., '100,102-104').
    :returns: Set of integer VLAN IDs
    :raises: InvalidParameterValue if the specification is invalid
    """
    if vlan_spec is None:
        return None

    if isinstance(vlan_spec, str):
        vlan_spec = vlan_spec.split(',')

    vlan_set = set()
    for item in vlan_spec:
        item = item.strip()
        if not item:
            # Skip empty elements (e.g., from "100,,200" or trailing commas)
            continue
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
