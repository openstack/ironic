#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Functionality related to allocations."""

import random

from ironic_lib import metrics_utils
from oslo_config import cfg
from oslo_log import log
import retrying

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic import objects


CONF = cfg.CONF
LOG = log.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)


def do_allocate(context, allocation):
    """Process the allocation.

    This call runs in a separate thread on a conductor. It finds suitable
    nodes for the allocation and reserves one of them.

    This call does not raise exceptions since it's designed to work
    asynchronously.

    :param context: an admin context
    :param allocation: an allocation object
    """
    try:
        nodes = _candidate_nodes(context, allocation)
        _allocate_node(context, allocation, nodes)
    except exception.AllocationFailed as exc:
        LOG.error(str(exc))
        _allocation_failed(allocation, exc)
    except Exception as exc:
        LOG.exception("Unexpected exception during processing of "
                      "allocation %s", allocation.uuid)
        reason = _("Unexpected exception during allocation: %s") % exc
        _allocation_failed(allocation, reason)


def verify_node_for_deallocation(node, allocation):
    """Verify that allocation can be removed for the node.

    :param node: a node object
    :param allocation: an allocation object associated with the node
    """
    if node.maintenance:
        # Allocations can always be removed in the maintenance mode.
        return

    if (node.target_provision_state
            and node.provision_state not in states.UPDATE_ALLOWED_STATES):
        msg = (_("Cannot remove allocation %(uuid)s for node %(node)s, "
                 "because the node is in state %(state)s where updates are "
                 "not allowed (and maintenance mode is off)") %
               {'node': node.uuid, 'uuid': allocation.uuid,
                'state': node.provision_state})
        raise exception.InvalidState(msg)

    if node.provision_state == states.ACTIVE:
        msg = (_("Cannot remove allocation %(uuid)s for node %(node)s, "
                 "because the node is active (and maintenance mode is off)") %
               {'node': node.uuid, 'uuid': allocation.uuid})
        raise exception.InvalidState(msg)


def _allocation_failed(allocation, reason):
    """Failure handler for the allocation."""
    try:
        allocation.state = states.ERROR
        allocation.last_error = str(reason)
        allocation.save()
    except Exception:
        LOG.exception('Could not save the failed allocation %s',
                      allocation.uuid)


def _traits_match(traits, node):
    return {t.trait for t in node.traits.objects}.issuperset(traits)


def _candidate_nodes(context, allocation):
    """Get a list of candidate nodes for the allocation."""
    filters = {'resource_class': allocation.resource_class,
               'provision_state': states.AVAILABLE,
               'associated': False,
               'with_power_state': True,
               'maintenance': False}
    if allocation.candidate_nodes:
        # NOTE(dtantsur): we assume that candidate_nodes were converted to
        # UUIDs on the API level.
        filters['uuid_in'] = allocation.candidate_nodes

    nodes = objects.Node.list(context, filters=filters)

    if not nodes:
        if allocation.candidate_nodes:
            error = _("none of the requested nodes are available and match "
                      "the resource class %s") % allocation.resource_class
        else:
            error = _("no available nodes match the resource class %s") % (
                allocation.resource_class)
        raise exception.AllocationFailed(uuid=allocation.uuid, error=error)

    # TODO(dtantsur): database-level filtering?
    if allocation.traits:
        traits = set(allocation.traits)
        nodes = [n for n in nodes if _traits_match(traits, n)]
        if not nodes:
            error = (_("no suitable nodes have the requested traits %s") %
                     ', '.join(traits))
            raise exception.AllocationFailed(uuid=allocation.uuid, error=error)

    # NOTE(dtantsur): make sure that parallel allocations do not try the nodes
    # in the same order.
    random.shuffle(nodes)

    LOG.debug('%(count)d nodes are candidates for allocation %(uuid)s',
              {'count': len(nodes), 'uuid': allocation.uuid})
    return nodes


def _verify_node(node, allocation):
    """Check that the node still satisfiest the request."""
    if node.maintenance:
        LOG.debug('Node %s is now in maintenance, skipping',
                  node.uuid)
        return False

    if node.instance_uuid:
        LOG.debug('Node %(node)s is already associated with instance '
                  '%(inst)s, skipping',
                  {'node': node.uuid, 'inst': node.instance_uuid})
        return False

    if node.provision_state != states.AVAILABLE:
        LOG.debug('Node %s is no longer available, skipping',
                  node.uuid)
        return False

    if node.resource_class != allocation.resource_class:
        LOG.debug('Resource class of node %(node)s no longer '
                  'matches requested resource class %(rsc)s for '
                  'allocation %(uuid)s, skipping',
                  {'node': node.uuid,
                   'rsc': allocation.resource_class,
                   'uuid': allocation.uuid})
        return False

    if allocation.traits and not _traits_match(set(allocation.traits), node):
        LOG.debug('List of traits of node %(node)s no longer '
                  'matches requested traits %(traits)s for '
                  'allocation %(uuid)s, skipping',
                  {'node': node.uuid,
                   'traits': allocation.traits,
                   'uuid': allocation.uuid})
        return False

    return True


# NOTE(dtantsur): instead of trying to allocate each node
# node_locked_retry_attempt times, we try to allocate *any* node the same
# number of times. This avoids getting stuck on a node reserved e.g. for power
# sync periodic task.
@retrying.retry(
    retry_on_exception=lambda e: isinstance(e, exception.AllocationFailed),
    stop_max_attempt_number=CONF.conductor.node_locked_retry_attempts,
    wait_fixed=CONF.conductor.node_locked_retry_interval * 1000)
def _allocate_node(context, allocation, nodes):
    """Go through the list of nodes and try to allocate one of them."""
    retry_nodes = []
    for node in nodes:
        try:
            # NOTE(dtantsur): retries are done for all nodes above, so disable
            # per-node retry. Also disable loading the driver, since the
            # current conductor may not have the requried hardware type or
            # interfaces (it's picked at random).
            with task_manager.acquire(context, node.uuid, shared=False,
                                      retry=False, load_driver=False,
                                      purpose='allocating') as task:
                # NOTE(dtantsur): double-check the node details, since they
                # could have changed before we acquired the lock.
                if not _verify_node(task.node, allocation):
                    continue

                allocation.node_id = task.node.id
                allocation.state = states.ACTIVE
                # NOTE(dtantsur): the node.instance_uuid and allocation_id are
                # updated inside of the save() call within the same
                # transaction to avoid races. NodeAssociated can be raised if
                # another process allocates this node first.
                allocation.save()
                LOG.info('Node %(node)s has been successfully reserved for '
                         'allocation %(uuid)s',
                         {'node': node.uuid, 'uuid': allocation.uuid})
                return allocation
        except exception.NodeLocked:
            LOG.debug('Node %s is currently locked, moving to the next one',
                      node.uuid)
            retry_nodes.append(node)
        except exception.NodeAssociated:
            LOG.debug('Node %s is already associated, moving to the next one',
                      node.uuid)

    # NOTE(dtantsur): rewrite the passed list to only contain the nodes that
    # are worth retrying. Do not include nodes that are no longer suitable.
    nodes[:] = retry_nodes

    if nodes:
        error = _('could not reserve any of %d suitable nodes') % len(nodes)
    else:
        error = _('all nodes were filtered out during reservation')

    raise exception.AllocationFailed(uuid=allocation.uuid, error=error)
