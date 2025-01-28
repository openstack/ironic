# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Base code for inspection hooks support."""

import abc

from oslo_config import cfg
from oslo_log import log


CONF = cfg.CONF
LOG = log.getLogger(__name__)


class InspectionHook(metaclass=abc.ABCMeta):  # pragma: no cover
    """Abstract base class for inspection hooks."""

    dependencies = []
    """An ordered list of hooks that must be enabled before this one.

    The items here should be entry point names, not classes.
    """

    def preprocess(self, task, inventory, plugin_data):
        """Hook to run before the main inspection data processing.

        This hook is run even before sanity checks.

        :param task: A TaskManager instance.
        :param inventory: Hardware inventory information sent by the ramdisk.
                          Must not be modified by the hook.
        :param plugin_data: Plugin data sent by the ramdisk. May be modified by
                            the hook.
        :returns: nothing.
        """

    def __call__(self, task, inventory, plugin_data):
        """Hook to run to process inspection data (before Ironic node update).

        This hook is run after node is found and ports are created,
        just before the node is updated with the data.

        :param task: A TaskManager instance.
        :param inventory: Hardware inventory information sent by the ramdisk.
                          Must not be modified by the hook.
        :param plugin_data: Plugin data sent by the ramdisk. May be modified by
                            the hook.
        :returns: nothing.
        """
