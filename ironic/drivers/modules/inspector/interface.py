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
Modules required to work with ironic_inspector:
    https://pypi.org/project/ironic-inspector
"""

from urllib import parse as urlparse

import eventlet
from oslo_log import log as logging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import periodics
from ironic.conductor import task_manager
from ironic.conductor import utils as cond_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.inspector import client

LOG = logging.getLogger(__name__)

# Internal field to mark whether ironic or inspector manages boot for the node
_IRONIC_MANAGES_BOOT = 'inspector_manage_boot'


def _get_callback_endpoint(client):
    root = CONF.inspector.callback_endpoint_override or client.get_endpoint()
    if root == 'mdns':
        return root

    parts = urlparse.urlsplit(root)

    if utils.is_loopback(parts.hostname):
        raise exception.InvalidParameterValue(
            _('Loopback address %s cannot be used as an introspection '
              'callback URL') % parts.hostname)

    # NOTE(dtantsur): the IPA side is quite picky about the exact format.
    if parts.path.endswith('/v1'):
        add = '/continue'
    else:
        add = '/v1/continue'

    return urlparse.urlunsplit((parts.scheme, parts.netloc,
                                parts.path.rstrip('/') + add,
                                parts.query, parts.fragment))


def _tear_down_managed_boot(task):
    errors = []

    ironic_manages_boot = utils.pop_node_nested_field(
        task.node, 'driver_internal_info', _IRONIC_MANAGES_BOOT)
    if not ironic_manages_boot:
        return errors

    try:
        task.driver.boot.clean_up_ramdisk(task)
    except Exception as exc:
        errors.append(_('unable to clean up ramdisk boot: %s') % exc)
        LOG.exception('Unable to clean up ramdisk boot for node %s',
                      task.node.uuid)
    try:
        with cond_utils.power_state_for_network_configuration(task):
            task.driver.network.remove_inspection_network(task)
    except Exception as exc:
        errors.append(_('unable to remove inspection ports: %s') % exc)
        LOG.exception('Unable to remove inspection network for node %s',
                      task.node.uuid)

    if CONF.inspector.power_off and not utils.fast_track_enabled(task.node):
        try:
            cond_utils.node_power_action(task, states.POWER_OFF)
        except Exception as exc:
            errors.append(_('unable to power off the node: %s') % exc)
            LOG.exception('Unable to power off node %s', task.node.uuid)

    return errors


def _inspection_error_handler(task, error, raise_exc=False, clean_up=True):
    if clean_up:
        _tear_down_managed_boot(task)

    task.node.last_error = error
    if raise_exc:
        task.node.save()
        raise exception.HardwareInspectionFailure(error=error)
    else:
        task.process_event('fail')


def _ironic_manages_boot(task, raise_exc=False):
    """Whether ironic should manage boot for this node."""
    try:
        task.driver.boot.validate_inspection(task)
    except exception.UnsupportedDriverExtension as e:
        LOG.debug('The boot interface %(iface)s of the node %(node)s does '
                  'not support managed boot for in-band inspection or '
                  'the required options are not populated: %(exc)s',
                  {'node': task.node.uuid,
                   'iface': task.node.get_interface('boot'),
                   'exc': e})
        if raise_exc:
            raise
        return False

    try:
        task.driver.network.validate_inspection(task)
    except exception.UnsupportedDriverExtension as e:
        LOG.debug('The network interface %(iface)s of the node %(node)s does '
                  'not support managed boot for in-band inspection or '
                  'the required options are not populated: %(exc)s',
                  {'node': task.node.uuid,
                   'iface': task.node.get_interface('network'),
                   'exc': e})
        if raise_exc:
            raise
        return False

    return True


def _start_managed_inspection(task):
    """Start inspection managed by ironic."""
    try:
        cli = client.get_client(task.context)
        endpoint = _get_callback_endpoint(cli)
        params = dict(
            utils.parse_kernel_params(CONF.inspector.extra_kernel_params),
            **{'ipa-inspection-callback-url': endpoint})
        if utils.fast_track_enabled(task.node):
            params['ipa-api-url'] = deploy_utils.get_ironic_api_url()

        cond_utils.node_power_action(task, states.POWER_OFF)
        with cond_utils.power_state_for_network_configuration(task):
            task.driver.network.add_inspection_network(task)
        task.driver.boot.prepare_ramdisk(task, ramdisk_params=params)
        cli.start_introspection(task.node.uuid, manage_boot=False)
        cond_utils.node_power_action(task, states.POWER_ON)
    except Exception as exc:
        LOG.exception('Unable to start managed inspection for node %(uuid)s: '
                      '%(err)s', {'uuid': task.node.uuid, 'err': exc})
        error = _('unable to start inspection: %s') % exc
        _inspection_error_handler(task, error, raise_exc=True)


class Inspector(base.InspectInterface):
    """In-band inspection via ironic-inspector project."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return {}  # no properties

    def validate(self, task):
        """Validate the driver-specific inspection information.

        If invalid, raises an exception; otherwise returns None.

        :param task: a task from TaskManager.
        :raises: UnsupportedDriverExtension
        """
        utils.parse_kernel_params(CONF.inspector.extra_kernel_params)
        if CONF.inspector.require_managed_boot:
            _ironic_manages_boot(task, raise_exc=True)

    def inspect_hardware(self, task):
        """Inspect hardware to obtain the hardware properties.

        This particular implementation only starts inspection using
        ironic-inspector. Results will be checked in a periodic task.

        :param task: a task from TaskManager.
        :returns: states.INSPECTWAIT
        :raises: HardwareInspectionFailure on failure
        """
        try:
            inspect_utils.create_ports_if_not_exist(task)
        except exception.UnsupportedDriverExtension:
            LOG.debug('Pre-creating ports prior to inspection not supported'
                      ' on node %s.', task.node.uuid)

        ironic_manages_boot = _ironic_manages_boot(
            task, raise_exc=CONF.inspector.require_managed_boot)

        utils.set_node_nested_field(task.node, 'driver_internal_info',
                                    _IRONIC_MANAGES_BOOT,
                                    ironic_manages_boot)
        task.node.save()

        LOG.debug('Starting inspection for node %(uuid)s using '
                  'ironic-inspector, booting is managed by %(project)s',
                  {'uuid': task.node.uuid,
                   'project': 'ironic' if ironic_manages_boot
                   else 'ironic-inspector'})

        if ironic_manages_boot:
            _start_managed_inspection(task)
        else:
            # NOTE(dtantsur): spawning a short-living green thread so that
            # we can release a lock as soon as possible and allow
            # ironic-inspector to operate on the node.
            eventlet.spawn_n(_start_inspection, task.node.uuid, task.context)
        return states.INSPECTWAIT

    def abort(self, task):
        """Abort hardware inspection.

        :param task: a task from TaskManager.
        """
        node_uuid = task.node.uuid
        LOG.debug('Aborting inspection for node %(uuid)s using '
                  'ironic-inspector', {'uuid': node_uuid})
        client.get_client(task.context).abort_introspection(node_uuid)

    @periodics.node_periodic(
        purpose='checking hardware inspection status',
        spacing=CONF.inspector.status_check_period,
        filters={'provision_state': states.INSPECTWAIT},
    )
    def _periodic_check_result(self, task, manager, context):
        """Periodic task checking results of inspection."""
        _check_status(task)


def _start_inspection(node_uuid, context):
    """Call to inspector to start inspection."""
    try:
        client.get_client(context).start_introspection(node_uuid)
    except Exception as exc:
        LOG.error('Error contacting ironic-inspector for inspection of node '
                  '%(node)s: %(cls)s: %(err)s',
                  {'node': node_uuid, 'cls': type(exc).__name__, 'err': exc})
        # NOTE(dtantsur): if acquire fails our last option is to rely on
        # timeout
        lock_purpose = 'recording hardware inspection error'
        with task_manager.acquire(context, node_uuid,
                                  purpose=lock_purpose) as task:
            error = _('Failed to start inspection: %s') % exc
            _inspection_error_handler(task, error)
    else:
        LOG.info('Node %s was sent to inspection to ironic-inspector',
                 node_uuid)


def _check_status(task):
    """Check inspection status for node given by a task."""
    node = task.node
    if node.provision_state != states.INSPECTWAIT:
        return
    if not isinstance(task.driver.inspect, Inspector):
        return

    LOG.debug('Calling to inspector to check status of node %s',
              task.node.uuid)

    try:
        inspector_client = client.get_client(task.context)
        status = inspector_client.get_introspection(node.uuid)
    except Exception:
        # NOTE(dtantsur): get_status should not normally raise
        # let's assume it's a transient failure and retry later
        LOG.exception('Unexpected exception while getting '
                      'inspection status for node %s, will retry later',
                      node.uuid)
        return

    if not status.error and not status.is_finished:
        return

    # If the inspection has finished or failed, we need to update the node, so
    # upgrade our lock to an exclusive one.
    task.upgrade_lock()
    node = task.node

    if status.error:
        LOG.error('Inspection failed for node %(uuid)s with error: %(err)s',
                  {'uuid': node.uuid, 'err': status.error})
        error = _('ironic-inspector inspection failed: %s') % status.error
        _inspection_error_handler(task, error)
    elif status.is_finished:
        _clean_up(task)
        store_data = CONF.inventory.data_backend
        if store_data == 'none':
            LOG.debug('Introspection data storage is disabled, the data will '
                      'not be saved for node %(node)s', {'node': node.uuid})
            return
        introspection_data = inspector_client.get_introspection_data(
            node.uuid, processed=True)
        inspect_utils.store_introspection_data(node, introspection_data,
                                               task.context)


def _clean_up(task):
    errors = _tear_down_managed_boot(task)
    if errors:
        errors = ', '.join(errors)
        LOG.error('Inspection clean up failed for node %(uuid)s: %(err)s',
                  {'uuid': task.node.uuid, 'err': errors})
        msg = _('Inspection clean up failed: %s') % errors
        _inspection_error_handler(task, msg, raise_exc=False, clean_up=False)
    else:
        LOG.info('Inspection finished successfully for node %s',
                 task.node.uuid)
        task.process_event('done')
