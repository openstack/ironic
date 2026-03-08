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

"""SwitchPortConfig - parsed representation of switchport configuration.

This module provides a dataclass for representing and parsing the switchport
configuration format used by the Ironic Networking interface:

    {access|trunk|hybrid}/native_vlan=VLAN_ID[/allowed_vlans=V1,V2,Vn-Vm,...]
"""

import dataclasses
from typing import Optional

from ironic.common import exception
from ironic.common.i18n import _
from ironic.networking import utils as net_utils

VALID_MODES = ('access', 'trunk', 'hybrid')


@dataclasses.dataclass(frozen=True)
class SwitchPortConfig:
    """Parsed representation of a switchport configuration value.

    Instances can be created from a configuration string via
    :meth:`from_string` or from a switchport dict via
    :meth:`from_switchport`.
    """

    mode: str
    native_vlan: Optional[int] = None
    allowed_vlans: Optional[list] = None

    @classmethod
    def from_string(cls, value, network_type='unknown'):
        """Parse a network config string into a SwitchPortConfig.

        :param value: String in format
            ``{access|trunk|hybrid}/native_vlan=N[/allowed_vlans=V1,V2,Vn-Vm]``
        :param network_type: Network type label used in error messages.
        :returns: A SwitchPortConfig instance.
        :raises: InvalidParameterValue if the format is invalid.
        """
        try:
            parts = value.split('/')
            mode = parts[0].strip()
            if not mode:
                raise ValueError("mode is empty")
            if mode not in VALID_MODES:
                raise ValueError(
                    f"mode must be one of {VALID_MODES}, "
                    f"got '{mode}'")
            if len(parts) < 2:
                raise ValueError(
                    "expected at least mode/native_vlan=N")
            native_vlan = None
            allowed_vlans = None
            for part in parts[1:]:
                key, sep, val = part.partition('=')
                if not sep:
                    raise ValueError(
                        f"expected key=value, got '{part}'")
                key = key.strip()
                val = val.strip()
                if key == 'native_vlan':
                    native_vlan = int(val)
                elif key == 'allowed_vlans':
                    allowed_vlans = cls._parse_allowed_vlans(
                        val)
        except (ValueError, IndexError) as e:
            raise exception.InvalidParameterValue(
                _("Invalid %(network_type)s network value '%(value)s'. "
                  "Expected: {access|trunk|hybrid}/native_vlan=VLAN_ID"
                  "[/allowed_vlans=V1,V2,Vn-Vm,...]. "
                  "Error: %(error)s")
                % {'network_type': network_type, 'value': value,
                   'error': e})
        return cls(mode=mode, native_vlan=native_vlan,
                   allowed_vlans=allowed_vlans)

    @staticmethod
    def _parse_allowed_vlans(val):
        """Parse the allowed_vlans value string.

        Each element may be a single VLAN ID (``"100"``) or a range
        (``"100-200"``).  Ranges are expanded into individual VLAN IDs
        using :func:`ironic.networking.utils.parse_vlan_ranges`.

        :param val: Comma-separated string, e.g. ``"1,2,4-7,9"``.
        :returns: Sorted list of integer VLAN IDs.
        :raises: InvalidParameterValue if any element is not a valid
            VLAN ID or range.
        """
        vlan_set = net_utils.parse_vlan_ranges(val)
        return sorted(vlan_set)

    @classmethod
    def from_switchport(cls, switchport):
        """Create a SwitchPortConfig from a switchport configuration dict.

        :param switchport: A dict with optional keys ``mode``,
            ``native_vlan``, and ``allowed_vlans``.
        :returns: A SwitchPortConfig instance, or None if the dict does
            not contain a ``mode`` key.
        :raises: InvalidParameterValue if ``mode`` is not a valid mode
            or ``native_vlan`` is not an integer.
        """
        mode = switchport.get('mode')
        if not mode:
            return None
        if mode not in VALID_MODES:
            raise exception.InvalidParameterValue(
                _("Invalid switchport mode '%(mode)s'. "
                  "Must be one of %(valid)s.")
                % {'mode': mode, 'valid': VALID_MODES})
        native_vlan = switchport.get('native_vlan')
        if native_vlan is not None and not isinstance(
                native_vlan, int):
            raise exception.InvalidParameterValue(
                _("native_vlan must be an integer, "
                  "got %(type)s.")
                % {'type': type(native_vlan).__name__})
        return cls(
            mode=mode,
            native_vlan=native_vlan,
            allowed_vlans=switchport.get('allowed_vlans'),
        )

    @property
    def is_valid(self):
        """True if the config has the required fields for its mode.

        For ``access`` mode, ``native_vlan`` must be set.
        For ``trunk`` or ``hybrid`` mode, ``allowed_vlans`` must be set.
        """
        if not self.mode:
            return False
        if self.mode == 'access':
            return self.native_vlan is not None
        # trunk / hybrid
        return self.allowed_vlans is not None
