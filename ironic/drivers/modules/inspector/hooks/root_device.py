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

from ironic_lib import utils as il_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules.inspector.hooks import base

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class RootDeviceHook(base.InspectionHook):
    """Smarter root disk selection using Ironic root device hints."""

    def _get_skip_list_for_node(self, node, block_devices):
        skip_list_hints = node.properties.get("skip_block_devices", [])
        if not skip_list_hints:
            return
        skip_list = set()

        for hint in skip_list_hints:
            skipped_devs = il_utils.find_devices_by_hints(block_devices, hint)
            excluded_devs = {dev['name'] for dev in skipped_devs}
            skipped_devices = excluded_devs.difference(skip_list)
            skip_list = skip_list.union(excluded_devs)

            if skipped_devices:
                LOG.warning("Using hint %(hint)s skipping devices: %(devs)s",
                            {'hint': hint, 'devs': ','.join(skipped_devices)})
        return skip_list

    def _process_root_device_hints(self, node, inventory, plugin_data):
        """Detect root disk from root device hints and IPA inventory."""

        hints = node.properties.get('root_device')
        if not hints:
            LOG.debug('Root device hints are not provided for node %s',
                      node.uuid)
            return

        skip_list = self._get_skip_list_for_node(node, inventory['disks'])
        if skip_list:
            inventory_disks = [d for d in inventory['disks']
                               if d['name'] not in skip_list]
        else:
            inventory_disks = inventory['disks']

        try:
            root_device = il_utils.match_root_device_hints(inventory_disks,
                                                           hints)
        except (TypeError, ValueError) as e:
            raise exception.HardwareInspectionFailure(
                _('No disks could be found using root device hints %(hints)s '
                  'for node %(node)s because they failed to validate. '
                  'Error: %(error)s') % {'hints': hints, 'node': node.uuid,
                                         'error': e})
        if not root_device:
            raise exception.HardwareInspectionFailure(_(
                'No disks satisfied root device hints for node %s') %
                node.uuid)

        LOG.debug('Disk %(disk)s of size %(size)s satisfies root device '
                  'hints. Node: %s', {'disk': root_device.get('name'),
                                      'size': root_device['size'],
                                      'node': node.uuid})
        plugin_data['root_disk'] = root_device

    def __call__(self, task, inventory, plugin_data):
        """Process root disk information."""
        self._process_root_device_hints(task.node, inventory, plugin_data)

        root_disk = plugin_data.get('root_disk')
        if root_disk:
            local_gb = root_disk['size'] // units.Gi
            if not local_gb:
                LOG.warning('The requested root disk is too small (smaller '
                            'than 1 GiB) or its size cannot be detected. '
                            'Root disk: %s, Node: %s', root_disk,
                            task.node.uuid)
            else:
                if CONF.inspector.disk_partitioning_spacing:
                    local_gb -= 1
                LOG.info('Root disk %(disk)s, local_gb %(local_gb)s GiB, '
                         'Node: %(node)s', {'disk': root_disk,
                                            'local_gb': local_gb,
                                            'node': task.node.uuid})
        else:
            local_gb = 0
            LOG.info('No root device found for node %s. Assuming node is '
                     'diskless.', task.node.uuid)

        plugin_data['local_gb'] = local_gb
        task.node.set_property('local_gb', str(local_gb))
        task.node.save()
