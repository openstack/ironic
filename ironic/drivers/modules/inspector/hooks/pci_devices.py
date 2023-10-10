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

"""Gather and distinguish PCI devices from plugin_data."""

import collections
import json

from oslo_config import cfg
from oslo_log import log as logging

from ironic.common import utils
from ironic.drivers.modules.inspector.hooks import base


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _parse_pci_alias_entries():
    parsed_pci_devices = []

    for pci_alias_entry in CONF.inspector.pci_device_alias:
        try:
            parsed_entry = json.loads(pci_alias_entry)
            if set(parsed_entry) != {'vendor_id', 'product_id', 'name'}:
                raise KeyError('The "pci_device_alias" entry should contain '
                               'exactly the "vendor_id", "product_id" and '
                               '"name" keys.')
            parsed_pci_devices.append(parsed_entry)
        except (ValueError, KeyError) as exc:
            LOG.error("Error parsing 'pci_device_alias' option: %s", exc)

    return {(dev['vendor_id'], dev['product_id']): dev['name']
            for dev in parsed_pci_devices}


class PciDevicesHook(base.InspectionHook):
    """Hook to count various PCI devices, and set the node's capabilities.

    This information can later be used by nova for node scheduling.
    """
    _aliases = _parse_pci_alias_entries()

    def _found_pci_devices_count(self, found_pci_devices):
        return collections.Counter([(dev['vendor_id'], dev['product_id'])
                                    for dev in found_pci_devices
                                    if (dev['vendor_id'], dev['product_id'])
                                    in self._aliases])

    def __call__(self, task, inventory, plugin_data):
        """Update node capabilities with PCI devices."""

        if 'pci_devices' not in plugin_data:
            if CONF.inspector.pci_device_alias:
                LOG.warning('No information about PCI devices was received '
                            'from the ramdisk.')
            return

        alias_count = {self._aliases[id_pair]: count for id_pair, count in
                       self._found_pci_devices_count(
                           plugin_data['pci_devices']).items()}
        if alias_count:
            LOG.info('Found the following PCI devices: %s', alias_count)

            old_capabilities = task.node.properties.get('capabilities')
            LOG.debug('Old capabilities for node %s: %s', task.node.uuid,
                      old_capabilities)
            new_capabilities = utils.get_updated_capabilities(old_capabilities,
                                                              alias_count)
            task.node.set_property('capabilities', new_capabilities)
            LOG.debug('New capabilities for node %s: %s', task.node.uuid,
                      new_capabilities)
            task.node.save()
