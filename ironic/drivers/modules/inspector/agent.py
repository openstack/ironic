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
from oslo_utils import excutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import utils as cond_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.inspector.hooks import base as hooks_base
from ironic.drivers.modules.inspector import interface as common
from ironic.drivers import utils as driver_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class AgentInspect(common.Common):
    """In-band inspection."""

    def __init__(self):
        super().__init__()
        self.hooks = hooks_base.validate_inspection_hooks()

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

        :param task: a task from TaskManager.
        :param inventory: hardware inventory from the node.
        :param plugin_data: optional plugin-specific data.
        """
        # Run the inspection hooks
        run_inspection_hooks(task, inventory, plugin_data, self.hooks)

        common.clean_up(task, finish=False)


def _store_logs(plugin_data, node):
    logs = plugin_data.get('logs')
    if not logs:
        LOG.warning('No logs were passed by the ramdisk for node %(node)s.',
                    {'node': node.uuid})
        return

    try:
        driver_utils.store_ramdisk_logs(node, logs, label='inspect')
    except exception:
        LOG.exception('Could not store the ramdisk logs for node %(node)s. ',
                      {'node': node.uuid})


def run_inspection_hooks(task, inventory, plugin_data, hooks):
    """Process data from the ramdisk using inspection hooks."""

    _run_preprocess_hooks(task, inventory, plugin_data, hooks)

    try:
        _run_post_hooks(task, inventory, plugin_data, hooks)
        _power_off_node(task)
    except exception.HardwareInspectionFailure:
        with excutils.save_and_reraise_exception():
            _store_logs(plugin_data, task.node)
    except Exception as exc:
        LOG.exception('Unexpected exception while running inspection hooks for'
                      ' node %(node)s', {'node': task.node.uuid})
        msg = _('Unexpected exception %(exc_class)s during processing for '
                'node: %(node)s. Error: %(error)s' %
                {'exc_class': exc.__class__.__name__,
                 'node': task.node.uuid,
                 'error': exc})
        _store_logs(plugin_data, task.node)
        raise exception.HardwareInspectionFailure(error=msg)

    if CONF.agent.deploy_logs_collect == 'always':
        _store_logs(plugin_data, task.node)


def _run_preprocess_hooks(task, inventory, plugin_data, hooks):
    failures = []

    for hook in hooks:
        LOG.debug('Running preprocess inspection hook: %(hook)s for node: '
                  '%(node)s', {'hook': hook.name, 'node': task.node.uuid})

        # NOTE(dtantsur): catch exceptions, so that we have changes to update
        # node inspection status with after look up
        try:
            hook.obj.preprocess(task, inventory, plugin_data)
        except exception.HardwareInspectionFailure as exc:
            LOG.error('Preprocess hook: %(hook)s failed for node %(node)s '
                      'with error: %(error)s', {'hook': hook.name,
                                                'node': task.node.uuid,
                                                'error': exc})
            failures.append('Error in preprocess hook %(hook)s: %(error)s',
                            {'hook': hook.name,
                             'error': exc})
        except Exception as exc:
            LOG.exception('Preprocess hook: %(hook)s failed for node %(node)s '
                          'with error: %(error)s', {'hook': hook.name,
                                                    'node': task.node.uuid,
                                                    'error': exc})
            failures.append(_('Unexpected exception %(exc_class)s during '
                              'preprocess hook %(hook)s: %(error)s' %
                              {'exc_class': exc.__class__.__name__,
                               'hook': hook.name,
                               'error': exc}))

    if failures:
        msg = _('The following failures happened while running preprocess '
                'hooks for node %(node)s:\n%(failures)s',
                {'node': task.node.uuid,
                 'failures': '\n'.join(failures)})
        _store_logs(plugin_data, task.node)
        raise exception.HardwareInspectionFailure(error=msg)

    # TODO(masghar): Store unprocessed inspection data


def _run_post_hooks(task, inventory, plugin_data, hooks):
    for hook in hooks:
        LOG.debug('Running inspection hook %(hook)s for node %(node)s',
                  {'hook': hook.name, 'node': task.node.uuid})
        hook.obj.__call__(task, inventory, plugin_data)


def _power_off_node(task):
    power_off = CONF.inspector.power_off
    if not power_off:
        return

    node = task.node
    LOG.debug('Forcing power off of node %(node)s', {'node': node.uuid})
    try:
        cond_utils.node_power_action(task, states.POWER_OFF)
    except Exception as exc:
        msg = _("Failed to power off node %(node)s after inspection. Check "
                "its power management configuration. Error: %(error)s" %
                {'node': node.uuid, "error": exc})
        raise exception.HardwareInspectionFailure(msg)
    LOG.info('Node %(node)s powered off', {'node': node.uuid})
