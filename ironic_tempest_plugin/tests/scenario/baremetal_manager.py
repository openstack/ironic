# Copyright 2012 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from tempest.common import waiters
from tempest import config
from tempest.lib import exceptions as lib_exc
from tempest.scenario import manager  # noqa
import tempest.test

from ironic_tempest_plugin import clients

CONF = config.CONF


# power/provision states as of icehouse
class BaremetalPowerStates(object):
    """Possible power states of an Ironic node."""
    POWER_ON = 'power on'
    POWER_OFF = 'power off'
    REBOOT = 'rebooting'
    SUSPEND = 'suspended'


class BaremetalProvisionStates(object):
    """Possible provision states of an Ironic node."""
    ENROLL = 'enroll'
    NOSTATE = None
    AVAILABLE = 'available'
    INIT = 'initializing'
    ACTIVE = 'active'
    BUILDING = 'building'
    DEPLOYWAIT = 'wait call-back'
    DEPLOYING = 'deploying'
    DEPLOYFAIL = 'deploy failed'
    DEPLOYDONE = 'deploy complete'
    DELETING = 'deleting'
    DELETED = 'deleted'
    ERROR = 'error'


class BaremetalScenarioTest(manager.ScenarioTest):

    credentials = ['primary', 'admin']

    @classmethod
    def skip_checks(cls):
        super(BaremetalScenarioTest, cls).skip_checks()
        if not CONF.baremetal.driver_enabled:
            msg = 'Ironic not available or Ironic compute driver not enabled'
            raise cls.skipException(msg)

    @classmethod
    def setup_clients(cls):
        super(BaremetalScenarioTest, cls).setup_clients()

        cls.baremetal_client = clients.Manager().baremetal_client

    @classmethod
    def resource_setup(cls):
        super(BaremetalScenarioTest, cls).resource_setup()
        # allow any issues obtaining the node list to raise early
        cls.baremetal_client.list_nodes()

    def _node_state_timeout(self, node_id, state_attr,
                            target_states, timeout=10, interval=1):
        if not isinstance(target_states, list):
            target_states = [target_states]

        def check_state():
            node = self.get_node(node_id=node_id)
            if node.get(state_attr) in target_states:
                return True
            return False

        if not tempest.test.call_until_true(check_state, timeout, interval):
            msg = ("Timed out waiting for node %s to reach %s state(s) %s" %
                   (node_id, state_attr, target_states))
            raise lib_exc.TimeoutException(msg)

    def wait_provisioning_state(self, node_id, state, timeout, interval=1):
        self._node_state_timeout(
            node_id=node_id, state_attr='provision_state',
            target_states=state, timeout=timeout, interval=interval)

    def wait_power_state(self, node_id, state):
        self._node_state_timeout(
            node_id=node_id, state_attr='power_state',
            target_states=state, timeout=CONF.baremetal.power_timeout)

    def wait_node(self, instance_id):
        """Waits for a node to be associated with instance_id."""

        def _get_node():
            node = None
            try:
                node = self.get_node(instance_id=instance_id)
            except lib_exc.NotFound:
                pass
            return node is not None

        if (not tempest.test.call_until_true(
            _get_node, CONF.baremetal.association_timeout, 1)):
            msg = ('Timed out waiting to get Ironic node by instance id %s'
                   % instance_id)
            raise lib_exc.TimeoutException(msg)

    def get_node(self, node_id=None, instance_id=None):
        if node_id:
            _, body = self.baremetal_client.show_node(node_id)
            return body
        elif instance_id:
            _, body = self.baremetal_client.show_node_by_instance_uuid(
                instance_id)
            if body['nodes']:
                return body['nodes'][0]

    def get_ports(self, node_uuid):
        ports = []
        _, body = self.baremetal_client.list_node_ports(node_uuid)
        for port in body['ports']:
            _, p = self.baremetal_client.show_port(port['uuid'])
            ports.append(p)
        return ports

    def add_keypair(self):
        self.keypair = self.create_keypair()

    def verify_connectivity(self, ip=None):
        if ip:
            dest = self.get_remote_client(ip)
        else:
            dest = self.get_remote_client(self.instance)
        dest.validate_authentication()

    def boot_instance(self, clients=None, keypair=None,
                      net_id=None, fixed_ip=None):
        if clients is None:
            servers_client = self.servers_client
        else:
            servers_client = clients.servers_client
        if keypair is None:
            keypair = self.keypair

        if any([net_id, fixed_ip]):
            network = {}
            if net_id:
                network['uuid'] = net_id
            if fixed_ip:
                network['fixed_ip'] = fixed_ip
            instance = self.create_server(
                key_name=keypair['name'],
                networks=[network],
                clients=clients
            )
        else:
            instance = self.create_server(
                key_name=keypair['name'],
                clients=clients
            )

        self.wait_node(instance['id'])
        node = self.get_node(instance_id=instance['id'])

        self.wait_power_state(node['uuid'], BaremetalPowerStates.POWER_ON)

        self.wait_provisioning_state(
            node['uuid'],
            [BaremetalProvisionStates.DEPLOYWAIT,
             BaremetalProvisionStates.ACTIVE],
            timeout=CONF.baremetal.deploywait_timeout)

        self.wait_provisioning_state(node['uuid'],
                                     BaremetalProvisionStates.ACTIVE,
                                     timeout=CONF.baremetal.active_timeout,
                                     interval=30)

        waiters.wait_for_server_status(servers_client,
                                       instance['id'], 'ACTIVE')
        node = self.get_node(instance_id=instance['id'])
        instance = servers_client.show_server(instance['id'])['server']

        return instance, node

    def terminate_instance(self, instance, servers_client=None):
        if servers_client is None:
            servers_client = self.servers_client

        node = self.get_node(instance_id=instance['id'])
        servers_client.delete_server(instance['id'])
        self.wait_power_state(node['uuid'],
                              BaremetalPowerStates.POWER_OFF)
        self.wait_provisioning_state(
            node['uuid'],
            [BaremetalProvisionStates.NOSTATE,
             BaremetalProvisionStates.AVAILABLE],
            timeout=CONF.baremetal.unprovision_timeout,
            interval=30)
