# -*- coding: utf-8 -*-
#
# Copyright 2014 Rackspace, Inc.
# Copyright 2015 Red Hat, Inc.
# All Rights Reserved.
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


import time

from oslo_config import cfg
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.common import utils
from ironic.drivers import base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic import objects
from ironic.openstack.common import log

agent_opts = [
    cfg.IntOpt('heartbeat_timeout',
               default=300,
               help='Maximum interval (in seconds) for agent heartbeats.'),
    ]

CONF = cfg.CONF
CONF.register_opts(agent_opts, group='agent')

LOG = log.getLogger(__name__)


def _time():
    """Broken out for testing."""
    return time.time()


def _get_client():
    client = agent_client.AgentClient()
    return client


class BaseAgentVendor(base.VendorInterface):

    def __init__(self):
        self.supported_payload_versions = ['2']
        self._client = _get_client()

    def continue_deploy(self, task, **kwargs):
        """Continues the deployment of baremetal node.

        This method continues the deployment of the baremetal node after
        the ramdisk have been booted.

        :param task: a TaskManager instance

        """
        pass

    def deploy_is_done(self, task):
        """Check if the deployment is already completed.

        :returns: True if the deployment is completed. False otherwise

        """
        pass

    def reboot_to_instance(self, task, **kwargs):
        """Method invoked after the deployment is completed.

        :param task: a TaskManager instance

        """
        pass

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        # NOTE(jroll) all properties are set by the driver,
        #             not by the operator.
        return {}

    def validate(self, task, method, **kwargs):
        """Validate the driver-specific Node deployment info.

        No validation necessary.

        :param task: a TaskManager instance
        :param method: method to be validated
        """
        pass

    def driver_validate(self, method, **kwargs):
        """Validate the driver deployment info.

        :param method: method to be validated.
        """
        version = kwargs.get('version')

        if not version:
            raise exception.MissingParameterValue(_('Missing parameter '
                                                    'version'))
        if version not in self.supported_payload_versions:
            raise exception.InvalidParameterValue(_('Unknown lookup '
                                                    'payload version: %s')
                                                    % version)

    @base.passthru(['POST'])
    def heartbeat(self, task, **kwargs):
        """Method for agent to periodically check in.

        The agent should be sending its agent_url (so Ironic can talk back)
        as a kwarg. kwargs should have the following format::

         {
             'agent_url': 'http://AGENT_HOST:AGENT_PORT'
         }

        AGENT_PORT defaults to 9999.
        """
        node = task.node
        driver_internal_info = node.driver_internal_info
        LOG.debug(
            'Heartbeat from %(node)s, last heartbeat at %(heartbeat)s.',
            {'node': node.uuid,
             'heartbeat': driver_internal_info.get('agent_last_heartbeat')})
        driver_internal_info['agent_last_heartbeat'] = int(_time())
        try:
            driver_internal_info['agent_url'] = kwargs['agent_url']
        except KeyError:
            raise exception.MissingParameterValue(_('For heartbeat operation, '
                                                    '"agent_url" must be '
                                                    'specified.'))

        node.driver_internal_info = driver_internal_info
        node.save()

        # Async call backs don't set error state on their own
        # TODO(jimrollenhagen) improve error messages here
        msg = _('Failed checking if deploy is done.')
        try:
            if node.provision_state == states.DEPLOYWAIT:
                msg = _('Node failed to get image for deploy.')
                self.continue_deploy(task, **kwargs)
            elif (node.provision_state == states.DEPLOYING and
                  self.deploy_is_done(task)):
                msg = _('Node failed to move to active state.')
                self.reboot_to_instance(task, **kwargs)
        except Exception:
            LOG.exception(_LE('Async exception for %(node)s: %(msg)s'),
                          {'node': node.uuid,
                           'msg': msg})
            deploy_utils.set_failed_state(task, msg)

    @base.driver_passthru(['POST'], async=False)
    def lookup(self, context, **kwargs):
        """Find a matching node for the agent.

        Method to be called the first time a ramdisk agent checks in. This
        can be because this is a node just entering decom or a node that
        rebooted for some reason. We will use the mac addresses listed in the
        kwargs to find the matching node, then return the node object to the
        agent. The agent can that use that UUID to use the node vendor
        passthru method.

        Currently, we don't handle the instance where the agent doesn't have
        a matching node (i.e. a brand new, never been in Ironic node).

        kwargs should have the following format::

         {
             "version": "2"
             "inventory": {
                 "interfaces": [
                     {
                         "name": "eth0",
                         "mac_address": "00:11:22:33:44:55",
                         "switch_port_descr": "port24"
                         "switch_chassis_descr": "tor1"
                     }, ...
                 ], ...
             }
         }

        The interfaces list should include a list of the non-IPMI MAC addresses
        in the form aa:bb:cc:dd:ee:ff.

        This method will also return the timeout for heartbeats. The driver
        will expect the agent to heartbeat before that timeout, or it will be
        considered down. This will be in a root level key called
        'heartbeat_timeout'

        :raises: NotFound if no matching node is found.
        :raises: InvalidParameterValue with unknown payload version
        """
        inventory = kwargs.get('inventory')
        interfaces = self._get_interfaces(inventory)
        mac_addresses = self._get_mac_addresses(interfaces)

        node = self._find_node_by_macs(context, mac_addresses)

        LOG.debug('Initial lookup for node %s succeeded.', node.uuid)

        # Only support additional hardware in v2 and above. Grab all the
        # top level keys in inventory that aren't interfaces and add them.
        # Nest it in 'hardware' to avoid namespace issues
        hardware = {
            'hardware': {
                'network': interfaces
            }
        }

        for key, value in kwargs.items():
            if key != 'interfaces':
                hardware['hardware'][key] = value

        return {
            'heartbeat_timeout': CONF.agent.heartbeat_timeout,
            'node': node
        }

    def _get_interfaces(self, inventory):
        interfaces = []
        try:
            interfaces = inventory['interfaces']
        except (KeyError, TypeError):
            raise exception.InvalidParameterValue(_(
                'Malformed network interfaces lookup: %s') % inventory)

        return interfaces

    def _get_mac_addresses(self, interfaces):
        """Returns MACs for the network devices."""
        mac_addresses = []

        for interface in interfaces:
            try:
                mac_addresses.append(utils.validate_and_normalize_mac(
                    interface.get('mac_address')))
            except exception.InvalidMAC:
                LOG.warning(_LW('Malformed MAC: %s'), interface.get(
                    'mac_address'))
        return mac_addresses

    def _find_node_by_macs(self, context, mac_addresses):
        """Get nodes for a given list of MAC addresses.

        Given a list of MAC addresses, find the ports that match the MACs
        and return the node they are all connected to.

        :raises: NodeNotFound if the ports point to multiple nodes or no
        nodes.
        """
        ports = self._find_ports_by_macs(context, mac_addresses)
        if not ports:
            raise exception.NodeNotFound(_(
                'No ports matching the given MAC addresses %sexist in the '
                'database.') % mac_addresses)
        node_id = self._get_node_id(ports)
        try:
            node = objects.Node.get_by_id(context, node_id)
        except exception.NodeNotFound:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Could not find matching node for the '
                                  'provided MACs %s.'), mac_addresses)

        return node

    def _find_ports_by_macs(self, context, mac_addresses):
        """Get ports for a given list of MAC addresses.

        Given a list of MAC addresses, find the ports that match the MACs
        and return them as a list of Port objects, or an empty list if there
        are no matches
        """
        ports = []
        for mac in mac_addresses:
            # Will do a search by mac if the mac isn't malformed
            try:
                port_ob = objects.Port.get_by_address(context, mac)
                ports.append(port_ob)

            except exception.PortNotFound:
                LOG.warning(_LW('MAC address %s not found in database'), mac)

        return ports

    def _get_node_id(self, ports):
        """Get a node ID for a list of ports.

        Given a list of ports, either return the node_id they all share or
        raise a NotFound if there are multiple node_ids, which indicates some
        ports are connected to one node and the remaining port(s) are connected
        to one or more other nodes.

        :raises: NodeNotFound if the MACs match multiple nodes. This
        could happen if you swapped a NIC from one server to another and
        don't notify Ironic about it or there is a MAC collision (since
        they're not guaranteed to be unique).
        """
        # See if all the ports point to the same node
        node_ids = set(port_ob.node_id for port_ob in ports)
        if len(node_ids) > 1:
            raise exception.NodeNotFound(_(
                'Ports matching mac addresses match multiple nodes. MACs: '
                '%(macs)s. Port ids: %(port_ids)s') %
                {'macs': [port_ob.address for port_ob in ports], 'port_ids':
                 [port_ob.uuid for port_ob in ports]}
            )

        # Only have one node_id left, return it.
        return node_ids.pop()
