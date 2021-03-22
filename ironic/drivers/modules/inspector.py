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

import ipaddress
import shlex
from urllib import parse as urlparse

import eventlet
from futurist import periodics
import openstack
from oslo_log import log as logging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as cond_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils

LOG = logging.getLogger(__name__)

_INSPECTOR_SESSION = None
# Internal field to mark whether ironic or inspector manages boot for the node
_IRONIC_MANAGES_BOOT = 'inspector_manage_boot'


def _get_inspector_session(**kwargs):
    global _INSPECTOR_SESSION
    if not _INSPECTOR_SESSION:
        if CONF.auth_strategy != 'keystone':
            # NOTE(dtantsur): using set_default instead of set_override because
            # the native keystoneauth option must have priority.
            CONF.set_default('auth_type', 'none', group='inspector')
        service_auth = keystone.get_auth('inspector')
        _INSPECTOR_SESSION = keystone.get_session('inspector',
                                                  auth=service_auth,
                                                  **kwargs)
    return _INSPECTOR_SESSION


def _get_client(context):
    """Helper to get inspector client instance."""
    session = _get_inspector_session()
    # NOTE(dtantsur): openstacksdk expects config option groups to match
    # service name, but we use just "inspector".
    conf = dict(CONF)
    conf['ironic-inspector'] = conf.pop('inspector')
    # TODO(pas-ha) investigate possibility of passing user context here,
    # similar to what neutron/glance-related code does
    return openstack.connection.Connection(
        session=session,
        oslo_conf=conf).baremetal_introspection


def _get_callback_endpoint(client):
    root = CONF.inspector.callback_endpoint_override or client.get_endpoint()
    if root == 'mdns':
        return root

    parts = urlparse.urlsplit(root)
    is_loopback = False
    try:
        # ip_address requires a unicode string on Python 2
        is_loopback = ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:  # host name
        is_loopback = (parts.hostname == 'localhost')

    if is_loopback:
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

    if CONF.inspector.power_off:
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
                   'iface': task.node.boot_interface,
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
                   'iface': task.node.network_interface,
                   'exc': e})
        if raise_exc:
            raise
        return False

    return True


def _parse_kernel_params():
    """Parse kernel params from the configuration."""
    result = {}
    for s in shlex.split(CONF.inspector.extra_kernel_params):
        try:
            key, value = s.split('=', 1)
        except ValueError:
            raise exception.InvalidParameterValue(
                _('Invalid key-value pair in extra_kernel_params: %s') % s)
        result[key] = value
    return result


def _start_managed_inspection(task):
    """Start inspection managed by ironic."""
    try:
        client = _get_client(task.context)
        endpoint = _get_callback_endpoint(client)
        params = dict(_parse_kernel_params(),
                      **{'ipa-inspection-callback-url': endpoint})
        if CONF.deploy.fast_track:
            params['ipa-api-url'] = deploy_utils.get_ironic_api_url()

        cond_utils.node_power_action(task, states.POWER_OFF)
        with cond_utils.power_state_for_network_configuration(task):
            task.driver.network.add_inspection_network(task)
        task.driver.boot.prepare_ramdisk(task, ramdisk_params=params)
        client.start_introspection(task.node.uuid, manage_boot=False)
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
        _parse_kernel_params()
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
            enabled_macs = task.driver.management.get_mac_addresses(task)
            if enabled_macs:
                inspect_utils.create_ports_if_not_exist(
                    task, enabled_macs, get_mac_address=lambda x: x[0])
            else:
                LOG.warning("Not attempting to create any port as no NICs "
                            "were discovered in 'enabled' state for node "
                            "%(node)s: %(mac_data)s",
                            {'mac_data': enabled_macs,
                             'node': task.node.uuid})

        except exception.UnsupportedDriverExtension:
            LOG.info('Pre-creating ports prior to inspection not supported'
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
        _get_client(task.context).abort_introspection(node_uuid)

    @periodics.periodic(spacing=CONF.inspector.status_check_period)
    def _periodic_check_result(self, manager, context):
        """Periodic task checking results of inspection."""
        filters = {'provision_state': states.INSPECTWAIT}
        node_iter = manager.iter_nodes(filters=filters)

        for node_uuid, driver, conductor_group in node_iter:
            try:
                lock_purpose = 'checking hardware inspection status'
                with task_manager.acquire(context, node_uuid,
                                          shared=True,
                                          purpose=lock_purpose) as task:
                    _check_status(task)
            except (exception.NodeLocked, exception.NodeNotFound):
                continue


def _start_inspection(node_uuid, context):
    """Call to inspector to start inspection."""
    try:
        _get_client(context).start_introspection(node_uuid)
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
        status = _get_client(task.context).get_introspection(node.uuid)
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
