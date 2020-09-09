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

from http import client as http_client

from oslo_config import cfg
from oslo_log import log
from pecan import rest

from ironic import api
from ironic.api.controllers.v1 import node as node_ctl
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states
from ironic.common import utils
from ironic import objects


CONF = cfg.CONF
LOG = log.getLogger(__name__)

_LOOKUP_RETURN_FIELDS = ['uuid', 'properties', 'instance_info',
                         'driver_internal_info']


def config(token):
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
        'heartbeat_timeout': CONF.api.ramdisk_heartbeat_timeout,
        'agent_token': token,
        # Since this is for the Victoria release, we send this as an
        # explicit True statement for newer agents to lock the setting
        # and behavior into place.
        'agent_token_required': True,
    }


def convert_with_links(node):
    token = node.driver_internal_info.get('agent_secret_token')
    node = node_ctl.node_convert_with_links(node, _LOOKUP_RETURN_FIELDS)
    return {'node': node, 'config': config(token)}


class LookupController(rest.RestController):
    """Controller handling node lookup for a deploy ramdisk."""

    @property
    def lookup_allowed_states(self):
        if CONF.deploy.fast_track:
            return states.FASTTRACK_LOOKUP_ALLOWED_STATES
        return states.LOOKUP_ALLOWED_STATES

    @method.expose()
    @args.validate(addresses=args.string_list, node_uuid=args.uuid)
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

        cdict = api.request.context.to_policy_values()
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
                    api.request.context, node_uuid)
            else:
                node = objects.Node.get_by_port_addresses(
                    api.request.context, valid_addresses)
        except exception.NotFound:
            # NOTE(dtantsur): we are reraising the same exception to make sure
            # we don't disclose the difference between nodes that are not found
            # at all and nodes in a wrong state by different error messages.
            raise exception.NotFound()

        if (CONF.api.restrict_lookup
                and node.provision_state not in self.lookup_allowed_states):
            raise exception.NotFound()

        if api_utils.allow_agent_token():
            try:
                topic = api.request.rpcapi.get_topic_for(node)
            except exception.NoValidHost as e:
                e.code = http_client.BAD_REQUEST
                raise

            found_node = api.request.rpcapi.get_node_with_token(
                api.request.context, node.uuid, topic=topic)
        else:
            found_node = node
        return convert_with_links(found_node)


class HeartbeatController(rest.RestController):
    """Controller handling heartbeats from deploy ramdisk."""

    @method.expose(status_code=http_client.ACCEPTED)
    @args.validate(node_ident=args.uuid_or_name, callback_url=args.string,
                   agent_version=args.string, agent_token=args.string,
                   agent_verify_ca=args.string)
    def post(self, node_ident, callback_url, agent_version=None,
             agent_token=None, agent_verify_ca=None):
        """Process a heartbeat from the deploy ramdisk.

        :param node_ident: the UUID or logical name of a node.
        :param callback_url: the URL to reach back to the ramdisk.
        :param agent_version: The version of the agent that is heartbeating.
            ``None`` indicates that the agent that is heartbeating is a version
            before sending agent_version was introduced so agent v3.0.0 (the
            last release before sending agent_version was introduced) will be
            assumed.
        :param agent_token: randomly generated validation token.
        :param agent_verify_ca: TLS certificate to use to connect to the agent.
        :raises: NodeNotFound if node with provided UUID or name was not found.
        :raises: InvalidUuidOrName if node_ident is not valid name or UUID.
        :raises: NoValidHost if RPC topic for node could not be retrieved.
        :raises: NotFound if requested API version does not allow this
            endpoint.
        """
        if not api_utils.allow_ramdisk_endpoints():
            raise exception.NotFound()

        if agent_version and not api_utils.allow_agent_version_in_heartbeat():
            raise exception.InvalidParameterValue(
                _('Field "agent_version" not recognised'))

        cdict = api.request.context.to_policy_values()
        policy.authorize('baremetal:node:ipa_heartbeat', cdict, cdict)

        if (agent_verify_ca is not None
                and not api_utils.allow_verify_ca_in_heartbeat()):
            raise exception.InvalidParameterValue(
                _('Field "agent_verify_ca" not recognised in this version'))

        rpc_node = api_utils.get_rpc_node_with_suffix(node_ident)
        dii = rpc_node['driver_internal_info']
        agent_url = dii.get('agent_url')
        # If we have an agent_url on file, and we get something different
        # we should fail because this is unexpected behavior of the agent.
        if agent_url is not None and agent_url != callback_url:
            LOG.error('Received heartbeat for node %(node)s with '
                      'callback URL %(url)s. This is not expected, '
                      'and the heartbeat will not be processed.',
                      {'node': rpc_node.uuid, 'url': callback_url})
            raise exception.Invalid(
                _('Detected change in ramdisk provided '
                  '"callback_url"'))
        # NOTE(TheJulia): If tokens are required, lets go ahead and fail the
        # heartbeat very early on.
        if agent_token is None:
            LOG.error('Agent heartbeat received for node %(node)s '
                      'without an agent token.', {'node': node_ident})
            raise exception.InvalidParameterValue(
                _('Agent token is required for heartbeat processing.'))

        try:
            topic = api.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = http_client.BAD_REQUEST
            raise

        api.request.rpcapi.heartbeat(
            api.request.context, rpc_node.uuid, callback_url,
            agent_version, agent_token, agent_verify_ca, topic=topic)
