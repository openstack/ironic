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

from ironic_tempest_plugin.services.baremetal import base


class BaremetalClient(base.BaremetalClient):
    """Base Tempest REST client for Ironic API v1."""
    version = '1'
    uri_prefix = 'v1'

    @base.handle_errors
    def list_nodes(self, **kwargs):
        """List all existing nodes."""
        return self._list_request('nodes', **kwargs)

    @base.handle_errors
    def list_chassis(self):
        """List all existing chassis."""
        return self._list_request('chassis')

    @base.handle_errors
    def list_chassis_nodes(self, chassis_uuid):
        """List all nodes associated with a chassis."""
        return self._list_request('/chassis/%s/nodes' % chassis_uuid)

    @base.handle_errors
    def list_ports(self, **kwargs):
        """List all existing ports."""
        return self._list_request('ports', **kwargs)

    @base.handle_errors
    def list_node_ports(self, uuid):
        """List all ports associated with the node."""
        return self._list_request('/nodes/%s/ports' % uuid)

    @base.handle_errors
    def list_nodestates(self, uuid):
        """List all existing states."""
        return self._list_request('/nodes/%s/states' % uuid)

    @base.handle_errors
    def list_ports_detail(self, **kwargs):
        """Details list all existing ports."""
        return self._list_request('/ports/detail', **kwargs)

    @base.handle_errors
    def list_drivers(self):
        """List all existing drivers."""
        return self._list_request('drivers')

    @base.handle_errors
    def show_node(self, uuid):
        """Gets a specific node.

        :param uuid: Unique identifier of the node in UUID format.
        :return: Serialized node as a dictionary.

        """
        return self._show_request('nodes', uuid)

    @base.handle_errors
    def show_node_by_instance_uuid(self, instance_uuid):
        """Gets a node associated with given instance uuid.

        :param instance_uuid: Unique identifier of the instance in UUID format.
        :return: Serialized node as a dictionary.

        """
        uri = '/nodes/detail?instance_uuid=%s' % instance_uuid

        return self._show_request('nodes',
                                  uuid=None,
                                  uri=uri)

    @base.handle_errors
    def show_chassis(self, uuid):
        """Gets a specific chassis.

        :param uuid: Unique identifier of the chassis in UUID format.
        :return: Serialized chassis as a dictionary.

        """
        return self._show_request('chassis', uuid)

    @base.handle_errors
    def show_port(self, uuid):
        """Gets a specific port.

        :param uuid: Unique identifier of the port in UUID format.
        :return: Serialized port as a dictionary.

        """
        return self._show_request('ports', uuid)

    @base.handle_errors
    def show_port_by_address(self, address):
        """Gets a specific port by address.

        :param address: MAC address of the port.
        :return: Serialized port as a dictionary.

        """
        uri = '/ports/detail?address=%s' % address

        return self._show_request('ports', uuid=None, uri=uri)

    def show_driver(self, driver_name):
        """Gets a specific driver.

        :param driver_name: Name of driver.
        :return: Serialized driver as a dictionary.
        """
        return self._show_request('drivers', driver_name)

    @base.handle_errors
    def create_node(self, chassis_id=None, **kwargs):
        """Create a baremetal node with the specified parameters.

        :param chassis_id: The unique identifier of the chassis.
        :param cpu_arch: CPU architecture of the node. Default: x86_64.
        :param cpus: Number of CPUs. Default: 8.
        :param local_gb: Disk size. Default: 1024.
        :param memory_mb: Available RAM. Default: 4096.
        :param driver: Driver name. Default: "fake"
        :return: A tuple with the server response and the created node.

        """
        node = {'chassis_uuid': chassis_id,
                'properties': {'cpu_arch': kwargs.get('cpu_arch', 'x86_64'),
                               'cpus': kwargs.get('cpus', 8),
                               'local_gb': kwargs.get('local_gb', 1024),
                               'memory_mb': kwargs.get('memory_mb', 4096)},
                'driver': kwargs.get('driver', 'fake')}

        return self._create_request('nodes', node)

    @base.handle_errors
    def create_chassis(self, **kwargs):
        """Create a chassis with the specified parameters.

        :param description: The description of the chassis.
            Default: test-chassis
        :return: A tuple with the server response and the created chassis.

        """
        chassis = {'description': kwargs.get('description', 'test-chassis')}

        return self._create_request('chassis', chassis)

    @base.handle_errors
    def create_port(self, node_id, **kwargs):
        """Create a port with the specified parameters.

        :param node_id: The ID of the node which owns the port.
        :param address: MAC address of the port.
        :param extra: Meta data of the port. Default: {'foo': 'bar'}.
        :param uuid: UUID of the port.
        :return: A tuple with the server response and the created port.

        """
        port = {'extra': kwargs.get('extra', {'foo': 'bar'}),
                'uuid': kwargs['uuid']}

        if node_id is not None:
            port['node_uuid'] = node_id

        if kwargs['address'] is not None:
            port['address'] = kwargs['address']

        return self._create_request('ports', port)

    @base.handle_errors
    def delete_node(self, uuid):
        """Deletes a node having the specified UUID.

        :param uuid: The unique identifier of the node.
        :return: A tuple with the server response and the response body.

        """
        return self._delete_request('nodes', uuid)

    @base.handle_errors
    def delete_chassis(self, uuid):
        """Deletes a chassis having the specified UUID.

        :param uuid: The unique identifier of the chassis.
        :return: A tuple with the server response and the response body.

        """
        return self._delete_request('chassis', uuid)

    @base.handle_errors
    def delete_port(self, uuid):
        """Deletes a port having the specified UUID.

        :param uuid: The unique identifier of the port.
        :return: A tuple with the server response and the response body.

        """
        return self._delete_request('ports', uuid)

    @base.handle_errors
    def update_node(self, uuid, **kwargs):
        """Update the specified node.

        :param uuid: The unique identifier of the node.
        :return: A tuple with the server response and the updated node.

        """
        node_attributes = ('properties/cpu_arch',
                           'properties/cpus',
                           'properties/local_gb',
                           'properties/memory_mb',
                           'driver',
                           'instance_uuid')

        patch = self._make_patch(node_attributes, **kwargs)

        return self._patch_request('nodes', uuid, patch)

    @base.handle_errors
    def update_chassis(self, uuid, **kwargs):
        """Update the specified chassis.

        :param uuid: The unique identifier of the chassis.
        :return: A tuple with the server response and the updated chassis.

        """
        chassis_attributes = ('description',)
        patch = self._make_patch(chassis_attributes, **kwargs)

        return self._patch_request('chassis', uuid, patch)

    @base.handle_errors
    def update_port(self, uuid, patch):
        """Update the specified port.

        :param uuid: The unique identifier of the port.
        :param patch: List of dicts representing json patches.
        :return: A tuple with the server response and the updated port.

        """

        return self._patch_request('ports', uuid, patch)

    @base.handle_errors
    def set_node_power_state(self, node_uuid, state):
        """Set power state of the specified node.

        :param node_uuid: The unique identifier of the node.
        :param state: desired state to set (on/off/reboot).

        """
        target = {'target': state}
        return self._put_request('nodes/%s/states/power' % node_uuid,
                                 target)

    @base.handle_errors
    def set_node_provision_state(self, node_uuid, state, configdrive=None):
        """Set provision state of the specified node.

        :param node_uuid: The unique identifier of the node.
        :param state: desired state to set
                (active/rebuild/deleted/inspect/manage/provide).
        :config_drive: A gzipped, base64-encoded configuration drive string.
        """
        data = {'target': state, 'configdrive': configdrive}
        return self._put_request('nodes/%s/states/provision' % node_uuid,
                                 data)

    @base.handle_errors
    def set_node_raid_config(self, node_uuid, target_raid_config):
        """Set raid config of the specified node.

        :param node_uuid: The unique identifier of the node.
        :target_raid_config: desired RAID configuration of the node.
        """
        return self._put_request('nodes/%s/states/raid' % node_uuid,
                                 target_raid_config)

    @base.handle_errors
    def validate_driver_interface(self, node_uuid):
        """Get all driver interfaces of a specific node.

        :param node_uuid: Unique identifier of the node in UUID format.

        """

        uri = '{pref}/{res}/{uuid}/{postf}'.format(pref=self.uri_prefix,
                                                   res='nodes',
                                                   uuid=node_uuid,
                                                   postf='validate')

        return self._show_request('nodes', node_uuid, uri=uri)

    @base.handle_errors
    def set_node_boot_device(self, node_uuid, boot_device, persistent=False):
        """Set the boot device of the specified node.

        :param node_uuid: The unique identifier of the node.
        :param boot_device: The boot device name.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.

        """
        request = {'boot_device': boot_device, 'persistent': persistent}
        resp, body = self._put_request('nodes/%s/management/boot_device' %
                                       node_uuid, request)
        self.expected_success(204, resp.status)
        return body

    @base.handle_errors
    def get_node_boot_device(self, node_uuid):
        """Get the current boot device of the specified node.

        :param node_uuid: The unique identifier of the node.

        """
        path = 'nodes/%s/management/boot_device' % node_uuid
        resp, body = self._list_request(path)
        self.expected_success(200, resp.status)
        return body

    @base.handle_errors
    def get_node_supported_boot_devices(self, node_uuid):
        """Get the supported boot devices of the specified node.

        :param node_uuid: The unique identifier of the node.

        """
        path = 'nodes/%s/management/boot_device/supported' % node_uuid
        resp, body = self._list_request(path)
        self.expected_success(200, resp.status)
        return body

    @base.handle_errors
    def get_console(self, node_uuid):
        """Get connection information about the console.

        :param node_uuid: Unique identifier of the node in UUID format.

        """

        resp, body = self._show_request('nodes/states/console', node_uuid)
        self.expected_success(200, resp.status)
        return resp, body

    @base.handle_errors
    def set_console_mode(self, node_uuid, enabled):
        """Start and stop the node console.

        :param node_uuid: Unique identifier of the node in UUID format.
        :param enabled: Boolean value; whether to enable or disable the
                        console.

        """

        enabled = {'enabled': enabled}
        resp, body = self._put_request('nodes/%s/states/console' % node_uuid,
                                       enabled)
        self.expected_success(202, resp.status)
        return resp, body
