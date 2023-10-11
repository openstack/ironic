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


from oslo_log import log as logging

from ironic.common import exception
from ironic.drivers.modules.inspector.hooks import base
from ironic.objects import node_inventory

LOG = logging.getLogger(__name__)


class RaidDeviceHook(base.InspectionHook):
    """Hook for learning the root device after RAID creation.

    This hook can figure out the root device in 2 runs. In the first run, the
    node's inventory is saved as usual, and the hook does not do anything.
    The second run will check the difference between the recently discovered
    block devices (as reported by the inspection results) and the previously
    saved ones (from the previously saved inventory). If there is exactly one
    new block device, its serial number is saved in node.properties under the
    'root_device' key.

    This way, it helps to figure out the root device hint in cases when Ironic
    doesn't have enough information to do so otherwise. One such usecase is
    DRAC RAID configuration, where the BMC doesn't provide any useful
    information about the created RAID disks. Using this hook immediately
    before and after creating the root RAID device will solve the issue of
    root device hints.
    """

    def _get_serials(self, inventory):
        if inventory.get('disks'):
            return [x['serial'] for x in inventory.get('disks')
                    if x.get('serial')]

    def __call__(self, task, inventory, plugin_data):
        node = task.node

        if 'root_device' in node.properties:
            LOG.info('Root device is already known for node %s', node.uuid)
            return

        current_devices = self._get_serials(inventory)
        if not current_devices:
            LOG.warning('No block device information was received from the '
                        'ramdisk for node %s', node.uuid)
            return

        try:
            previous_inventory = node_inventory.NodeInventory.get_by_node_id(
                task.context, node.id)
        except exception.NodeInventoryNotFound:
            LOG.debug('Inventory for node %s not found in the database. Raid '
                      'device hook exiting.', task.node.uuid)
            return
        previous_devices = self._get_serials(previous_inventory.get(
            'inventory_data'))

        # Compare previously discovered devices with the current ones
        new_devices = [device for device in current_devices
                       if device not in previous_devices]
        if len(new_devices) > 1:
            LOG.warning('Root device cannot be identified because multiple '
                        'new devices were found for node %s', node.uuid)
            return
        elif len(new_devices) == 0:
            LOG.warning('No new devices were found for node %s', node.uuid)
            return

        node.set_property('root_device', {'serial': new_devices[0]})
        node.save()
        LOG.info('"root_device" property set for node %s', node.uuid)
