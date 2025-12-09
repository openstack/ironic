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

import functools
import inspect

from oslo_log import log
import oslo_messaging as messaging

from ironic.common import exception
from ironic.common.exception import ConfigInvalid
from ironic.common.i18n import _
from ironic.common import metrics_utils
from ironic.common import rpc
from ironic.conf import CONF
from ironic.drivers.modules.switch.base import SwitchDriverException
from ironic.drivers.modules.switch.base import SwitchMethodNotImplemented
from ironic.networking import switch_config
from ironic.networking.switch_drivers import driver_adapter
from ironic.networking.switch_drivers import driver_factory
from ironic.networking import utils as networking_utils

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


def validate_vlan_configuration(
    operation,
    switch_id_arg_name="switch_id"):
    """Decorator to validate VLAN configuration against allowed/denied lists.

    This decorator extracts native_vlan and allowed_vlans from method
    arguments and validates them against the switch's VLAN configuration.

    :param operation: Description of the operation for error messages.
    :param switch_id_arg_name: Name of the argument containing the switch ID.
                              For multi-switch operations, this should be the
                              argument containing the list of switch IDs.
    :returns: Decorated function that applies VLAN validation.
    """

    def decorator(func):
        # Precompute the function signature at decoration time
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(self, context, *args, **kwargs):
            """Wrapper to validate VLAN config before executing operation."""
            # Use the precomputed signature to bind the arguments
            bound_args = sig.bind(self, context, *args, **kwargs)
            bound_args.apply_defaults()

            # Extract VLAN-related arguments
            native_vlan = bound_args.arguments.get("native_vlan", None)
            allowed_vlans = bound_args.arguments.get("allowed_vlans", [])
            switch_id_value = bound_args.arguments.get(
                switch_id_arg_name, None
            )

            # For multi-switch operations, use the primary (first) switch
            if isinstance(switch_id_value, (list, tuple)) and switch_id_value:
                primary_switch_id = switch_id_value[0]
            else:
                primary_switch_id = switch_id_value

            # Only validate if we have a switch_id and native_vlan
            if primary_switch_id and native_vlan is not None:
                # Get the switch driver
                driver = self._get_switch_driver(primary_switch_id)

                # Build list of VLANs to check
                vlans_to_check = []
                if native_vlan:
                    vlans_to_check.append(native_vlan)
                if allowed_vlans:
                    vlans_to_check.extend(allowed_vlans)

                # Validate VLAN configuration
                switch_config.validate_vlan_configuration(
                    vlans_to_check,
                    driver,
                    primary_switch_id,
                    operation,
                )

            return func(self, context, *args, **kwargs)

        return wrapper

    return decorator


def _get_switch_config_filename():
    return CONF.ironic_networking.driver_config_dir + "/switches.conf"


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
            if networking_utils.rpc_transport() == "json-rpc":
                # Always use the JSON-RPC config for both topic and host
                host_ip = CONF.ironic_networking_json_rpc.host_ip
                port = CONF.ironic_networking_json_rpc.port
                topic_host = f"{host_ip}:{port}"
                topic = f"ironic.{topic_host}"
                self.host = topic_host
            else:
                topic = rpc.NETWORKING_TOPIC
        self.topic = topic

        # Tell the RPC service which json-rpc config group to use for
        # networking. This enables separate listener configuration.
        self.json_rpc_conf_group = "ironic_networking_json_rpc"

        # Initialize driver adapter for configuration preprocessing
        self._driver_adapter = None

        # Initialize switch driver factory (will be set properly in init_host)
        self._switch_driver_factory = None

    def prepare_host(self):
        """Prepare host for networking service initialization.

        This method is called by the RPC service before starting the listener.
        Since networking host configuration is now handled in __init__,
        this method is a no-op.
        """
        pass

    def init_host(self, admin_context=None):
        """Initialize the networking service host.

        This method implements two-phase driver initialization:
        1. Load driver classes (but don't initialize instances yet)
        2. Get translators from driver classes and preprocess config
        3. Initialize driver instances (config files now exist)

        :param admin_context: admin context (unused but kept for compatibility)
        """
        LOG.info("Initializing networking service on host %s", self.host)

        # Phase 1: Load driver classes (invoke_on_load=False)
        self._switch_driver_factory = (
            driver_factory.get_switch_driver_factory()
        )
        available_drivers = self._switch_driver_factory.names
        if not available_drivers:
            LOG.error("No switch drivers loaded")
            raise ConfigInvalid(_("No switch drivers loaded"))

        LOG.info("Available switch drivers: %s", ", ".join(available_drivers))

        # Phase 2: Get driver classes and create adapter
        try:
            # Get driver classes (not instances)
            driver_classes = self._switch_driver_factory.get_driver_classes()

            # Create adapter with driver classes
            self._driver_adapter = (
                driver_adapter.NetworkingDriverAdapter(driver_classes)
            )

            # Preprocess config - writes driver-specific config files
            count = self._driver_adapter.preprocess_config(
                _get_switch_config_filename()
            )
            LOG.info(
                "Generated %d driver-specific config files during init", count
            )
        except Exception as e:
            LOG.exception("Failed to preprocess driver configuration: %s", e)
            raise

        # Phase 3: Now initialize driver instances (config files are ready)
        try:
            self._switch_driver_factory.initialize_drivers()
            LOG.info("Successfully initialized switch driver instances")
        except Exception as e:
            LOG.exception("Failed to initialize switch drivers: %s", e)
            raise


    def _get_switch_driver(self, switch_id):
        """Get the appropriate switch driver for a switch.

        This method finds the correct driver for a switch by checking each
        available driver to see if it is configured to handle the switch.
        If multiple drivers can handle the same switch, the first one found
        is used.

        :param switch_id: Identifier of the switch.
        :returns: Switch driver instance.
        :raises: NetworkError if no drivers are available.
        :raises: SwitchNotFound if no driver supports the switch.
        """
        available_drivers = self._switch_driver_factory.names
        if not available_drivers:
            raise exception.NetworkError(
                _(
                    "No switch drivers are available. Please configure "
                    "enabled_switch_drivers in the networking section."
                )
            )

        # Check each driver to see if it can handle this switch
        for driver_name in available_drivers:
            try:
                driver = self._switch_driver_factory.get_driver(driver_name)

                # Check if this driver is configured for this switch
                if driver.is_switch_configured(switch_id):
                    LOG.debug(
                        "Using switch driver '%s' for switch '%s'",
                        driver_name,
                        switch_id,
                    )
                    return driver

            except exception.DriverNotFound:
                LOG.warning(
                    "Switch driver '%s' not found, skipping", driver_name
                )
                continue
            except Exception as e:
                LOG.warning(
                    "Error checking driver '%s' for switch '%s': %s",
                    driver_name,
                    switch_id,
                    e,
                )
                continue

        # No driver found that supports this switch
        raise exception.SwitchNotFound(switch_id=switch_id)

    def _update_port_impl(
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
        """Implementation of port update operation.

        :param switch_id: Identifier of the network switch.
        :param port_name: Name of the port to update.
        :param description: Description for the port.
        :param mode: Port mode (e.g., 'access', 'trunk').
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :param lag_name: Name of the LAG (optional).
        :returns: Dictionary containing the updated port configuration.
        """
        # Get the appropriate switch driver
        driver = self._get_switch_driver(switch_id)

        # Call the driver's update_port method
        driver.update_port(
            switch_id,
            port_name,
            description,
            mode,
            native_vlan,
            allowed_vlans=allowed_vlans,
            default_vlan=default_vlan,
            lag_name=lag_name,
        )

        # Return configuration summary
        port_config = {
            "switch_id": switch_id,
            "port_name": port_name,
            "description": description,
            "mode": mode,
            "native_vlan": native_vlan,
            "allowed_vlans": allowed_vlans or [],
            "default_vlan": default_vlan,
            "lag_name": lag_name,
            "status": "configured",
        }

        LOG.info(
            "Successfully configured port %(port)s on switch %(switch)s",
            {"port": port_name, "switch": switch_id},
        )

        return port_config

    @METRICS.timer("NetworkingManager.update_port")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
    )
    @validate_vlan_configuration("update_port")
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
        """Update a network switch port configuration.

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
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary containing the updated port configuration.
        """
        LOG.debug(
            "RPC update_port called for switch %(switch)s, port %(port)s",
            {"switch": switch_id, "port": port_name},
        )

        # Validate mode
        valid_modes = ["access", "trunk"]
        if mode not in valid_modes:
            raise exception.InvalidParameterValue(
                _("mode must be one of: %s") % ", ".join(valid_modes)
            )

        # Validate VLAN ID
        if (
            not isinstance(native_vlan, int)
            or native_vlan < 1
            or native_vlan > 4094
        ):
            raise exception.InvalidParameterValue(
                _("native_vlan must be an integer between 1 and 4094")
            )

        # Validate allowed_vlans if provided
        if allowed_vlans is not None:
            if not isinstance(allowed_vlans, (list, tuple)):
                raise exception.InvalidParameterValue(
                    _("allowed_vlans must be a list or tuple")
                )
            for vlan in allowed_vlans:
                if not isinstance(vlan, int) or vlan < 1 or vlan > 4094:
                    raise exception.InvalidParameterValue(
                        _(
                            "Each VLAN in allowed_vlans must be an integer "
                            "between 1 and 4094"
                        )
                    )

        try:
            return self._update_port_impl(
                switch_id,
                port_name,
                description,
                mode,
                native_vlan,
                allowed_vlans=allowed_vlans,
                default_vlan=default_vlan,
                lag_name=lag_name,
            )
        except exception.InvalidParameterValue:
            # Re-raise validation errors as-is
            raise
        except exception.NetworkError:
            # Re-raise NetworkError as-is
            raise
        except Exception as e:
            LOG.exception(
                "Failed to configure port %(port)s on switch "
                "%(switch)s",
                {"port": port_name, "switch": switch_id},
            )
            raise exception.NetworkError(
                _("Failed to configure network port: %s") % e
            ) from e

    def _reset_port_impl(
        self, switch_id, port_name, native_vlan, allowed_vlans=None,
        default_vlan=None
    ):
        """Implementation of port reset operation.

        :param switch_id: Identifier of the network switch.
        :param port_name: Name of the port to reset.
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :returns: Dictionary containing the reset port configuration.
        """
        # Get the appropriate switch driver
        driver = self._get_switch_driver(switch_id)

        # Call the driver's reset_port method
        driver.reset_port(
            switch_id, port_name, native_vlan,
            allowed_vlans=allowed_vlans, default_vlan=default_vlan
        )

        # Return reset configuration summary
        port_config = {
            "switch_id": switch_id,
            "port_name": port_name,
            "description": "Default port configuration",
            "mode": "access",
            "native_vlan": native_vlan,
            "allowed_vlans": [],
            "default_vlan": default_vlan,
            "status": "reset",
        }

        LOG.info(
            "Successfully reset port %(port)s on switch %(switch)s",
            {"port": port_name, "switch": switch_id},
        )

        return port_config

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
        """Reset a network switch port to default configuration.

        :param context: request context.
        :param switch_id: Identifier of the network switch.
        :param port_name: Name of the port to reset.
        :param native_vlan: VLAN ID to be removed from the port.
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :returns: Dictionary containing the reset port configuration.
        """
        LOG.debug(
            "RPC reset_port called for switch %(switch)s, port %(port)s",
            {"switch": switch_id, "port": port_name},
        )

        try:
            return self._reset_port_impl(
                switch_id, port_name, native_vlan,
                allowed_vlans=allowed_vlans, default_vlan=default_vlan
            )
        except exception.InvalidParameterValue:
            # Re-raise validation errors as-is
            raise
        except exception.NetworkError:
            # Re-raise NetworkError as-is
            raise
        except exception.SwitchNotFound:
            # Re-raise SwitchNotFound as-is
            raise
        except Exception as e:
            LOG.exception(
                "Failed to reset port %(port)s on switch "
                "%(switch)s",
                {"port": port_name, "switch": switch_id},
            )
            raise exception.NetworkError(
                _("Failed to reset network port: %s") % e
            ) from e

    @METRICS.timer("NetworkingManager.update_lag")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
        exception.Invalid,
        SwitchMethodNotImplemented,
    )
    @validate_vlan_configuration("update_lag",
                                 switch_id_arg_name="switch_ids")
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
        """Update a link aggregation group (LAG) configuration.

        :param context: request context.
        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to update.
        :param description: Description for the LAG.
        :param mode: LAG mode (e.g., 'access', 'trunk').
        :param native_vlan: VLAN ID to be removed from the port.
        :param aggregation_mode: Aggregation mode (e.g., 'lacp', 'static').
        :param allowed_vlans: Allowed VLAN IDs to be removed (optional).
        :param default_vlan: VLAN ID to restore onto the port (optional).
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :raises: SwitchMethodNotImplemented - LAG is not yet supported.
        :returns: Dictionary containing the updated LAG configuration.
        """
        raise SwitchMethodNotImplemented(
            _("LAG operations are not yet supported")
        )

    @METRICS.timer("NetworkingManager.delete_lag")
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NetworkError,
        exception.SwitchNotFound,
        exception.Invalid,
        SwitchMethodNotImplemented,
    )
    def delete_lag(self, context, switch_ids, lag_name):
        """Delete a link aggregation group (LAG) configuration (stub).

        :param context: request context.
        :param switch_ids: List of switch identifiers.
        :param lag_name: Name of the LAG to delete.
        :raises: InvalidParameterValue if validation fails.
        :raises: NetworkError if the network operation fails.
        :raises: SwitchMethodNotImplemented - LAG is not yet supported.
        :returns: Dictionary containing the deletion status.
        """
        raise SwitchMethodNotImplemented(
            _("LAG operations are not yet supported")
        )

    @METRICS.timer("NetworkingManager.get_switches")
    @messaging.expected_exceptions(exception.NetworkError)
    def get_switches(self, context):
        """Get information about all switches from all drivers.

        :param context: Request context
        :returns: Dictionary of switch_id -> switch_info dictionaries
        :raises: NetworkError if driver operations fail
        """
        switches = {}

        if self._switch_driver_factory is None:
            LOG.debug("Switch driver factory not available")
            return switches

        driver_names = self._switch_driver_factory.names
        if not driver_names:
            LOG.debug("No switch drivers available")
            return switches

        for driver_name in driver_names:
            try:
                driver = self._switch_driver_factory.get_driver(driver_name)
            except (exception.DriverNotFound, exception.DriverLoadError) as e:
                LOG.error(
                    "Error accessing driver %(driver)s: %(error)s",
                    {"driver": driver_name, "error": e}
                )
                raise exception.NetworkError(
                    _("Error accessing driver %(driver)s: %(error)s") % {
                        "driver": driver_name, "error": e
                    }
                ) from e

            try:
                switch_ids = driver.get_switch_ids()
                for switch_id in switch_ids:
                    switch_info = driver.get_switch_info(switch_id)
                    if switch_info:
                        switches[switch_id] = switch_info
            except SwitchDriverException as e:
                LOG.error(
                    "Failed to get switch information from driver "
                    "%(driver)s: %(error)s",
                    {"driver": driver_name, "error": e}
                )
                raise exception.NetworkError(
                    _("Failed to get switch information from driver "
                      "%(driver)s: %(error)s") % {
                        "driver": driver_name, "error": e
                    }
                ) from e

        LOG.info("Successfully retrieved %(count)d switch config sections",
                 {"count": len(switches)})
        return switches

    def cleanup(self):
        """Clean up resources."""
        pass
