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
from ironic.common.i18n import _
from ironic.drivers.modules.inspector.hooks import base

LOG = logging.getLogger(__name__)


class ArchitectureHook(base.InspectionHook):
    """Hook to set the node's cpu_arch property based on the inventory."""

    def __call__(self, task, inventory, plugin_data):
        """Update node properties with CPU architecture."""

        try:
            cpu_arch = inventory['cpu']['architecture']
            LOG.info('Discovered CPU architecture: %(cpu_arch)s for node: '
                     '%(node)s', {'cpu_arch': cpu_arch,
                                  'node': task.node.uuid})
            task.node.set_property('cpu_arch', cpu_arch)
            task.node.save()
        except (KeyError, ValueError, TypeError):
            msg = _('Inventory has malformed or missing CPU architecture '
                    'information: %(cpu)s for node %(node)s.') % {
                        'cpu': inventory.get('cpu'), 'node': task.node.uuid}
            LOG.error(msg)
            raise exception.InvalidNodeInventory(node=task.node.uuid,
                                                 reason=msg)
