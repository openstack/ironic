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
Driver Configuration Translators

This module contains translator classes that convert generic switch
configuration into driver-specific configuration formats. Each translator
handles the specifics of how a particular driver expects its configuration
to be structured.
"""
import abc

from oslo_log import log

LOG = log.getLogger(__name__)


class BaseTranslator(metaclass=abc.ABCMeta):
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

    @abc.abstractmethod
    def _get_section_name(self, switch_name):
        """Get the section name for a switch in driver-specific format.

        :param switch_name: Name of the switch
        :returns: Section name string
        """
        raise NotImplementedError(
            "Subclasses must implement _get_section_name"
        )

    @abc.abstractmethod
    def _translate_switch_config(self, config):
        """Translate a single switch configuration.

        :param config: Dictionary of configuration options
        :returns: Dictionary of translated configuration options
        """
        raise NotImplementedError(
            "Subclasses must implement _translate_switch_config"
        )
