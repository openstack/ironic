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

from ironic.common import utils
from ironic.drivers.modules.inspector.hooks import base

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class BootModeHook(base.InspectionHook):
    """Hook to set the node's boot_mode capability in node properties."""

    def __call__(self, task, inventory, plugin_data):

        boot_mode = inventory.get('boot', {}).get('current_boot_mode')
        if boot_mode is None:
            LOG.warning('No boot mode information available for node %s',
                        task.node.uuid)
            return
        LOG.info('Boot mode is %s for node %s', boot_mode, task.node.uuid)

        old_capabilities = task.node.properties.get('capabilities')
        new_capabilities = utils.get_updated_capabilities(
            old_capabilities, {'boot_mode': boot_mode})
        LOG.debug('New capabilities for node %s: %s', task.node.uuid,
                  new_capabilities)
        task.node.set_property('capabilities', new_capabilities)
        task.node.save()
