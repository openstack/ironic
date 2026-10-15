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

import re

from oslo_config import cfg
from oslo_log import log as logging
import yaml

from ironic.common import exception
from ironic.drivers.modules.inspector.hooks import base
from ironic import objects

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CUSTOM_TRAIT_PATTERN = re.compile(r'^CUSTOM_[A-Z0-9_]+$')


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
            # Validate trait format if provided
            trait = device.get('trait')
            if trait and not CUSTOM_TRAIT_PATTERN.match(trait):
                raise RuntimeError(
                    'Trait "%s" for device %s:%s does not match the '
                    'required pattern CUSTOM_[A-Z0-9_]+. All traits must '
                    'be prefixed with CUSTOM_ and contain only uppercase '
                    'letters, numbers, and underscores.' % (
                        trait, device.get('vendor_id'),
                        device.get('device_id')))

    def _manage_traits(self, task, found_traits):
        """Manage node traits based on detected accelerators.

        :param task: A TaskManager instance.
        :param found_traits: Set of trait strings found on the node.
        """
        if not CONF.inspector.auto_set_accelerator_traits:
            return

        # Get all traits defined in known_accelerators
        all_known_traits = set()
        for device in self._known_devices['pci_devices']:
            trait = device.get('trait')
            if trait:
                all_known_traits.add(trait)

        # Get current node traits
        try:
            current_traits = objects.TraitList.get_by_node_id(
                task.context, task.node.id)
            current_trait_names = set(current_traits.get_trait_names())
        except exception.NodeNotFound:
            LOG.warning('Node %s not found when retrieving traits.',
                        task.node.uuid)
            return

        # Determine traits to add and remove
        traits_to_add = found_traits - current_trait_names
        # Only remove traits that are in our known_accelerators config
        # and were previously set but are no longer detected
        traits_to_remove = (all_known_traits & current_trait_names
                            ) - found_traits

        # Add new traits
        for trait in traits_to_add:
            try:
                trait_obj = objects.Trait(task.context, node_id=task.node.id,
                                          trait=trait)
                trait_obj.create()
                LOG.debug('Added trait %s to node %s based on detected '
                          'accelerator device.', trait, task.node.uuid)
            except Exception as e:
                LOG.warning('Failed to add trait %s to node %s: %s',
                            trait, task.node.uuid, e)

        # Remove traits that are no longer applicable
        for trait in traits_to_remove:
            try:
                objects.Trait.destroy(task.context, task.node.id, trait)
                LOG.debug('Removed trait %s from node %s as the associated '
                          'accelerator device is no longer present.',
                          trait, task.node.uuid)
            except exception.NodeTraitNotFound:
                pass
            except Exception as e:
                LOG.warning('Failed to remove trait %s from node %s: %s',
                            trait, task.node.uuid, e)

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
        found_traits = set()
        for pci_dev in pci_devices:
            known_device = index.get((pci_dev['vendor_id'],
                                      pci_dev['product_id']))
            if known_device:
                accelerator = known_device.copy()
                accelerator.update(pci_address=pci_dev['bus'])
                accelerators.append(accelerator)
                # Track the trait for this device if one is defined,
                # otherwise warn: the trait can be added by the operator
                # through the known accelerators configuration file.
                trait = known_device.get('trait')
                if trait:
                    found_traits.add(trait)
                else:
                    LOG.warning(
                        'Accelerator device %s (%s:%s) found on node %s '
                        'has no trait defined in the known accelerators '
                        'configuration file. Add a trait to the file to '
                        'have it recorded on the node.',
                        known_device.get('device_info'),
                        pci_dev['vendor_id'], pci_dev['product_id'],
                        task.node.uuid)

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

        # Manage traits based on detected accelerators
        self._manage_traits(task, found_traits)
