# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Base classes for networking service switch drivers.

This module defines the base interface that all switch drivers must implement
to provide vendor-specific network switch management functionality.
"""

import abc

from oslo_log import log

from ironic.common.exception import IronicException
from ironic.common.i18n import _

LOG = log.getLogger(__name__)


class SwitchDriverException(IronicException):
    _msg_fmt = _("A switch configuration exception occurred.")


class SwitchNotFound(SwitchDriverException):
    _msg_fmt = _("Switch %(switch_id)s not present in configuration.")


class SwitchMethodNotImplemented(SwitchDriverException):
    _msg_fmt = _("Method %(method)s not implemented for "
                 "driver %(DRIVER_NAME).")


class BaseTranslator:
    """Base class for configuration translators."""

    def translate_configs(self, switch_configs):
        """Translate all switch configurations.

        :param switch_configs: Dictionary of switch_name -> config_dict
        :returns: Dictionary of section_name -> translated_config_dict
        """
        translated = {}

        for switch_name, config in switch_configs.items():
            translated.update(self.translate_config(switch_name, config))

        return translated

    def translate_config(self, switch_name, config):
        """Translate a single switch configuration.

        :param switch_name: Name of the switch
        :param config: Dictionary of configuration options for the switch
        :returns: Dictionary of section_name -> translated_config_dict
        """
        section_name = self._get_section_name(switch_name)
        translated_config = self._translate_switch_config(config)

        if translated_config:
            LOG.debug(
                "Translated config for switch %s to section %s",
                switch_name,
                section_name,
            )
            return {section_name: translated_config}

        return {}

    def _get_section_name(self, switch_name):
        """Get the section name for a switch in driver-specific format.

        :param switch_name: Name of the switch
        :returns: Section name string
        """
        return switch_name

    def _translate_switch_config(self, config):
        """Translate a single switch configuration.

        :param config: Dictionary of configuration options
        :returns: Dictionary of translated configuration options
        """
        return config


class SwitchDriverBase(object, metaclass=abc.ABCMeta):
    """Base class for all switch drivers.

    Switch drivers provide vendor-specific implementations for managing
    network switches. They are loaded dynamically by the networking service
    based on configuration and handle operations like port configuration,
    VLAN management, and LAG operations.
    """

    # The name of the switch driver.
    DRIVER_NAME = None

    # The version of the switch driver.
    DRIVER_VERSION = None

    # Whether this driver is supported. Drivers should set this to False
    # if they are deprecated or experimental.
    SUPPORTED = True

    def __init__(self):
        """Initialize the switch driver."""
        pass

    @property
    def supported(self):
        """Return whether this driver is supported."""
        return self.SUPPORTED

    @classmethod
    @abc.abstractmethod
    def get_translator(cls):
        """Return the translator for this driver's config entries."""

    @abc.abstractmethod
    def update_port(
        self,
        switch_id,
        port_name,
        description,
        mode,
        native_vlan,
        allowed_vlans=None,
        default_vlan=None,
        lag_name=None,
    ):
        """Update a port configuration on a switch.

        :param switch_id: Identifier for the switch.
        :param port_name: Name of the port on the switch.
        :param description: Description to set for the port.
        :param mode: Port mode ('access', 'trunk', or 'hybrid').
        :param native_vlan: VLAN ID to be set on the port.
        :param allowed_vlans: List of allowed VLAN IDs to be added(optional).
        :param default_vlan: VLAN ID to removed from the port(optional).
        :param lag_name: LAG name if port is part of a
                                  channel.
        :raises: ValueError on parameter validation errors.
        :raises: SwitchNotFound if the specified switch does not exist.
        :raises: SwitchDriverException on configuration failures.
        """

    @abc.abstractmethod
    def reset_port(
        self, switch_id, port_name, native_vlan=None,
        allowed_vlans=None, default_vlan=None
    ):
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

    @abc.abstractmethod
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

    @abc.abstractmethod
    def delete_lag(self, switch_ids, lag_name):
        """Delete LAG configuration from switches.

        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to delete.
        :raises: ValueError on parameter validation errors.
        :raises: SwitchNotFound if the specified switch does not exist.
        :raises: SwitchDriverException on configuration failures.
        """

    def is_switch_configured(self, switch_id):
        """Check if this driver is configured to manage the specified switch.

        This method should return True if this driver is configured to handle
        the specified switch. This is used by the driver selection logic to
        determine which driver should handle a specific switch.

        :param switch_id: Identifier for the switch to check.
        :returns: True if this driver can manage the specified switch,
                  False otherwise.
        """
        return False

    @abc.abstractmethod
    def get_switch_ids(self):
        """Return a list of switch identifiers.

        :returns: List of switch identifiers or an empty list.
        """

    @abc.abstractmethod
    def get_switch_info(self, switch_id):
        """Get information about a switch.

        This method should return a dictionary containing information about
        the specified switch. The dictionary can include various attributes
        that control the behavior of the networking service for this switch.

        Supported attributes:
        - switch_id: Identifier for the switch
        - device_name: The name of the switch device
        - device_type: The type of the switch device
        - ip: IP address of the switch device

        :param switch_id: Identifier for the switch.
        :returns: Dictionary with switch information or None.
        :raises: SwitchNotFound if the specified switch does not exist.
        """


class NoOpSwitchDriver(SwitchDriverBase):
    """No-operation switch driver for testing and development.

    This driver implements all required methods but performs no actual
    switch operations. It's useful for testing the networking service
    without requiring actual switch hardware.
    """

    DRIVER_NAME = "noop"
    DRIVER_VERSION = "1.0.0"
    SUPPORTED = True

    @classmethod
    def get_translator(cls):
        """Return the translator."""
        return BaseTranslator()

    def update_port(
        self,
        switch_id,
        port_name,
        description,
        mode,
        native_vlan,
        allowed_vlans=None,
        default_vlan=None,
        lag_name=None,
    ):
        """Log port update operation without performing actual change."""
        LOG.info(
            "NoOp: Update port %s on switch %s - mode: %s, "
            "native_vlan: %s, allowed_vlans: %s, "
            "default_vlan: %s, lag: %s",
            port_name,
            switch_id,
            mode,
            native_vlan,
            allowed_vlans,
            default_vlan,
            lag_name,
        )

    def reset_port(self, switch_id, port_name,
                   native_vlan=None, allowed_vlans=None, default_vlan=None):
        """Log port reset operation without performing actual reset."""
        LOG.info("NoOp: Reset port %s on switch %s", port_name, switch_id)

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
        """Log LAG update without performing actual configuration."""
        LOG.info(
            "NoOp: Update LAG %s on switches %s - mode: %s, "
            "native_vlan: %s, aggregation_mode: %s, "
            "allowed_vlans: %s, default_vlan: %s",
            lag_name,
            switch_ids,
            mode,
            native_vlan,
            aggregation_mode,
            allowed_vlans,
            default_vlan,
        )

    def delete_lag(self, switch_ids, lag_name):
        """LAG deletion without performing actual deletion."""
        LOG.info(
            "NoOp: Delete LAG %s from switches %s",
            lag_name,
            switch_ids,
        )

    def is_switch_configured(self, switch_id):
        """Check if NoOp driver can handle the specified switch.

        For testing purposes, the NoOp driver always returns True,
        meaning it can handle any switch. This simplifies testing
        and provides a fallback for development environments.

        :param switch_id: Identifier for the switch to check.
        :returns: Always True for testing purposes.
        """
        return True

    def get_switch_ids(self):
        """Return a list of switch identifiers."""
        return []

    def get_switch_info(self, switch_id):
        """Return mock switch information."""
        return {
            "switch_id": switch_id,
            "driver": "noop",
            "status": "connected",
            "model": "NoOp Virtual Switch",
            "version": "1.0.0",
        }
