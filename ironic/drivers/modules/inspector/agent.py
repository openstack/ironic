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

from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import utils as cond_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.inspector import interface as common
from ironic.drivers.modules.inspector import nics

LOG = logging.getLogger(__name__)


class AgentInspect(common.Common):
    """In-band inspection."""

    def _start_managed_inspection(self, task):
        """Start inspection managed by ironic."""
        ep = deploy_utils.get_ironic_api_url().rstrip('/')
        if ep.endswith('/v1'):
            ep = f'{ep}/continue_inspection'
        else:
            ep = f'{ep}/v1/continue_inspection'

        common.prepare_managed_inspection(task, ep)
        cond_utils.node_power_action(task, states.POWER_ON)

    def _start_unmanaged_inspection(self, task):
        """Start unmanaged inspection."""
        try:
            cond_utils.node_power_action(task, states.POWER_OFF)
            # Only network boot is supported for unmanaged inspection.
            cond_utils.node_set_boot_device(task, boot_devices.PXE,
                                            persistent=False)
            cond_utils.node_power_action(task, states.POWER_ON)
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
        error = _("By request, the inspection operation has been aborted")
        inspect_utils.clear_lookup_addresses(task.node)
        common.inspection_error_handler(task, error, raise_exc=False,
                                        clean_up=True)

    def continue_inspection(self, task, inventory, plugin_data):
        """Continue in-band hardware inspection.

        This implementation simply defers to ironic-inspector. It only exists
        to simplify the transition to Ironic-native in-band inspection.

        :param task: a task from TaskManager.
        :param inventory: hardware inventory from the node.
        :param plugin_data: optional plugin-specific data.
        """
        # TODO(dtantsur): migrate the whole pipeline from ironic-inspector
        nics.process_interfaces(task, inventory, plugin_data)
        common.clean_up(task, finish=False)
