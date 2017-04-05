# Copyright 2016 Red Hat, Inc.
#
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

from oslo_config import cfg
from oslo_log import log
import pecan
from pecan import rest
from six.moves import http_client
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers.v1 import node as node_ctl
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common import policy
from ironic.common import states
from ironic.common import utils
from ironic import objects


CONF = cfg.CONF
LOG = log.getLogger(__name__)

_LOOKUP_RETURN_FIELDS = ('uuid', 'properties', 'instance_info',
                         'driver_internal_info')
_LOOKUP_ALLOWED_STATES = {states.DEPLOYING, states.DEPLOYWAIT,
                          states.CLEANING, states.CLEANWAIT,
                          states.INSPECTING}


def config():
    return {
        'metrics': {
            'backend': CONF.metrics.agent_backend,
            'prepend_host': CONF.metrics.agent_prepend_host,
            'prepend_uuid': CONF.metrics.agent_prepend_uuid,
            'prepend_host_reverse': CONF.metrics.agent_prepend_host_reverse,
            'global_prefix': CONF.metrics.agent_global_prefix
        },
        'metrics_statsd': {
            'statsd_host': CONF.metrics_statsd.agent_statsd_host,
            'statsd_port': CONF.metrics_statsd.agent_statsd_port
        },
        'heartbeat_timeout': CONF.api.ramdisk_heartbeat_timeout
    }


class LookupResult(base.APIBase):
    """API representation of the node lookup result."""

    node = node_ctl.Node
    """The short node representation."""

    config = {wtypes.text: types.jsontype}
    """The configuration to pass to the ramdisk."""

    @classmethod
    def sample(cls):
        return cls(node=node_ctl.Node.sample(),
                   config={'heartbeat_timeout': 600})

    @classmethod
    def convert_with_links(cls, node):
        node = node_ctl.Node.convert_with_links(node, _LOOKUP_RETURN_FIELDS)
        return cls(node=node, config=config())


class LookupController(rest.RestController):
    """Controller handling node lookup for a deploy ramdisk."""

    @expose.expose(LookupResult, types.listtype, types.uuid)
    def get_all(self, addresses=None, node_uuid=None):
        """Look up a node by its MAC addresses and optionally UUID.

        If the "restrict_lookup" option is set to True (the default), limit
        the search to nodes in certain transient states (e.g. deploy wait).

        :param addresses: list of MAC addresses for a node.
        :param node_uuid: UUID of a node.
        :raises: NotFound if requested API version does not allow this
            endpoint.
        :raises: NotFound if suitable node was not found or node's provision
            state is not allowed for the lookup.
        :raises: IncompleteLookup if neither node UUID nor any valid MAC
            address was provided.
        """
        if not api_utils.allow_ramdisk_endpoints():
            raise exception.NotFound()

        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:driver:ipa_lookup', cdict, cdict)

        # Validate the list of MAC addresses
        if addresses is None:
            addresses = []

        valid_addresses = []
        invalid_addresses = []
        for addr in addresses:
            try:
                mac = utils.validate_and_normalize_mac(addr)
                valid_addresses.append(mac)
            except exception.InvalidMAC:
                invalid_addresses.append(addr)

        if invalid_addresses:
            node_log = ('' if not node_uuid
                        else '(Node UUID: %s)' % node_uuid)
            LOG.warning('The following MAC addresses "%(addrs)s" are '
                        'invalid and will be ignored by the lookup '
                        'request %(node)s',
                        {'addrs': ', '.join(invalid_addresses),
                         'node': node_log})

        if not valid_addresses and not node_uuid:
            raise exception.IncompleteLookup()

        try:
            if node_uuid:
                node = objects.Node.get_by_uuid(
                    pecan.request.context, node_uuid)
            else:
                node = objects.Node.get_by_port_addresses(
                    pecan.request.context, valid_addresses)
        except exception.NotFound:
            # NOTE(dtantsur): we are reraising the same exception to make sure
            # we don't disclose the difference between nodes that are not found
            # at all and nodes in a wrong state by different error messages.
            raise exception.NotFound()

        if (CONF.api.restrict_lookup and
                node.provision_state not in _LOOKUP_ALLOWED_STATES):
            raise exception.NotFound()

        return LookupResult.convert_with_links(node)


class HeartbeatController(rest.RestController):
    """Controller handling heartbeats from deploy ramdisk."""

    @expose.expose(None, types.uuid_or_name, wtypes.text,
                   status_code=http_client.ACCEPTED)
    def post(self, node_ident, callback_url):
        """Process a heartbeat from the deploy ramdisk.

        :param node_ident: the UUID or logical name of a node.
        :param callback_url: the URL to reach back to the ramdisk.
        :raises: NodeNotFound if node with provided UUID or name was not found.
        :raises: InvalidUuidOrName if node_ident is not valid name or UUID.
        :raises: NoValidHost if RPC topic for node could not be retrieved.
        :raises: NotFound if requested API version does not allow this
            endpoint.
        """
        if not api_utils.allow_ramdisk_endpoints():
            raise exception.NotFound()

        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:ipa_heartbeat', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)

        try:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = http_client.BAD_REQUEST
            raise

        pecan.request.rpcapi.heartbeat(pecan.request.context,
                                       rpc_node.uuid, callback_url,
                                       topic=topic)
