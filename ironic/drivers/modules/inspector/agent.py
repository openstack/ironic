# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
In-band inspection implementation.
"""

from oslo_config import cfg
from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import utils as cond_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.inspector import interface as common
from ironic.drivers import utils as drivers_utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class AgentInspect(common.Common):
    """In-band inspection."""

    default_require_managed_boot = True

    def __init__(self):
        super().__init__()
        enabled_hooks = [x.strip()
                         for x in CONF.inspector.hooks.split(',')
                         if x.strip()]
        self.hooks = inspect_utils.validate_inspection_hooks("agent",
                                                             enabled_hooks)

    def _start_managed_inspection(self, task):
        """Start inspection with boot managed by ironic."""
        ep = deploy_utils.get_ironic_api_url().rstrip('/')
        if ep.endswith('/v1'):
            ep = f'{ep}/continue_inspection'
        else:
            ep = f'{ep}/v1/continue_inspection'

        common.prepare_managed_inspection(task, ep)
        self._power_on_or_reboot(task)

    def _start_unmanaged_inspection(self, task):
        """Start unmanaged inspection."""
        try:
            if not task.node.disable_power_off:
                cond_utils.node_power_action(task, states.POWER_OFF)
            # Only network boot is supported for unmanaged inspection.
            cond_utils.node_set_boot_device(task, boot_devices.PXE,
                                            persistent=False)
            self._power_on_or_reboot(task)
        except Exception as exc:
            LOG.exception('Unable to start unmanaged inspection for node '
                          '%(uuid)s: %(err)s',
                          {'uuid': task.node.uuid, 'err': exc})
            error = _('unable to start inspection: %s') % exc
            common.inspection_error_handler(task, error, raise_exc=True,
                                            clean_up=False)

    def abort(self, task):
        """Abort hardware inspection.

        :param task: a task from TaskManager.
        """
        if inspect_utils.clear_lookup_addresses(task.node):
            task.node.save()

        common.clean_up(task, finish=False, always_power_off=True)

    def continue_inspection(self, task, inventory, plugin_data):
        """Continue in-band hardware inspection.

        :param task: a task from TaskManager.
        :param inventory: hardware inventory from the node.
        :param plugin_data: optional plugin-specific data.
        """
        # Run the inspection hooks
        inspect_utils.run_inspection_hooks(task, inventory, plugin_data,
                                           self.hooks, _store_logs)
        if CONF.agent.deploy_logs_collect == 'always':
            _store_logs(plugin_data, task.node)
        common.clean_up(task, finish=False, always_power_off=True)


def _store_logs(plugin_data, node):
    logs = plugin_data.get('logs')
    if not logs:
        LOG.warning('No logs were passed by the ramdisk for node %(node)s.',
                    {'node': node.uuid})
        return

    try:
        drivers_utils.store_ramdisk_logs(node, logs, label='inspect')
    except exception:
        LOG.exception('Could not store the ramdisk logs for node %(node)s. ',
                      {'node': node.uuid})
