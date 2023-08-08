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

from oslo_config import cfg
from oslo_log import log as logging

from ironic.drivers.modules.inspector.hooks import base

LOG = logging.getLogger(__name__)
_ITEM_SIZE = 4
CONF = cfg.CONF


class ExtraHardwareHook(base.InspectionHook):
    """Hook to gather extra information about the node hardware."""

    def __call__(self, task, inventory, plugin_data):
        """Store extra hardware information in plugin_data['extra']

        Convert the extra collected data from the format of the
        hardware-detect tool (list of lists) to a nested dictionary. Remove
        the original ``data`` field from plugin_data, and save the converted
        data into a new field ``extra`` instead.
        """

        if 'data' not in plugin_data:
            LOG.warning('No extra hardware information was received from the '
                        'ramdisk for node %s', task.node.uuid)
            return

        data = plugin_data['data']
        if not self._is_valid_data(data):
            LOG.warning('Extra hardware data was not in a recognised format, '
                        'and will not be forwarded to inspection rules for '
                        'node %s', task.node.uuid)
            if CONF.inspector.extra_hardware_strict:
                LOG.debug('Deleting \"data\" key from plugin data of node %s '
                          'as it is malformed and strict mode is on.',
                          task.node.uuid)
                del plugin_data['data']
            return

        # NOTE(sambetts) If data is in a valid format, convert it to
        # dictionaries for rules processing, and store converted data in
        # plugin_data['extra'].
        # Delete plugin_data['data'], as it is assumed unusable by rules.
        converted = {}
        for item in data:
            if not item:
                continue
            try:
                converted_0 = converted.setdefault(item[0], {})
                converted_1 = converted_0.setdefault(item[1], {})
                try:
                    item[3] = int(item[3])
                except (ValueError, TypeError):
                    pass
                converted_1[item[2]] = item[3]
            except Exception as e:
                LOG.warning('Ignoring invalid extra data item %s for node %s. '
                            'Error: %s', item, task.node.uuid, e)
        plugin_data['extra'] = converted

        LOG.debug('Deleting \"data\" key from plugin data of node %s as it is '
                  'assumed unusable by inspection rules.', task.node.uuid)
        del plugin_data['data']

    def _is_valid_data(self, data):
        return isinstance(data, list) and all(
            isinstance(item, list)
            and (not CONF.inspector.extra_hardware_strict
                 or len(item) == _ITEM_SIZE)
            for item in data)
