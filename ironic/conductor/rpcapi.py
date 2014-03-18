# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
Client side of the conductor RPC API.
"""

from oslo.config import cfg

from ironic.common import exception
from ironic.common import hash_ring as hash
from ironic.conductor import manager
from ironic.db import api as dbapi
from ironic.objects import base as objects_base
import ironic.openstack.common.rpc.proxy

# NOTE(max_lobur): This is temporary override for Oslo setting defined in
# ironic.openstack.common.rpc.__init__.py. Should stay while Oslo is not fixed.
# *The setting shows what exceptions can be deserialized from RPC response.
# *This won't be reflected in ironic.conf.sample
# TODO(max_lobur): cover this by an integration test as
# described in https://bugs.launchpad.net/ironic/+bug/1252824
cfg.CONF.set_default('allowed_rpc_exception_modules',
                     ['ironic.common.exception',
                      'exceptions', ])


class ConductorAPI(ironic.openstack.common.rpc.proxy.RpcProxy):
    """Client side of the conductor RPC API.

    API version history:

        1.0 - Initial version.
              Included get_node_power_status
        1.1 - Added update_node and start_power_state_change.
        1.2 - Added vendor_passhthru.
        1.3 - Rename start_power_state_change to change_node_power_state.
        1.4 - Added do_node_deploy and do_node_tear_down.
        1.5 - Added validate_driver_interfaces.
        1.6 - change_node_power_state, do_node_deploy and do_node_tear_down
              accept node id instead of node object.
        1.7 - Added topic parameter to RPC methods.
        1.8 - Added change_node_maintenance_mode.
        1.9 - Added destroy_node.
        1.10 - Remove get_node_power_state
        1.11 - Added get_console_information, set_console_mode.
        1.12 - validate_vendor_action, do_vendor_action replaced by single
              vendor_passthru method.
        1.13 - Added update_port.

    """

    RPC_API_VERSION = '1.13'

    def __init__(self, topic=None):
        if topic is None:
            topic = manager.MANAGER_TOPIC

        # Initialize consistent hash ring
        self.hash_rings = {}
        d2c = dbapi.get_instance().get_active_driver_dict()
        for driver in d2c.keys():
            self.hash_rings[driver] = hash.HashRing(d2c[driver])

        super(ConductorAPI, self).__init__(
                topic=topic,
                serializer=objects_base.IronicObjectSerializer(),
                default_version=self.RPC_API_VERSION)

    def get_topic_for(self, node):
        """Get the RPC topic for the conductor service which the node
        is mapped to.

        :param node: a node object.
        :returns: an RPC topic string.
        :raises: NoValidHost

        """
        try:
            ring = self.hash_rings[node.driver]
            dest = ring.get_hosts(node.uuid)
            return self.topic + "." + dest[0]
        except KeyError:
            reason = (_('No conductor service registered which supports '
                        'driver %s.') % node.driver)
            raise exception.NoValidHost(reason=reason)

    def update_node(self, context, node_obj, topic=None):
        """Synchronously, have a conductor update the node's information.

        Update the node's information in the database and return a node object.
        The conductor will lock the node while it validates the supplied
        information. If driver_info is passed, it will be validated by
        the core drivers. If instance_uuid is passed, it will be set or unset
        only if the node is properly configured.

        Note that power_state should not be passed via this method.
        Use change_node_power_state for initiating driver actions.

        :param context: request context.
        :param node_obj: a changed (but not saved) node object.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: updated node object, including all fields.

        """
        return self.call(context,
                         self.make_msg('update_node',
                                       node_obj=node_obj),
                         topic=topic or self.topic)

    def change_node_power_state(self, context, node_id, new_state, topic=None):
        """Synchronously, acquire lock and start the conductor background task
        to change power state of a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param new_state: one of ironic.common.states power state values
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        return self.call(context,
                         self.make_msg('change_node_power_state',
                                       node_id=node_id,
                                       new_state=new_state),
                         topic=topic or self.topic)

    def vendor_passthru(self, context, node_id, driver_method, info,
                        topic=None):
        """Synchronously, acquire lock, validate given parameters and start
        the conductor background task for specified vendor action.

        :param context: request context.
        :param node_id: node id or uuid.
        :param driver_method: name of method for driver.
        :param info: info for node driver.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if supplied info is not valid.
        :raises: UnsupportedDriverExtension if current driver does not have
                 vendor interface.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        topic = topic or self.topic
        return self.call(context,
                         self.make_msg('vendor_passthru',
                                       node_id=node_id,
                                       driver_method=driver_method,
                                       info=info),
                         topic=topic)

    def do_node_deploy(self, context, node_id, topic=None):
        """Signal to conductor service to perform a deployment.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InstanceDeployFailure
        :raises: InvalidParameterValue if validation fails
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        The node must already be configured and in the appropriate
        undeployed state before this method is called.

        """
        return self.call(context,
                         self.make_msg('do_node_deploy',
                                       node_id=node_id),
                         topic=topic or self.topic)

    def do_node_tear_down(self, context, node_id, topic=None):
        """Signal to conductor service to tear down a deployment.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InstanceDeployFailure
        :raises: InvalidParameterValue if validation fails
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        The node must already be configured and in the appropriate
        deployed state before this method is called.

        """
        return self.call(context,
                        self.make_msg('do_node_tear_down',
                                      node_id=node_id),
                        topic=topic or self.topic)

    def validate_driver_interfaces(self, context, node_id, topic=None):
        """Validate the `core` and `standardized` interfaces for drivers.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: a dictionary containing the results of each
                  interface validation.

        """
        return self.call(context,
                         self.make_msg('validate_driver_interfaces',
                                       node_id=node_id),
                         topic=topic or self.topic)

    def change_node_maintenance_mode(self, context, node_id, mode, topic=None):
        """Set node maintenance mode on or off.

        :param context: request context.
        :param node_id: node id or uuid.
        :param mode: True or False.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: a node object.
        :raises: NodeMaintenanceFailure.

        """
        return self.call(context,
                         self.make_msg('change_node_maintenance_mode',
                                       node_id=node_id,
                                       mode=mode),
                         topic=topic or self.topic)

    def destroy_node(self, context, node_id, topic=None):
        """Delete a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeAssociated if the node contains an instance
            associated with it.
        :raises: NodeInWrongPowerState if the node is not powered off.

        """
        return self.call(context,
                         self.make_msg('destroy_node',
                                       node_id=node_id),
                         topic=topic or self.topic)

    def get_console_information(self, context, node_id, topic=None):
        """Get connection information about the console.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        """
        return self.call(context,
                         self.make_msg('get_console_information',
                                       node_id=node_id),
                         topic=topic or self.topic)

    def set_console_mode(self, context, node_id, enabled, topic=None):
        """Enable/Disable the console.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :param enabled: Boolean value; whether the console is enabled or
                        disabled.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        """
        return self.call(context,
                         self.make_msg('set_console_mode',
                                       node_id=node_id,
                                       enabled=enabled),
                         topic=topic or self.topic)

    def update_port(self, context, port_obj, topic=None):
        """Synchronously, have a conductor update the port's information.

        Update the port's information in the database and return a port object.
        The conductor will lock related node and trigger specific driver
        actions if they are needed.

        :param context: request context.
        :param port_obj: a changed (but not saved) port object.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: updated port object, including all fields.

        """
        return self.call(context,
                         self.make_msg('update_port',
                                       port_obj=port_obj),
                         topic=topic or self.topic)
