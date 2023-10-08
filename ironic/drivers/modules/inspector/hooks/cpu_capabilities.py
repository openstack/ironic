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


class CPUCapabilitiesHook(base.InspectionHook):
    """Hook to set node's capabilities based on cpu flags in the inventory."""

    def __call__(self, task, inventory, plugin_data):
        cpu_flags = inventory.get('cpu', {}).get('flags')
        if not cpu_flags:
            LOG.warning('No CPU flags available for node %s.', task.node.uuid)
            return

        cpu_flags = set(cpu_flags)
        cpu_capabilities = {}
        for flag, name in CONF.inspector.cpu_capabilities.items():
            if flag in cpu_flags:
                cpu_capabilities[name] = 'true'
        LOG.info('CPU capabilities for node %s: %s', task.node.uuid,
                 cpu_capabilities)

        old_capabilities = task.node.properties.get('capabilities')
        new_capabilities = utils.get_updated_capabilities(old_capabilities,
                                                          cpu_capabilities)
        LOG.debug('New capabilities for node %s: %s', task.node.uuid,
                  new_capabilities)
        task.node.set_property('capabilities', new_capabilities)
        task.node.save()
