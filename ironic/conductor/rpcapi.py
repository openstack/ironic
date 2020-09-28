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

import random

import oslo_messaging as messaging

from ironic.common import exception
from ironic.common import hash_ring
from ironic.common.i18n import _
from ironic.common.json_rpc import client as json_rpc
from ironic.common import release_mappings as versions
from ironic.common import rpc
from ironic.conductor import manager
from ironic.conf import CONF
from ironic.db import api as dbapi
from ironic.objects import base as objects_base


class ConductorAPI(object):
    """Client side of the conductor RPC API.

    API version history:

    |    1.0 - Initial version.
    |          Included get_node_power_status
    |    1.1 - Added update_node and start_power_state_change.
    |    1.2 - Added vendor_passthru.
    |    1.3 - Rename start_power_state_change to change_node_power_state.
    |    1.4 - Added do_node_deploy and do_node_tear_down.
    |    1.5 - Added validate_driver_interfaces.
    |    1.6 - change_node_power_state, do_node_deploy and do_node_tear_down
    |          accept node id instead of node object.
    |    1.7 - Added topic parameter to RPC methods.
    |    1.8 - Added change_node_maintenance_mode.
    |    1.9 - Added destroy_node.
    |    1.10 - Remove get_node_power_state
    |    1.11 - Added get_console_information, set_console_mode.
    |    1.12 - validate_vendor_action, do_vendor_action replaced by single
    |          vendor_passthru method.
    |    1.13 - Added update_port.
    |    1.14 - Added driver_vendor_passthru.
    |    1.15 - Added rebuild parameter to do_node_deploy.
    |    1.16 - Added get_driver_properties.
    |    1.17 - Added set_boot_device, get_boot_device and
    |          get_supported_boot_devices.
    |    1.18 - Remove change_node_maintenance_mode.
    |    1.19 - Change return value of vendor_passthru and
    |           driver_vendor_passthru
    |    1.20 - Added http_method parameter to vendor_passthru and
    |           driver_vendor_passthru
    |    1.21 - Added get_node_vendor_passthru_methods and
    |           get_driver_vendor_passthru_methods
    |    1.22 - Added configdrive parameter to do_node_deploy.
    |    1.23 - Added do_provisioning_action
    |    1.24 - Added inspect_hardware method
    |    1.25 - Added destroy_port
    |    1.26 - Added continue_node_clean
    |    1.27 - Convert continue_node_clean to cast
    |    1.28 - Change exceptions raised by destroy_node
    |    1.29 - Change return value of vendor_passthru and
    |           driver_vendor_passthru to a dictionary
    |    1.30 - Added set_target_raid_config and
    |           get_raid_logical_disk_properties
    |    1.31 - Added Versioned Objects indirection API methods:
    |           object_class_action_versions, object_action and
    |           object_backport_versions
    |    1.32 - Add do_node_clean
    |    1.33 - Added update and destroy portgroup.
    |    1.34 - Added heartbeat
    |    1.35 - Added destroy_volume_connector and update_volume_connector
    |    1.36 - Added create_node
    |    1.37 - Added destroy_volume_target and update_volume_target
    |    1.38 - Added vif_attach, vif_detach, vif_list
    |    1.39 - Added timeout optional parameter to change_node_power_state
    |    1.40 - Added inject_nmi
    |    1.41 - Added create_port
    |    1.42 - Added optional agent_version to heartbeat
    |    1.43 - Added do_node_rescue, do_node_unrescue and can_send_rescue
    |    1.44 - Added add_node_traits and remove_node_traits.
    |    1.45 - Added continue_node_deploy
    |    1.46 - Added reset_interfaces to update_node
    |    1.47 - Added support for conductor groups
    |    1.48 - Added allocation API
    |    1.49 - Added get_node_with_token and agent_token argument to
                heartbeat
    |    1.50 - Added set_indicator_state, get_indicator_state and
    |           get_supported_indicators.
    |    1.51 - Added agent_verify_ca to heartbeat.

    """

    # NOTE(rloo): This must be in sync with manager.ConductorManager's.
    # NOTE(pas-ha): This also must be in sync with
    #               ironic.common.release_mappings.RELEASE_MAPPING['master']
    RPC_API_VERSION = '1.51'

    def __init__(self, topic=None):
        super(ConductorAPI, self).__init__()
        self.topic = topic
        if self.topic is None:
            self.topic = manager.MANAGER_TOPIC

        serializer = objects_base.IronicObjectSerializer()
        release_ver = versions.RELEASE_MAPPING.get(CONF.pin_release_version)
        version_cap = (release_ver['rpc'] if release_ver
                       else self.RPC_API_VERSION)

        if CONF.rpc_transport == 'json-rpc':
            self.client = json_rpc.Client(serializer=serializer,
                                          version_cap=version_cap)
            self.topic = ''
        else:
            target = messaging.Target(topic=self.topic, version='1.0')
            self.client = rpc.get_client(target, version_cap=version_cap,
                                         serializer=serializer)

        use_groups = self.client.can_send_version('1.47')
        # NOTE(tenbrae): this is going to be buggy
        self.ring_manager = hash_ring.HashRingManager(use_groups=use_groups)

    def get_conductor_for(self, node):
        """Get the conductor which the node is mapped to.

        :param node: a node object.
        :returns: the conductor hostname.
        :raises: NoValidHost

        """
        try:
            ring = self.ring_manager.get_ring(node.driver,
                                              node.conductor_group)
            dest = ring.get_nodes(node.uuid.encode('utf-8'))
            return dest.pop()
        except exception.DriverNotFound:
            reason = (_('No conductor service registered which supports '
                        'driver %(driver)s for conductor group "%(group)s".') %
                      {'driver': node.driver, 'group': node.conductor_group})
            raise exception.NoValidHost(reason=reason)

    def get_topic_for(self, node):
        """Get the RPC topic for the conductor service the node is mapped to.

        :param node: a node object.
        :returns: an RPC topic string.
        :raises: NoValidHost

        """
        hostname = self.get_conductor_for(node)
        return '%s.%s' % (self.topic, hostname)

    def get_random_topic(self):
        """Get an RPC topic for a random conductor service."""
        conductors = dbapi.get_instance().get_online_conductors()
        try:
            hostname = random.choice(conductors)
        except IndexError:
            # There are no conductors - return 503 Service Unavailable
            raise exception.TemporaryFailure()
        return '%s.%s' % (self.topic, hostname)

    def get_topic_for_driver(self, driver_name):
        """Get RPC topic name for a conductor supporting the given driver.

        The topic is used to route messages to the conductor supporting
        the specified driver. A conductor is selected at random from the
        set of qualified conductors.

        :param driver_name: the name of the driver to route to.
        :returns: an RPC topic string.
        :raises: DriverNotFound

        """
        # NOTE(jroll) we want to be able to route this to any conductor,
        # regardless of groupings. We use a fresh, uncached hash ring that
        # does not take groups into account.
        local_ring_manager = hash_ring.HashRingManager(use_groups=False,
                                                       cache=False)
        try:
            ring = local_ring_manager.get_ring(driver_name, '')
        except exception.TemporaryFailure:
            # NOTE(dtantsur): even if no conductors are registered, it makes
            # sense to report 404 on any driver request.
            raise exception.DriverNotFound(_("No conductors registered."))
        host = random.choice(list(ring.nodes))
        return self.topic + "." + host

    def get_current_topic(self):
        """Get RPC topic name for the current conductor."""
        return self.topic + "." + CONF.host

    def can_send_create_port(self):
        """Return whether the RPCAPI supports the create_port method."""
        return self.client.can_send_version("1.41")

    def can_send_rescue(self):
        """Return whether the RPCAPI supports node rescue methods."""
        return self.client.can_send_version("1.43")

    def create_node(self, context, node_obj, topic=None):
        """Synchronously, have a conductor validate and create a node.

        Create the node's information in the database and return a node object.

        :param context: request context.
        :param node_obj: a created (but not saved) node object.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: created node object.
        :raises: InterfaceNotFoundInEntrypoint if validation fails for any
                 dynamic interfaces (e.g. network_interface).
        :raises: NoValidDefaultForInterface if no default can be calculated
                 for some interfaces, and explicit values must be provided.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.36')
        return cctxt.call(context, 'create_node', node_obj=node_obj)

    def update_node(self, context, node_obj, topic=None,
                    reset_interfaces=False):
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
        :param reset_interfaces: whether to reset hardware interfaces to their
                                 defaults.
        :returns: updated node object, including all fields.
        :raises: NoValidDefaultForInterface if no default can be calculated
                 for some interfaces, and explicit values must be provided.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.1')
        return cctxt.call(context, 'update_node', node_obj=node_obj,
                          reset_interfaces=reset_interfaces)

    def change_node_power_state(self, context, node_id, new_state,
                                topic=None, timeout=None):
        """Change a node's power state.

        Synchronously, acquire lock and start the conductor background task
        to change power state of a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param new_state: one of ironic.common.states power state values
        :param timeout: timeout (in seconds) positive integer (> 0) for any
           power state. ``None`` indicates to use default timeout.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.39')
        return cctxt.call(context, 'change_node_power_state', node_id=node_id,
                          new_state=new_state, timeout=timeout)

    def vendor_passthru(self, context, node_id, driver_method, http_method,
                        info, topic=None):
        """Receive requests for vendor-specific actions.

        Synchronously validate driver specific info or get driver status,
        and if successful invokes the vendor method. If the method mode
        is async the conductor will start background worker to perform
        vendor action.

        :param context: request context.
        :param node_id: node id or uuid.
        :param driver_method: name of method for driver.
        :param http_method: the HTTP method used for the request.
        :param info: info for node driver.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if supplied info is not valid.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: UnsupportedDriverExtension if current driver does not have
                 vendor interface.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: NodeLocked if node is locked by another conductor.
        :returns: A dictionary containing:

            :return: The response of the invoked vendor method
            :async: Boolean value. Whether the method was invoked
                asynchronously (True) or synchronously (False). When invoked
                asynchronously the response will be always None.
            :attach: Boolean value. Whether to attach the response of
                the invoked vendor method to the HTTP response object (True)
                or return it in the response body (False).

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.20')
        return cctxt.call(context, 'vendor_passthru', node_id=node_id,
                          driver_method=driver_method,
                          http_method=http_method,
                          info=info)

    def driver_vendor_passthru(self, context, driver_name, driver_method,
                               http_method, info, topic=None):
        """Pass vendor-specific calls which don't specify a node to a driver.

        Handles driver-level vendor passthru calls. These calls don't
        require a node UUID and are executed on a random conductor with
        the specified driver. If the method mode is async the conductor
        will start background worker to perform vendor action.

        :param context: request context.
        :param driver_name: name of the driver on which to call the method.
        :param driver_method: name of the vendor method, for use by the driver.
        :param http_method: the HTTP method used for the request.
        :param info: data to pass through to the driver.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue for parameter errors.
        :raises: MissingParameterValue if a required parameter is missing
        :raises: UnsupportedDriverExtension if the driver doesn't have a vendor
                 interface, or if the vendor interface does not support the
                 specified driver_method.
        :raises: DriverNotFound if the supplied driver is not loaded.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: InterfaceNotFoundInEntrypoint if the default interface for a
                 hardware type is invalid.
        :raises: NoValidDefaultForInterface if no default interface
                 implementation can be found for this driver's vendor
                 interface.
        :returns: A dictionary containing:

            :return: The response of the invoked vendor method
            :async: Boolean value. Whether the method was invoked
                asynchronously (True) or synchronously (False). When invoked
                asynchronously the response will be always None.
            :attach: Boolean value. Whether to attach the response of
                the invoked vendor method to the HTTP response object (True)
                or return it in the response body (False).

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.20')
        return cctxt.call(context, 'driver_vendor_passthru',
                          driver_name=driver_name,
                          driver_method=driver_method,
                          http_method=http_method,
                          info=info)

    def get_node_vendor_passthru_methods(self, context, node_id, topic=None):
        """Retrieve information about vendor methods of the given node.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.21')
        return cctxt.call(context, 'get_node_vendor_passthru_methods',
                          node_id=node_id)

    def get_driver_vendor_passthru_methods(self, context, driver_name,
                                           topic=None):
        """Retrieve information about vendor methods of the given driver.

        :param context: an admin context.
        :param driver_name: name of the driver.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: UnsupportedDriverExtension if current driver does not have
                 vendor interface.
        :raises: DriverNotFound if the supplied driver is not loaded.
        :raises: InterfaceNotFoundInEntrypoint if the default interface for a
                 hardware type is invalid.
        :raises: NoValidDefaultForInterface if no default interface
                 implementation can be found for this driver's vendor
                 interface.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.21')
        return cctxt.call(context, 'get_driver_vendor_passthru_methods',
                          driver_name=driver_name)

    def do_node_deploy(self, context, node_id, rebuild, configdrive,
                       topic=None):
        """Signal to conductor service to perform a deployment.

        :param context: request context.
        :param node_id: node id or uuid.
        :param rebuild: True if this is a rebuild request.
        :param configdrive: A gzipped and base64 encoded configdrive.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InstanceDeployFailure
        :raises: InvalidParameterValue if validation fails
        :raises: MissingParameterValue if a required parameter is missing
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        The node must already be configured and in the appropriate
        undeployed state before this method is called.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.22')
        return cctxt.call(context, 'do_node_deploy', node_id=node_id,
                          rebuild=rebuild, configdrive=configdrive)

    def do_node_tear_down(self, context, node_id, topic=None):
        """Signal to conductor service to tear down a deployment.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InstanceDeployFailure
        :raises: InvalidParameterValue if validation fails
        :raises: MissingParameterValue if a required parameter is missing
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        The node must already be configured and in the appropriate
        deployed state before this method is called.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.6')
        return cctxt.call(context, 'do_node_tear_down', node_id=node_id)

    def do_provisioning_action(self, context, node_id, action, topic=None):
        """Signal to conductor service to perform the given action on a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param action: an action. One of ironic.common.states.VERBS
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue
        :raises: NoFreeConductorWorker when there is no free worker to start
                async task.
        :raises: InvalidStateRequested if the requested action can not
                 be performed.

        This encapsulates some provisioning actions in a single call.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.23')
        return cctxt.call(context, 'do_provisioning_action',
                          node_id=node_id, action=action)

    def continue_node_clean(self, context, node_id, topic=None):
        """Signal to conductor service to start the next cleaning action.

        NOTE(JoshNang) this is an RPC cast, there will be no response or
        exception raised by the conductor for this RPC.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.27')
        return cctxt.cast(context, 'continue_node_clean',
                          node_id=node_id)

    def continue_node_deploy(self, context, node_id, topic=None):
        """Signal to conductor service to start the next deployment action.

        NOTE(rloo): this is an RPC cast, there will be no response or
        exception raised by the conductor for this RPC.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.45')
        return cctxt.cast(context, 'continue_node_deploy',
                          node_id=node_id)

    def validate_driver_interfaces(self, context, node_id, topic=None):
        """Validate the `core` and `standardized` interfaces for drivers.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: a dictionary containing the results of each
                  interface validation.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.5')
        return cctxt.call(context, 'validate_driver_interfaces',
                          node_id=node_id)

    def destroy_node(self, context, node_id, topic=None):
        """Delete a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeAssociated if the node contains an instance
            associated with it.
        :raises: InvalidState if the node is in the wrong provision
            state to perform deletion.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.9')
        return cctxt.call(context, 'destroy_node', node_id=node_id)

    def get_console_information(self, context, node_id, topic=None):
        """Get connection information about the console.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        :raises: MissingParameterValue if a required parameter is missing
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.11')
        return cctxt.call(context, 'get_console_information', node_id=node_id)

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
        :raises: MissingParameterValue if a required parameter is missing
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.11')
        return cctxt.call(context, 'set_console_mode', node_id=node_id,
                          enabled=enabled)

    def create_port(self, context, port_obj, topic=None):
        """Synchronously, have a conductor validate and create a port.

        Create the port's information in the database and return a port object.
        The conductor will lock related node and trigger specific driver
        actions if they are needed.

        :param context: request context.
        :param port_obj: a created (but not saved) port object.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: created port object.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.41')
        return cctxt.call(context, 'create_port', port_obj=port_obj)

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
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.13')
        return cctxt.call(context, 'update_port', port_obj=port_obj)

    def update_portgroup(self, context, portgroup_obj, topic=None):
        """Synchronously, have a conductor update the portgroup's information.

        Update the portgroup's information in the database and return a
        portgroup object.
        The conductor will lock related node and trigger specific driver
        actions if they are needed.

        :param context: request context.
        :param portgroup_obj: a changed (but not saved) portgroup object.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: updated portgroup object, including all fields.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.33')
        return cctxt.call(context, 'update_portgroup',
                          portgroup_obj=portgroup_obj)

    def destroy_portgroup(self, context, portgroup, topic=None):
        """Delete a portgroup.

        :param context: request context.
        :param portgroup: portgroup object
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node associated with the portgroup does
                 not exist.
        :raises: PortgroupNotEmpty if portgroup is not empty
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.33')
        return cctxt.call(context, 'destroy_portgroup', portgroup=portgroup)

    def get_driver_properties(self, context, driver_name, topic=None):
        """Get the properties of the driver.

        :param context: request context.
        :param driver_name: name of the driver.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: a dictionary with <property name>:<property description>
                  entries.
        :raises: DriverNotFound.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.16')
        return cctxt.call(context, 'get_driver_properties',
                          driver_name=driver_name)

    def set_boot_device(self, context, node_id, device, persistent=False,
                        topic=None):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node. Be aware
        that not all drivers support this.

        :param context: request context.
        :param node_id: node id or uuid.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Whether to set next-boot, or make the change
                           permanent. Default: False.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.17')
        return cctxt.call(context, 'set_boot_device', node_id=node_id,
                          device=device, persistent=persistent)

    def get_boot_device(self, context, node_id, topic=None):
        """Get the current boot device.

        Returns the current boot device of a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.17')
        return cctxt.call(context, 'get_boot_device', node_id=node_id)

    def inject_nmi(self, context, node_id, topic=None):
        """Inject NMI for a node.

        Inject NMI (Non Maskable Interrupt) for a node immediately.
        Be aware that not all drivers support this.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management or management.inject_nmi.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.40')
        return cctxt.call(context, 'inject_nmi', node_id=node_id)

    def get_supported_boot_devices(self, context, node_id, topic=None):
        """Get the list of supported devices.

        Returns the list of supported boot devices of a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.17')
        return cctxt.call(context, 'get_supported_boot_devices',
                          node_id=node_id)

    def set_indicator_state(self, context, node_id, component,
                            indicator, state, topic=None):
        """Set node hardware components indicator to the desired state.

        :param context: request context.
        :param node_id: node id or uuid.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator IDs, as
            reported by `get_supported_indicators`)
        :param state: Indicator state, one of
            mod:`ironic.common.indicator_states`.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.50')
        return cctxt.call(context, 'set_indicator_state', node_id=node_id,
                          component=component, indicator=indicator,
                          state=state)

    def get_indicator_state(self, context, node_id, component, indicator,
                            topic=None):
        """Get node hardware component indicator state.

        :param context: request context.
        :param node_id: node id or uuid.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator IDs, as
            reported by `get_supported_indicators`)
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: Indicator state, one of
            mod:`ironic.common.indicator_states`.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.50')
        return cctxt.call(context, 'get_indicator_state', node_id=node_id,
                          component=component, indicator=indicator)

    def get_supported_indicators(self, context, node_id,
                                 component=None, topic=None):
        """Get node hardware components and their indicators.

        :param context: request context.
        :param node_id: node id or uuid.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: A dictionary of hardware components
            (:mod:`ironic.common.components`) as keys with indicator IDs
            as values.

                ::

                    {
                        'chassis': ['enclosure-0'],
                        'system': ['blade-A']
                        'drive': ['ssd0']
                    }

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.50')
        return cctxt.call(context, 'get_supported_indicators', node_id=node_id,
                          component=component)

    def inspect_hardware(self, context, node_id, topic=None):
        """Signals the conductor service to perform hardware introspection.

        :param context: request context.
        :param node_id: node id or uuid.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: HardwareInspectionFailure
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support inspection.
        :raises: InvalidStateRequested if 'inspect' is not a valid
                 action to do in the current state.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.24')
        return cctxt.call(context, 'inspect_hardware', node_id=node_id)

    def destroy_port(self, context, port, topic=None):
        """Delete a port.

        :param context: request context.
        :param port: port object
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node associated with the port does not
                 exist.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.25')
        return cctxt.call(context, 'destroy_port', port=port)

    def set_target_raid_config(self, context, node_id, target_raid_config,
                               topic=None):
        """Stores the target RAID configuration on the node.

        Stores the target RAID configuration on node.target_raid_config

        :param context: request context.
        :param node_id: node id or uuid.
        :param target_raid_config: Dictionary containing the target RAID
            configuration. It may be an empty dictionary as well.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
            support RAID configuration.
        :raises: InvalidParameterValue, if validation of target raid config
            fails.
        :raises: MissingParameterValue, if some required parameters are
            missing.
        :raises: NodeLocked if node is locked by another conductor.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.30')
        return cctxt.call(context, 'set_target_raid_config',
                          node_id=node_id,
                          target_raid_config=target_raid_config)

    def get_raid_logical_disk_properties(self, context, driver_name,
                                         topic=None):
        """Get the logical disk properties for RAID configuration.

        Gets the information about logical disk properties which can
        be specified in the input RAID configuration.

        :param context: request context.
        :param driver_name: name of the driver
        :param topic: RPC topic. Defaults to self.topic.
        :raises: UnsupportedDriverExtension if the driver doesn't
            support RAID configuration.
        :raises: InterfaceNotFoundInEntrypoint if the default interface for a
                 hardware type is invalid.
        :raises: NoValidDefaultForInterface if no default interface
                 implementation can be found for this driver's RAID
                 interface.
        :returns: A dictionary containing the properties that can be mentioned
            for logical disks and a textual description for them.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.30')
        return cctxt.call(context, 'get_raid_logical_disk_properties',
                          driver_name=driver_name)

    def do_node_clean(self, context, node_id, clean_steps, topic=None):
        """Signal to conductor service to perform manual cleaning on a node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param clean_steps: a list of clean step dictionaries.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if validation of power driver interface
                 failed.
        :raises: InvalidStateRequested if cleaning can not be performed.
        :raises: NodeInMaintenance if node is in maintenance mode.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.32')
        return cctxt.call(context, 'do_node_clean',
                          node_id=node_id, clean_steps=clean_steps)

    def heartbeat(self, context, node_id, callback_url, agent_version,
                  agent_token=None, agent_verify_ca=None, topic=None):
        """Process a node heartbeat.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param callback_url: URL to reach back to the ramdisk.
        :param topic: RPC topic. Defaults to self.topic.
        :param agent_token: randomly generated validation token.
        :param agent_version: the version of the agent that is heartbeating
        :param agent_verify_ca: TLS certificate for the agent.
        :raises: InvalidParameterValue if an invalid agent token is received.
        """
        new_kws = {}
        version = '1.34'
        if self.client.can_send_version('1.42'):
            version = '1.42'
            new_kws['agent_version'] = agent_version
        if self.client.can_send_version('1.49'):
            version = '1.49'
            new_kws['agent_token'] = agent_token
        if self.client.can_send_version('1.51'):
            version = '1.51'
            new_kws['agent_verify_ca'] = agent_verify_ca
        cctxt = self.client.prepare(topic=topic or self.topic, version=version)
        return cctxt.call(context, 'heartbeat', node_id=node_id,
                          callback_url=callback_url, **new_kws)

    def object_class_action_versions(self, context, objname, objmethod,
                                     object_versions, args, kwargs):
        """Perform an action on a VersionedObject class.

        We want any conductor to handle this, so it is intentional that there
        is no topic argument for this method.

        :param context: The context within which to perform the action
        :param objname: The registry name of the object
        :param objmethod: The name of the action method to call
        :param object_versions: A dict of {objname: version} mappings
        :param args: The positional arguments to the action method
        :param kwargs: The keyword arguments to the action method
        :raises: NotImplementedError when an operator makes an error during
            upgrade
        :returns: The result of the action method, which may (or may not)
            be an instance of the implementing VersionedObject class.
        """
        if not self.client.can_send_version('1.31'):
            raise NotImplementedError(_('Incompatible conductor version - '
                                        'please upgrade ironic-conductor '
                                        'first'))
        cctxt = self.client.prepare(topic=self.topic, version='1.31')
        return cctxt.call(context, 'object_class_action_versions',
                          objname=objname, objmethod=objmethod,
                          object_versions=object_versions,
                          args=args, kwargs=kwargs)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        """Perform an action on a VersionedObject instance.

        We want any conductor to handle this, so it is intentional that there
        is no topic argument for this method.

        :param context: The context within which to perform the action
        :param objinst: The object instance on which to perform the action
        :param objmethod: The name of the action method to call
        :param args: The positional arguments to the action method
        :param kwargs: The keyword arguments to the action method
        :raises: NotImplementedError when an operator makes an error during
            upgrade
        :returns: A tuple with the updates made to the object and
            the result of the action method
        """
        if not self.client.can_send_version('1.31'):
            raise NotImplementedError(_('Incompatible conductor version - '
                                        'please upgrade ironic-conductor '
                                        'first'))
        cctxt = self.client.prepare(topic=self.topic, version='1.31')
        return cctxt.call(context, 'object_action', objinst=objinst,
                          objmethod=objmethod, args=args, kwargs=kwargs)

    def object_backport_versions(self, context, objinst, object_versions):
        """Perform a backport of an object instance.

        The default behavior of the base VersionedObjectSerializer, upon
        receiving an object with a version newer than what is in the local
        registry, is to call this method to request a backport of the object.

        We want any conductor to handle this, so it is intentional that there
        is no topic argument for this method.

        :param context: The context within which to perform the backport
        :param objinst: An instance of a VersionedObject to be backported
        :param object_versions: A dict of {objname: version} mappings
        :raises: NotImplementedError when an operator makes an error during
            upgrade
        :returns: The downgraded instance of objinst
        """
        if not self.client.can_send_version('1.31'):
            raise NotImplementedError(_('Incompatible conductor version - '
                                        'please upgrade ironic-conductor '
                                        'first'))
        cctxt = self.client.prepare(topic=self.topic, version='1.31')
        return cctxt.call(context, 'object_backport_versions', objinst=objinst,
                          object_versions=object_versions)

    def destroy_volume_connector(self, context, connector, topic=None):
        """Delete a volume connector.

        Delete the volume connector. The conductor will lock the related node
        during this operation.

        :param context: request context
        :param connector: volume connector object
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the connector does
                 not exist
        :raises: VolumeConnectorNotFound if the volume connector cannot be
                 found
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.35')
        return cctxt.call(context, 'destroy_volume_connector',
                          connector=connector)

    def update_volume_connector(self, context, connector, topic=None):
        """Update the volume connector's information.

        Update the volume connector's information in the database and return
        a volume connector object. The conductor will lock the related node
        during this operation.

        :param context: request context
        :param connector: a changed (but not saved) volume connector object
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if the volume connector's UUID is being
                 changed
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the connector does
                 not exist
        :raises: VolumeConnectorNotFound if the volume connector cannot be
                 found
        :raises: VolumeConnectorTypeAndIdAlreadyExists if another connector
                 already exists with the same values for type and connector_id
                 fields
        :returns: updated volume connector object, including all fields.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.35')
        return cctxt.call(context, 'update_volume_connector',
                          connector=connector)

    def destroy_volume_target(self, context, target, topic=None):
        """Delete a volume target.

        :param context: request context
        :param target: volume target object
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the target does
                 not exist
        :raises: VolumeTargetNotFound if the volume target cannot be found
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.37')
        return cctxt.call(context, 'destroy_volume_target',
                          target=target)

    def update_volume_target(self, context, target, topic=None):
        """Update the volume target's information.

        Update the volume target's information in the database and return a
        volume target object. The conductor will lock the related node during
        this operation.

        :param context: request context
        :param target: a changed (but not saved) volume target object
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if the volume target's UUID is being
                 changed
        :raises: NodeLocked if the node is already locked
        :raises: NodeNotFound if the node associated with the volume target
                 does not exist
        :raises: VolumeTargetNotFound if the volume target cannot be found
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same node ID and boot index values
        :returns: updated volume target object, including all fields

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.37')
        return cctxt.call(context, 'update_volume_target',
                          target=target)

    def vif_attach(self, context, node_id, vif_info, topic=None):
        """Attach VIF to a node

        :param context: request context.
        :param node_id: node ID or UUID.
        :param vif_info: a dictionary representing VIF object.
            It must have an 'id' key, whose value is a unique
            identifier for that VIF.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked, if node has an exclusive lock held on it
        :raises: NetworkError, if an error occurs during attaching the VIF.
        :raises: InvalidParameterValue, if a parameter that's required for
            VIF attach is wrong/missing.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.38')
        return cctxt.call(context, 'vif_attach', node_id=node_id,
                          vif_info=vif_info)

    def vif_detach(self, context, node_id, vif_id, topic=None):
        """Detach VIF from a node

        :param context: request context.
        :param node_id: node ID or UUID.
        :param vif_id: an ID of a VIF.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked, if node has an exclusive lock held on it
        :raises: NetworkError, if an error occurs during detaching the VIF.
        :raises: InvalidParameterValue, if a parameter that's required for
            VIF detach is wrong/missing.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.38')
        return cctxt.call(context, 'vif_detach', node_id=node_id,
                          vif_id=vif_id)

    def vif_list(self, context, node_id, topic=None):
        """List attached VIFs for a node

        :param context: request context.
        :param node_id: node ID or UUID.
        :param topic: RPC topic. Defaults to self.topic.
        :returns: List of VIF dictionaries, each dictionary will have an
            'id' entry with the ID of the VIF.
        :raises: NetworkError, if an error occurs during listing the VIFs.
        :raises: InvalidParameterValue, if a parameter that's required for
            VIF list is wrong/missing.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.38')
        return cctxt.call(context, 'vif_list', node_id=node_id)

    def do_node_rescue(self, context, node_id, rescue_password, topic=None):
        """Signal to conductor service to perform a rescue.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param rescue_password: A string representing the password to be set
            inside the rescue environment.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InstanceRescueFailure
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        The node must already be configured and in the appropriate
        state before this method is called.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.43')
        return cctxt.call(context, 'do_node_rescue', node_id=node_id,
                          rescue_password=rescue_password)

    def do_node_unrescue(self, context, node_id, topic=None):
        """Signal to conductor service to perform an unrescue.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InstanceUnrescueFailure
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        The node must already be configured and in the appropriate
        state before this method is called.

        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.43')
        return cctxt.call(context, 'do_node_unrescue', node_id=node_id)

    def add_node_traits(self, context, node_id, traits, replace=False,
                        topic=None):
        """Add or replace traits for a node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param traits: a list of traits to add to the node.
        :param replace: True to replace all of the node's traits.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidParameterValue if adding the traits would exceed the
            per-node traits limit.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node does not exist.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.44')
        return cctxt.call(context, 'add_node_traits', node_id=node_id,
                          traits=traits, replace=replace)

    def remove_node_traits(self, context, node_id, traits, topic=None):
        """Remove some or all traits from a node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param traits: a list of traits to remove from the node, or None. If
            None, all traits will be removed from the node.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node does not exist.
        :raises: NodeTraitNotFound if one of the traits is not found.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.44')
        return cctxt.call(context, 'remove_node_traits', node_id=node_id,
                          traits=traits)

    def create_allocation(self, context, allocation, topic=None):
        """Create an allocation.

        :param context: request context.
        :param allocation: an allocation object.
        :param topic: RPC topic. Defaults to self.topic.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.48')
        return cctxt.call(context, 'create_allocation', allocation=allocation)

    def destroy_allocation(self, context, allocation, topic=None):
        """Delete an allocation.

        :param context: request context.
        :param allocation: an allocation object.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: InvalidState if the associated node is in the wrong provision
            state to perform deallocation.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.48')
        return cctxt.call(context, 'destroy_allocation', allocation=allocation)

    def get_node_with_token(self, context, node_id, topic=None):
        """Request the node from the conductor with an agent token

        :param context: request context.
        :param node_id: node ID or UUID.
        :param topic: RPC topic. Defaults to self.topic.
        :raises: NodeLocked if node is locked by another conductor.

        :returns: A Node object with agent token.
        """
        cctxt = self.client.prepare(topic=topic or self.topic, version='1.49')
        return cctxt.call(context, 'get_node_with_token', node_id=node_id)
