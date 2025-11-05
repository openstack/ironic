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

from ironic.drivers.modules.switch.base import BaseTranslator
from ironic.drivers.modules.switch.base import SwitchDriverBase
from ironic.drivers.modules.switch.base import SwitchDriverException
from ironic.drivers.modules.switch.base import SwitchNotFound
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.networking.utils import parse_vlan_ranges

devices = importutils.try_import('networking_generic_switch.devices')
device_utils = importutils.try_import(
    'networking_generic_switch.devices.utils')

VALID_PORT_MODES = ['access', 'trunk', 'hybrid']
VALID_TRUNK_MODES = ['trunk', 'hybrid']

LOG = logging.getLogger(__name__)


class GenericSwitchDriver(SwitchDriverBase):
    """Generic Switch Standalone Driver implementation.

    This driver provides a switch driver implementation that is decoupled from
    the Neutron ML2 interface.  It provides the same access to the underlying
    generic switch device interface but with a non-Neutron specific API
    interface.  It is intended to be used as a driver within Ironic's
    Standalone Networking Service.
    """
    DRIVER_NAME = 'generic-switch'
    DRIVER_VERSION = '1.0'
    SUPPORTED = True

    _devices = []

    def __init__(self, *args, **kwargs):
        """Perform driver initialization.

        Initialize the driver and load all configured switch devices
        using the same devices module as GenericSwitchDriver.
        """
        super(GenericSwitchDriver, self).__init__()
        if devices is None:
            # Import failed, handle gracefully
            raise ImportError("networking_generic_switch not imported")

        self._devices = devices.get_devices()

        if self._devices:
            LOG.info('Devices have been loaded: %s',
                     list(self._devices.keys()))
        else:
            LOG.warning('No devices have been loaded')

    @classmethod
    def get_translator(cls):
        return GenericSwitchTranslator()

    @staticmethod
    def _get_trunk_details(native_vlan, allowed_vlans):
        """Convert allowed_vlans to sub_ports format expected by devices."""
        sub_ports = []
        for vlan in allowed_vlans or []:
            if vlan != native_vlan:
                # Don't include default VLAN in sub_ports
                sub_ports.append({'segmentation_id': vlan})
        if len(sub_ports) > 0:
            return {'sub_ports': sub_ports}
        return None

    @staticmethod
    def _validate_switch_id(switch_id):
        """Validate switch ID parameter.

        :param switch_id: Switch identifier to validate
        :raises: ValueError if switch_id is invalid
        """
        if not switch_id or not isinstance(switch_id, str):
            raise ValueError("switch_id must be a non-empty string")
        if switch_id.isspace():
            raise ValueError("switch_id cannot be only whitespace")

    @staticmethod
    def _validate_port_name(port_name):
        """Validate port ID parameter.

        :param port_name: Port name to validate
        :raises: ValueError if port_id is invalid
        """
        if not port_name or not isinstance(port_name, str):
            raise ValueError("port_name must be a non-empty string")
        if port_name.isspace():
            raise ValueError("port_name cannot be only whitespace")

    def _get_switch(self, switch_id):
        """Lookup a switch device by ID.

        :param switch_id: MAC address or hostname of the switch
        :returns: Switch device object
        :raises: SwitchNotFound if switch is not found
        :raises: ValueError if switch_id is invalid
        """
        self._validate_switch_id(switch_id)

        switch = device_utils.get_switch_device(
            self._devices, switch_info=switch_id,
            ngs_mac_address=switch_id)

        if not switch:
            raise SwitchNotFound(switch_id)
        return switch

    @staticmethod
    def _validate_port_mode(mode, allowed_vlans):
        """Validate port mode and required parameters.

        :param mode: Port mode to validate
        :param allowed_vlans: List of allowed VLANs
        :raises: ValueError if mode is invalid or required parameters missing
        """
        if mode not in VALID_PORT_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of: {VALID_PORT_MODES}")

        if mode in VALID_TRUNK_MODES:
            if len(allowed_vlans or []) == 0:
                raise ValueError(
                    f"allowed_vlans parameter cannot be empty or missing "
                    f"when mode is '{mode}'")

    @staticmethod
    def _validate_trunk_support(switch, switch_id, mode):
        """Validate that switch supports trunk operations if needed.

        :param switch: Switch device object
        :param switch_id: Switch identifier for error messages
        :param mode: Port mode
        :raises: SwitchDriverException if trunk mode requested but not
          supported
        """
        if mode in VALID_TRUNK_MODES:
            if not switch.support_trunk_on_ports:
                raise SwitchDriverException(
                    f"Switch {switch_id} does not support trunk ports")

    def update_port(self, switch_id, port_name, description, mode, native_vlan,
                    allowed_vlans=None, default_vlan=None,
                    lag_name=None, **kwargs):
        """Update a port configuration on a switch.

        :param switch_id: Identifier for the switch.
        :param port_name: Name of the port on the switch.
        :param description: Description to set for the port.
        :param mode: Port mode ('access', 'trunk', or 'hybrid').
        :param native_vlan: VLAN ID to be set on the port.
        :param allowed_vlans: List of allowed VLAN IDs to be added(optional).
        :param default_vlan: VLAN ID to removed from the port(optional).
        :param lag_name: LAG name if port is part of a LAG.
        :raises: ValueError on parameter validation errors.
        :raises: SwitchNotFound if the specified switch does not exist.
        :raises: SwitchDriverException on configuration failures.
        """
        # Validate parameters
        self._validate_port_name(port_name)
        self._validate_port_mode(mode, allowed_vlans)

        # Lookup the switch device
        switch = self._get_switch(switch_id)

        # Validate switch capabilities
        self._validate_trunk_support(switch, switch_id, mode)

        LOG.info("Updating port %(port_id)s on "
                 "switch %(switch_id)s with mode %(mode)s, "
                 "native_vlan %(native_vlan)s, "
                 "description '%(description)s', "
                 "allowed_vlans %(allowed_vlans)s, "
                 "default_vlan %(default_vlan)s, ",
                 {'port_id': port_name, 'switch_id': switch_id, 'mode': mode,
                  'native_vlan': native_vlan, 'description': description,
                  'allowed_vlans': allowed_vlans,
                  'default_vlan': default_vlan})

        try:
            # Prepare trunk details for non-access modes
            trunk_details = None
            if mode in VALID_TRUNK_MODES:
                trunk_details = (
                    self._get_trunk_details(native_vlan, allowed_vlans))

            # Configure the port
            switch.plug_port_to_network(
                port_name, native_vlan,
                trunk_details=trunk_details,
                default_vlan=default_vlan)

        except Exception as e:
            LOG.error("Failed to update port "
                      "%(port_id)s on switch %(switch_id)s: %(exc)s",
                      {'port_id': port_name, 'switch_id': switch_id, 'exc': e})
            raise SwitchDriverException(message=str(e))

    def reset_port(self, switch_id, port_name,
                   native_vlan=None, allowed_vlans=None, default_vlan=None):
        """Reset a port configuration on a switch.

        :param switch_id: Identifier for the switch.
        :param port_name: Name of the port on the switch.
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: List of allowed VLAN IDs to be removed(optional).
        :param default_vlan: VLAN ID to restore onto the port(optional).
        :raises: ValueError on parameter validation errors.
        :raises: SwitchNotFound if the specified switch does not exist.
        :raises: SwitchDriverException on configuration failures.
        """
        switch = self._get_switch(switch_id)

        LOG.info("Resetting port %(port_id)s on "
                 "switch %(switch_id)s, removing "
                 "native_vlan %(native_vlan)s, setting "
                 "default_vlan %(default_vlan)s",
                 {'port_id': port_name, 'switch_id': switch_id,
                  'native_vlan': native_vlan,
                  'default_vlan': default_vlan})

        try:
            trunk_details = (
                self._get_trunk_details(native_vlan, allowed_vlans))
            switch.delete_port(port_name, native_vlan,
                               trunk_details=trunk_details,
                               default_vlan=default_vlan)
        except Exception as e:
            LOG.error("Failed to reset port "
                      "%(port_id)s on switch %(switch_id)s: %(exc)s",
                      {'port_id': port_name, 'switch_id': switch_id, 'exc': e})
            raise SwitchDriverException(message=str(e))

    def get_switch_info(self, switch_id):
        """Get information about a switch.

        :param switch_id: MAC address or hostname of the switch
        :returns: Dictionary containing switch information
        :raises: SwitchNotFound if switch is not found
        """
        switch = self._get_switch(switch_id)

        return {
            'switch_id': switch_id,
            'device_name': getattr(switch, 'device_name', switch_id),
            'device_type': switch.config.get('device_type', 'unknown'),
            'allowed_vlans': switch.ngs_config.get('ngs_allowed_vlans', None),
        }

    def is_switch_configured(self, switch_id):
        """Check if this driver is configured to manage the specified switch.

        This method should return True if this driver is configured to handle
        the specified switch. This is used by the driver selection logic to
        determine which driver should handle a specific switch.

        :param switch_id: Identifier for the switch to check.
        :returns: True if this driver can manage the specified switch,
                  False otherwise.
        """
        try:
            switch = self._get_switch(switch_id)
        except SwitchNotFound:
            return False

        # Check for essential configuration parameters
        config = getattr(switch, 'config', {})
        device_type = config.get('device_type')

        if not device_type:
            LOG.warning("Switch %s missing device_type configuration",
                        switch_id)
            return False

        # Check if switch has connectivity information
        host_info = config.get('ip') or config.get('host')
        if not host_info:
            LOG.warning("Switch %s missing connection information",
                        switch_id)
            return False

        return True

    def get_switch_ids(self):
        """Get a list of all switch IDs.

        :returns: List of switch IDs
        """
        switch_ids = [switch_id for switch_id, _ in self._devices.items()]
        return switch_ids

    def update_lag(
        self,
        switch_ids,
        lag_name,
        description,
        mode,
        native_vlan,
        aggregation_mode,
        allowed_vlans=None,
        default_vlan=None,
    ):
        """Update LAG configuration across switches.

        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG.
        :param description: Description for the LAG.
        :param mode: switchport mode ('access' or 'trunk').
        :param native_vlan: VLAN ID to be set for the LAG.
        :param aggregation_mode: Aggregation mode (e.g., 'lacp', 'static').
        :param allowed_vlans: List of allowed VLAN IDs to be added (optional).
        :param default_vlan: VLAN ID to removed from the port(optional).
        :raises: ValueError on parameter validation errors.
        :raises: SwitchNotFound if the specified switch does not exist.
        :raises: SwitchDriverException on configuration failures.
        """
        # Generic switch driver doesn't directly support LAGs
        # This could be extended in the future or by subclasses
        raise SwitchDriverException(
            "LAG operations not supported by generic switch driver")

    def delete_lag(self, switch_ids, lag_name):
        """Delete LAG configuration from switches.

        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to delete.
        :raises: ValueError on parameter validation errors.
        :raises: SwitchNotFound if the specified switch does not exist.
        :raises: SwitchDriverException on configuration failures.
        """
        # Generic switch driver doesn't directly support LAGs
        # This could be extended in the future or by subclasses
        raise SwitchDriverException(
            "LAG operations not supported by generic switch driver")


class GenericSwitchTranslator(BaseTranslator):
    """Translates generic config to networking-generic-switch format."""

    def _get_section_name(self, switch_name):
        """Generate section name for networking-generic-switch driver."""
        return f"genericswitch:{switch_name}"

    def _translate_allowed_vlans(self, allowed_vlans):
        """Translate allowed_vlans from Ironic format to NGS format.

        Ironic supports ranges like "100,102-104,106" or ['100', '102-104'].
        networking-generic-switch expects comma-separated individual VLANs
        like "100,102,103,104,106".

        :param allowed_vlans: String or list of VLAN IDs/ranges
        :returns: Comma-separated string of individual VLAN IDs
        """
        # Parse the input (handles both string and list, expands ranges)
        vlan_set = parse_vlan_ranges(allowed_vlans)

        # Handle None (all VLANs allowed) - NGS uses None for this
        if vlan_set is None:
            return None

        # Handle empty set (no VLANs allowed) - NGS uses empty string
        if not vlan_set:
            return ""

        # Convert set to sorted list and join with commas
        vlan_list = sorted(vlan_set)
        return ",".join(str(vlan) for vlan in vlan_list)

    def _translate_switch_config(self, config):
        """Translate from user format to networking-generic-switch format."""
        # networking-generic-switch expects these fields
        translation_map = {
            # Generic field -> driver field
            "address": "ip",
            "device_type": "device_type",
            "username": "username",
            "password": "password",
            "key_file": "key_file",
            "enable_secret": "secret",
            "port": "port",
            "mac_address": "ngs_mac_address",
            "native_vlan": "ngs_port_native_vlan",
            "persist": "ngs_save_configuration",
            "allowed_vlans": "ngs_allowed_vlans",
        }

        # Translate fields
        driver_config = {}
        for user_key, driver_key in translation_map.items():
            if user_key in config and user_key not in [
                "driver_type",
                "allowed_vlans",
            ]:
                driver_config[driver_key] = config[user_key]

        if "allowed_vlans" in config:
            driver_config["ngs_allowed_vlans"] = (
                self._translate_allowed_vlans(config["allowed_vlans"]))

        if "persist" not in config:
            # If the user does not specify a value for persist, set it to False
            # by default since the driver itself will default to True
            driver_config["ngs_save_configuration"] = False

        return driver_config
