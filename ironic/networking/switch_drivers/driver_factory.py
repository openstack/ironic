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
Networking service driver factory for loading switch drivers.

This module provides a driver factory system for the networking service,
allowing dynamic loading of switch drivers from external projects via
entry points.
"""

import collections

from oslo_log import log

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conf import CONF

LOG = log.getLogger(__name__)


class BaseSwitchDriverFactory(driver_factory.BaseDriverFactory):
    """Base factory for discovering, loading and managing switch drivers.

    This factory loads switch drivers from entry points and manages their
    lifecycle. Switch drivers are loaded from external projects and provide
    vendor-specific implementations for network switch management.

    Inherits from common.BaseDriverFactory to ensure consistency with
    Ironic's standard driver factory pattern.
    """

    # Entry point namespace for switch drivers
    _entrypoint_name = "ironic.networking.switch_drivers"

    # Configuration option containing enabled drivers list
    _enabled_driver_list_config_option = "enabled_switch_drivers"

    # Template for logging loaded drivers
    _logging_template = "Loaded the following switch drivers: %s"

    @classmethod
    def _set_enabled_drivers(cls):
        """Set the list of enabled drivers from configuration.

        Overrides the base implementation to read from the networking
        configuration group instead of the default group.
        """
        enabled_drivers = getattr(
            CONF.ironic_networking, cls._enabled_driver_list_config_option, []
        )

        # Check for duplicated driver entries and warn about them
        counter = collections.Counter(enabled_drivers).items()
        duplicated_drivers = []
        cls._enabled_driver_list = []

        for item, cnt in counter:
            if not item:
                raise exception.ConfigInvalid(
                    error_msg=(
                        'An empty switch driver was specified in the "%s" '
                        "configuration option. Please fix your ironic.conf "
                        "file." % cls._enabled_driver_list_config_option
                    )
                )
            if cnt > 1:
                duplicated_drivers.append(item)
            cls._enabled_driver_list.append(item)

        if duplicated_drivers:
            raise exception.ConfigInvalid(
                error_msg=(
                    'The switch driver(s) "%s" is/are duplicated in the '
                    "list of enabled drivers. Please check your "
                    "configuration file." % ", ".join(duplicated_drivers)
                )
            )

    @classmethod
    def _init_extension_manager(cls):
        """Initialize the extension manager for loading switch drivers.

        Extends the base implementation to handle the case where no
        switch drivers are enabled.
        """
        # Set enabled drivers first
        cls._set_enabled_drivers()

        # Only proceed if we have enabled drivers
        if not cls._enabled_driver_list:
            LOG.info("No switch drivers enabled in configuration")
            return

        # Call parent implementation
        try:
            super()._init_extension_manager()
        except RuntimeError as e:
            if "No suitable drivers found" in str(e):
                LOG.warning(
                    "No switch drivers could be loaded. Check that "
                    "the specified drivers are installed and their "
                    "entry points are correctly defined."
                )
                cls._extension_manager = None
            else:
                raise


def _warn_if_unsupported(ext):
    """Warn if a driver is marked as unsupported."""
    if hasattr(ext.obj, "supported") and not ext.obj.supported:
        LOG.warning(
            'Switch driver "%s" is UNSUPPORTED. It has been '
            "deprecated and may be removed in a future release.",
            ext.name,
        )


class SwitchDriverFactory(BaseSwitchDriverFactory):
    """Factory for loading switch drivers from entry points."""

    pass


# Global factory instance
_switch_driver_factory = None


def get_switch_driver_factory():
    """Get the global switch driver factory instance."""
    global _switch_driver_factory
    if _switch_driver_factory is None:
        _switch_driver_factory = SwitchDriverFactory()
    return _switch_driver_factory


def get_switch_driver(driver_name):
    """Get a switch driver instance by name.

    :param driver_name: Name of the switch driver to retrieve.
    :returns: Instance of the switch driver.
    :raises: DriverNotFound if the driver is not found.
    """
    factory = get_switch_driver_factory()
    return factory.get_driver(driver_name)


def list_switch_drivers():
    """Get a list of all available switch driver names.

    :returns: List of switch driver names.
    """
    factory = get_switch_driver_factory()
    return factory.names


def switch_drivers():
    """Get all switch drivers as a dictionary.

    :returns: Dictionary mapping driver name to driver instance.
    """
    factory = get_switch_driver_factory()
    return dict(factory.items())
