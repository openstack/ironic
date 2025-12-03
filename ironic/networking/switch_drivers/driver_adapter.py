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
Driver Configuration Adapter

This module provides functionality to translate user-friendly switch
configuration into driver-specific configuration formats. It allows users
to configure switches using a generic format while supporting multiple
switch driver implementations.
"""

import configparser
import glob
import os
import tempfile

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _

LOG = log.getLogger(__name__)

CONF = cfg.CONF


class NetworkingDriverAdapter:
    """Adapter for translating switch config to driver-specific format."""

    def __init__(self, driver_classes):
        """Initialize the driver adapter.

        :param driver_classes: Dictionary of driver name -> driver class.
            Classes must implement get_translator() classmethod.
        """
        self.driver_translators = {}
        self._register_translators(driver_classes)

    def _register_translators(self, driver_classes):
        """Register available driver translators.

        :param driver_classes: Dictionary of driver name -> driver class.
            Works with both driver classes and instances since
            get_translator() is a classmethod.
        """
        for name, driver_class in driver_classes.items():
            self.register_translator(name, driver_class.get_translator())

        LOG.debug(
            "Registered translators for drivers: %s",
            list(self.driver_translators.keys()),
        )

    def register_translator(self, driver_type, translator_instance):
        """Register a custom translator for a driver type.

        :param driver_type: String identifier for the driver type
        :param translator_instance: Instance of a translator class
        """
        self.driver_translators[driver_type] = translator_instance
        LOG.info(
            "Registered custom translator for driver type: %s", driver_type
        )

    def _validate_switch_config(self, switch_name, config):
        """Validate switch configuration has required fields.

        :param switch_name: Name of the switch
        :param config: Dictionary of configuration options
        :raises: NetworkError if validation fails
        """
        required_fields = [
            'driver_type',
            'device_type',
            'address',
            'username',
            'mac_address',
        ]
        missing_fields = [f for f in required_fields if f not in config]

        # Check for authentication: must have either password or key_file
        has_auth = 'password' in config or 'key_file' in config

        if missing_fields or not has_auth:
            error_parts = []
            if missing_fields:
                error_parts.append(
                    "missing required fields: %s" % ', '.join(missing_fields)
                )
            if not has_auth:
                error_parts.append(
                    "must specify either 'password' or 'key_file'"
                )

            raise exception.NetworkError(
                _("Invalid configuration for switch '%(switch)s': %(errors)s")
                % {'switch': switch_name, 'errors': '; '.join(error_parts)}
            )

    def preprocess_config(self, output_file):
        """Transform user config into driver-specific config files.

        Scans oslo.config for switch configurations and generates
        driver-specific config files that then get written to a driver-specific
        config file.

        :returns: Number of translations generated
        """
        try:
            if not os.path.exists(CONF.ironic_networking.switch_config_file):
                raise exception.NetworkError(
                    _("Switch configuration file %s does not exist")
                    % CONF.ironic_networking.switch_config_file
                )

            # Extract generic switch sections from config
            switch_sections = self._extract_switch_sections(
                CONF.ironic_networking.switch_config_file
            )

            if not switch_sections:
                LOG.debug(
                    "No user defined switch sections found in %s",
                    CONF.ironic_networking.switch_config_file,
                )
                return 0

            # Generate driver-specific configs
            translations = {}
            for switch_name, config in switch_sections.items():
                # Validate configuration before processing
                self._validate_switch_config(switch_name, config)

                driver_type = config["driver_type"]
                LOG.debug(
                    "Translating switch %s with driver type %s",
                    switch_name,
                    driver_type,
                )
                if driver_type in self.driver_translators:
                    translator = self.driver_translators[driver_type]
                else:
                    error_msg = (_("No driver translator registered for "
                                  "switch: %(switch_name)s, with driver type: "
                                  "%(driver_type)s") %
                                 {"switch_name": switch_name,
                                  "driver_type": driver_type})
                    raise exception.ConfigInvalid(error_msg=error_msg)

                translation = translator.translate_config(switch_name, config)
                if translation:
                    translations.update(translation)

            if translations:
                self._write_config_file(output_file, translations)
                CONF.reload_config_files()

            return len(translations)
        except Exception as e:
            LOG.exception("Failed to preprocess switch configuration: %s", e)
            raise exception.NetworkError(
                _("Configuration preprocessing failed: %s") % e
            )

    def _config_files(self):
        """Generate which yields all config files in the required order"""
        for config_file in CONF.config_file:
            yield config_file
        for config_dir in CONF.config_dir:
            config_dir_glob = os.path.join(config_dir, "*.conf")
            for config_file in sorted(glob.glob(config_dir_glob)):
                yield config_file

    def _extract_switch_sections(self, config_file):
        """Extract switch configuration sections from oslo.config.

        Looks for sections with names like:
        - [switch:switch_name]

        :returns: Dictionary of section_name -> config_dict
        """
        switch_sections = {}

        sections = {}
        parser = cfg.ConfigParser(config_file, sections)
        try:
            parser.parse()
        except Exception as e:
            LOG.warning("Failed to parse config file %s: %s", config_file, e)
            return {}

        for section_name, section_config in sections.items():
            if section_name.startswith("switch:"):
                switch_name = section_name[7:]
                # Get all key/value pairs in this section
                switch_sections[switch_name] = {
                    k: v[0] for k, v in section_config.items()
                }

        LOG.debug("Found %d switch sections", len(switch_sections))
        return switch_sections

    def _write_config_file(self, output_file, switch_configs):
        """Generate driver-specific configuration file.

        :param output_file: Path to the output file
        :param switch_configs: Dictionary of switch_name -> config_dict
        """
        # Create temp file in same directory as output file for atomic rename
        output_dir = os.path.dirname(output_file)
        temp_fd = None
        temp_path = None

        try:
            config = configparser.ConfigParser()

            # Add all sections and their key-value pairs
            for section_name, section_config in switch_configs.items():
                config.add_section(section_name)
                for key, value in section_config.items():
                    config.set(section_name, key, str(value))

            # Write to temporary file first
            temp_fd, temp_path = tempfile.mkstemp(
                dir=output_dir, prefix='.tmp_driver_config_', text=True
            )
            with os.fdopen(temp_fd, 'w') as f:
                temp_fd = None  # fdopen takes ownership
                f.write(
                    "# Auto-generated config for driver-specific switch "
                    "configurations\n"
                )
                f.write(
                    "# Generated from user defined switch configuration\n\n"
                )
                config.write(f)

            # Atomically move temp file to final location
            os.replace(temp_path, output_file)
            temp_path = None  # Successfully moved

            LOG.info("Generated driver config file: %s", output_file)

        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to generate config file: %s", e)
                # Clean up temp file if it still exists
                if temp_fd is not None:
                    try:
                        os.close(temp_fd)
                    except OSError as cleanup_error:
                        LOG.debug("Failed to close temp file descriptor: %s",
                                  cleanup_error)
                if temp_path is not None:
                    try:
                        os.unlink(temp_path)
                    except OSError as cleanup_error:
                        LOG.debug("Failed to remove temp file %s: %s",
                                  temp_path, cleanup_error)

    def reload_configuration(self, output_file):
        """Reload and regenerate switch configuration files.

        This method re-extracts switch configurations from the config files
        and regenerates the driver-specific configuration files. It should
        be called when the switch configuration file has been modified.

        :param output_file: Path to the output file for driver-specific configs
        :returns: Number of translations generated
        :raises: NetworkError if configuration reload fails
        """
        LOG.info("Reloading switch configuration from config files")

        try:
            # Force oslo.config to reload configuration files
            CONF.reload_config_files()

            # Re-run the preprocessing steps
            count = self.preprocess_config(output_file)

            LOG.info(
                "Successfully reloaded switch configuration. "
                "Generated %d driver-specific config sections",
                count,
            )
            return count

        except Exception as e:
            LOG.error("Failed to reload switch configuration: %s", e)
            raise exception.NetworkError(
                _("Configuration reload failed: %s") % e
            )
