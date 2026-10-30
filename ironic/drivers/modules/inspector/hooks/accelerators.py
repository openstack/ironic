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
import yaml

from ironic.drivers.modules.inspector.hooks import base

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class AcceleratorsHook(base.InspectionHook):
    """Hook to set the node's accelerators property."""

    def __init__(self):
        super(AcceleratorsHook, self).__init__()
        self._known_devices = {}
        with open(CONF.inspector.known_accelerators) as f:
            self._known_devices = yaml.safe_load(f)
        self._validate_known_devices()

    def _validate_known_devices(self):
        # Do a simple check against the data source
        if (not self._known_devices
                or 'pci_devices' not in self._known_devices):
            raise RuntimeError('Could not find pci_devices in the '
                               'configuration data.')
        if not isinstance(self._known_devices['pci_devices'], list):
            raise RuntimeError('pci_devices in the configuration file should '
                               'contain a list of devices.')
        for device in self._known_devices['pci_devices']:
            if not device.get('vendor_id') or not device.get('device_id'):
                raise RuntimeError('One of the PCI devices in the '
                                   'configuration file is missing vendor_id '
                                   'or device_id.')

    def __call__(self, task, inventory, plugin_data):
        # NOTE(dtantsur): inconsistency here: IPA uses plugin_data, while
        # Redfish put it in inventory.
        pci_devices = plugin_data.get('pci_devices', [])
        if not pci_devices:
            pci_devices = inventory.get('pci_devices', [])

        if not pci_devices:
            LOG.warning('Unable to process accelerator devices because no PCI '
                        'device information was received from the ramdisk for '
                        'node %s.', task.node.uuid)
            return

        index = {}
        for dev in self._known_devices['pci_devices']:
            dev_ids = dev['device_id']
            if isinstance(dev_ids, str):
                dev_ids = (dev_ids,)
            for dev_id in dev_ids:
                index[(dev['vendor_id'], dev_id)] = dev

        accelerators = []
        for pci_dev in pci_devices:
            known_device = index.get((pci_dev['vendor_id'],
                                      pci_dev['product_id']))
            if known_device:
                accelerator = known_device.copy()
                accelerator.update(pci_address=pci_dev['bus'])
                accelerators.append(accelerator)

        if accelerators:
            LOG.info('Found the following accelerator devices for node %s: %s',
                     task.node.uuid, accelerators)
            task.node.set_property('accelerators', accelerators)
            task.node.save()
        else:
            LOG.info('No known accelerator devices found for node %s',
                     task.node.uuid)
            task.node.set_property('accelerators', accelerators)
            task.node.save()
