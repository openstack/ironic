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

import eventlet
from futurist import periodics
import openstack
from oslo_log import log as logging

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers import base


LOG = logging.getLogger(__name__)

_INSPECTOR_SESSION = None


def _get_inspector_session(**kwargs):
    global _INSPECTOR_SESSION
    if not _INSPECTOR_SESSION:
        if CONF.auth_strategy == 'noauth':
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
        """
        # NOTE(deva): this is not callable if inspector is disabled
        #             so don't raise an exception -- just pass.
        pass

    def inspect_hardware(self, task):
        """Inspect hardware to obtain the hardware properties.

        This particular implementation only starts inspection using
        ironic-inspector. Results will be checked in a periodic task.

        :param task: a task from TaskManager.
        :returns: states.INSPECTWAIT
        """
        LOG.debug('Starting inspection for node %(uuid)s using '
                  'ironic-inspector', {'uuid': task.node.uuid})

        # NOTE(dtantsur): we're spawning a short-living green thread so that
        # we can release a lock as soon as possible and allow ironic-inspector
        # to operate on a node.
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
        LOG.exception('Exception during contacting ironic-inspector '
                      'for inspection of node %(node)s: %(err)s',
                      {'node': node_uuid, 'err': exc})
        # NOTE(dtantsur): if acquire fails our last option is to rely on
        # timeout
        lock_purpose = 'recording hardware inspection error'
        with task_manager.acquire(context, node_uuid,
                                  purpose=lock_purpose) as task:
            task.node.last_error = _('Failed to start inspection: %s') % exc
            task.process_event('fail')
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
        node.last_error = (_('ironic-inspector inspection failed: %s')
                           % status.error)
        task.process_event('fail')
    elif status.is_finished:
        LOG.info('Inspection finished successfully for node %s', node.uuid)
        task.process_event('done')
