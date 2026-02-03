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

from ironic.common.i18n import _
from ironic.common.trait_based_networking.config_file import ConfigFile
from ironic.conf import CONF

from oslo_log import log

import os
import threading


LOG = log.getLogger(__name__)

_LOADER_LOCK = threading.Lock()
_CACHED_CONFIG_LOADER = None


def tbn_config_file_traits():
    """Get TBN traits from the configured YAML file.

    Thread-safe way to retrieve the configured and parsed TBN traits.
    """
    global _CACHED_CONFIG_LOADER
    with _LOADER_LOCK:
        if _CACHED_CONFIG_LOADER is None:
            _CACHED_CONFIG_LOADER = ConfigLoader()
        _CACHED_CONFIG_LOADER.refresh()
        return _CACHED_CONFIG_LOADER.traits


def is_config_valid():
    with _LOADER_LOCK:
        if _CACHED_CONFIG_LOADER is None:
            return False
        return _CACHED_CONFIG_LOADER.valid


class ConfigLoader(object):
    """Extends ConfigFile and provides automatic config file change detection

    Not intended for consumption outside of this module. Use the module level
    tbn_config_file_traits() function to retrieve configured and parsed traits.
    """
    def __init__(self):
        self._last_mtime = None
        self._config_file = None
        self._valid = False
        self.refresh()

    def _has_file_changed(self):
        """Returns True if the underlying config file's mtime has changed."""
        new_mtime = os.path.getmtime(
            CONF.conductor.trait_based_networking_config_file)

        if self._last_mtime is None:
            self._last_mtime = new_mtime
            return True

        if self._last_mtime != new_mtime:
            self._last_mtime = new_mtime
            return True

        return False

    def refresh(self):
        if self._has_file_changed():
            self._load_tbn_config()

    @property
    def valid(self):
        return self._valid

    @property
    def traits(self):
        if self._config_file is None:
            return []
        return self._config_file.traits()

    def _load_tbn_config(self):
        """Load Trait Based Networking configuration file for later use"""
        if not CONF.conductor.enable_trait_based_networking:
            LOG.debug('Trait Based Networking not enabled, skipping loading '
                        'configuration file.')
            return

        LOG.info(('Loading Trait Based Networking configuration located at '
                  '%(file_location)s'),
                 {'file_location': \
                  CONF.conductor.trait_based_networking_config_file })
        try:
            self._config_file = ConfigFile(
                CONF.conductor.trait_based_networking_config_file)
        except OSError as err:
            self._valid = False
            LOG.error(('Failed to load Trait Based Networking configuration '
                       'file located at \'%(file)s\', error: %(err)s'), {
                        'file': \
                            CONF.conductor.trait_based_networking_config_file,
                        'err': err})
            return

        valid, reasons = self._config_file.validate()

        if not valid:
            self._valid = False
            LOG.error(('Configuration file for Trait Based Networking '
                       'located at \'%(file)s\' is invalid. Reasons '
                       'follow:'), {
                        'file': \
                        CONF.conductor.trait_based_networking_config_file
                     })
            for reason in reasons:
                LOG.error(reason)

            return

        # NOTE(clif) If we made it here the configuration should parse.
        self._config_file.parse()

        self._valid = True
        LOG.info(_('Successfully loaded and parsed configuration for '
                   'Trait Based Networking.'))
