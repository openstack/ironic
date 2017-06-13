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

import functools

from tempest import config
from tempest.lib.common import api_version_utils
from tempest.lib.common.utils import data_utils
from tempest.lib import exceptions as lib_exc
from tempest import test

from ironic_tempest_plugin import clients
from ironic_tempest_plugin.tests.api.admin import api_microversion_fixture

CONF = config.CONF


# NOTE(adam_g): The baremetal API tests exercise operations such as enroll
# node, power on, power off, etc.  Testing against real drivers (ie, IPMI)
# will require passing driver-specific data to Tempest (addresses,
# credentials, etc).  Until then, only support testing against the fake driver,
# which has no external dependencies.
SUPPORTED_DRIVERS = ['fake']

# NOTE(jroll): resources must be deleted in a specific order, this list
# defines the resource types to clean up, and the correct order.
RESOURCE_TYPES = ['port', 'portgroup', 'volume_connector', 'volume_target',
                  'node', 'chassis']


def creates(resource):
    """Decorator that adds resources to the appropriate cleanup list."""

    def decorator(f):
        @functools.wraps(f)
        def wrapper(cls, *args, **kwargs):
            resp, body = f(cls, *args, **kwargs)

            if 'uuid' in body:
                cls.created_objects[resource].add(body['uuid'])

            return resp, body
        return wrapper
    return decorator


class BaseBaremetalTest(api_version_utils.BaseMicroversionTest,
                        test.BaseTestCase):
    """Base class for Baremetal API tests."""

    credentials = ['admin']

    @classmethod
    def skip_checks(cls):
        super(BaseBaremetalTest, cls).skip_checks()
        if not CONF.service_available.ironic:
            raise cls.skipException('Ironic is not enabled.')
        if CONF.baremetal.driver not in SUPPORTED_DRIVERS:
            skip_msg = ('%s skipped as Ironic driver %s is not supported for '
                        'testing.' %
                        (cls.__name__, CONF.baremetal.driver))
            raise cls.skipException(skip_msg)

        cfg_min_version = CONF.baremetal.min_microversion
        cfg_max_version = CONF.baremetal.max_microversion
        api_version_utils.check_skip_with_microversion(cls.min_microversion,
                                                       cls.max_microversion,
                                                       cfg_min_version,
                                                       cfg_max_version)

    @classmethod
    def setup_credentials(cls):
        cls.request_microversion = (
            api_version_utils.select_request_microversion(
                cls.min_microversion,
                CONF.baremetal.min_microversion))
        cls.services_microversion = {
            CONF.baremetal.catalog_type: cls.request_microversion}
        super(BaseBaremetalTest, cls).setup_credentials()

    @classmethod
    def setup_clients(cls):
        super(BaseBaremetalTest, cls).setup_clients()
        cls.client = clients.Manager().baremetal_client

    @classmethod
    def resource_setup(cls):
        super(BaseBaremetalTest, cls).resource_setup()
        cls.request_microversion = (
            api_version_utils.select_request_microversion(
                cls.min_microversion,
                CONF.baremetal.min_microversion))
        cls.driver = CONF.baremetal.driver
        cls.power_timeout = CONF.baremetal.power_timeout
        cls.unprovision_timeout = CONF.baremetal.unprovision_timeout
        cls.created_objects = {}
        for resource in RESOURCE_TYPES:
            cls.created_objects[resource] = set()

    @classmethod
    def resource_cleanup(cls):
        """Ensure that all created objects get destroyed."""

        try:
            for resource in RESOURCE_TYPES:
                uuids = cls.created_objects[resource]
                delete_method = getattr(cls.client, 'delete_%s' % resource)
                for u in uuids:
                    delete_method(u, ignore_errors=lib_exc.NotFound)
        finally:
            super(BaseBaremetalTest, cls).resource_cleanup()

    def _assertExpected(self, expected, actual):
        """Check if expected keys/values exist in actual response body.

        Check if the expected keys and values are in the actual response body.
        It will not check the keys 'created_at' and 'updated_at', since they
        will always have different values. Asserts if any expected key (or
        corresponding value) is not in the actual response.

        Note: this method has an underscore even though it is used outside of
        this class, in order to distinguish this method from the more standard
        assertXYZ methods.

        :param expected: dict of key-value pairs that are expected to be in
                         'actual' dict.
        :param actual: dict of key-value pairs.

        """
        for key, value in expected.items():
            if key not in ('created_at', 'updated_at'):
                self.assertIn(key, actual)
                self.assertEqual(value, actual[key])

    def setUp(self):
        super(BaseBaremetalTest, self).setUp()
        self.useFixture(api_microversion_fixture.APIMicroversionFixture(
            self.request_microversion))

    @classmethod
    @creates('chassis')
    def create_chassis(cls, description=None, **kwargs):
        """Wrapper utility for creating test chassis.

        :param description: A description of the chassis. If not supplied,
            a random value will be generated.
        :return: A tuple with the server response and the created chassis.

        """
        description = description or data_utils.rand_name('test-chassis')
        resp, body = cls.client.create_chassis(description=description,
                                               **kwargs)
        return resp, body

    @classmethod
    @creates('node')
    def create_node(cls, chassis_id, cpu_arch='x86', cpus=8, local_gb=10,
                    memory_mb=4096, resource_class=None):
        """Wrapper utility for creating test baremetal nodes.

        :param chassis_id: The unique identifier of the chassis.
        :param cpu_arch: CPU architecture of the node. Default: x86.
        :param cpus: Number of CPUs. Default: 8.
        :param local_gb: Disk size. Default: 10.
        :param memory_mb: Available RAM. Default: 4096.
        :param resource_class: Node resource class.
        :return: A tuple with the server response and the created node.

        """
        resp, body = cls.client.create_node(chassis_id, cpu_arch=cpu_arch,
                                            cpus=cpus, local_gb=local_gb,
                                            memory_mb=memory_mb,
                                            driver=cls.driver,
                                            resource_class=resource_class)

        return resp, body

    @classmethod
    @creates('port')
    def create_port(cls, node_id, address, extra=None, uuid=None,
                    portgroup_uuid=None, physical_network=None):
        """Wrapper utility for creating test ports.

        :param node_id: The unique identifier of the node.
        :param address: MAC address of the port.
        :param extra: Meta data of the port. If not supplied, an empty
            dictionary will be created.
        :param uuid: UUID of the port.
        :param portgroup_uuid: The UUID of a portgroup of which this port is a
            member.
        :param physical_network: The physical network to which the port is
            attached.
        :return: A tuple with the server response and the created port.

        """
        extra = extra or {}
        resp, body = cls.client.create_port(address=address, node_id=node_id,
                                            extra=extra, uuid=uuid,
                                            portgroup_uuid=portgroup_uuid,
                                            physical_network=physical_network)

        return resp, body

    @classmethod
    @creates('portgroup')
    def create_portgroup(cls, node_uuid, **kwargs):
        """Wrapper utility for creating test port groups.

        :param node_uuid: The unique identifier of the node.
        :return: A tuple with the server response and the created port group.
        """
        resp, body = cls.client.create_portgroup(node_uuid=node_uuid, **kwargs)

        return resp, body

    @classmethod
    @creates('volume_connector')
    def create_volume_connector(cls, node_uuid, **kwargs):
        """Wrapper utility for creating test volume connector.

        :param node_uuid: The unique identifier of the node.
        :return: A tuple with the server response and the created volume
            connector.
        """
        resp, body = cls.client.create_volume_connector(node_uuid=node_uuid,
                                                        **kwargs)

        return resp, body

    @classmethod
    @creates('volume_target')
    def create_volume_target(cls, node_uuid, **kwargs):
        """Wrapper utility for creating test volume target.

        :param node_uuid: The unique identifier of the node.
        :return: A tuple with the server response and the created volume
            target.
        """
        resp, body = cls.client.create_volume_target(node_uuid=node_uuid,
                                                     **kwargs)

        return resp, body

    @classmethod
    def delete_chassis(cls, chassis_id):
        """Deletes a chassis having the specified UUID.

        :param chassis_id: The unique identifier of the chassis.
        :return: Server response.

        """

        resp, body = cls.client.delete_chassis(chassis_id)

        if chassis_id in cls.created_objects['chassis']:
            cls.created_objects['chassis'].remove(chassis_id)

        return resp

    @classmethod
    def delete_node(cls, node_id):
        """Deletes a node having the specified UUID.

        :param node_id: The unique identifier of the node.
        :return: Server response.

        """

        resp, body = cls.client.delete_node(node_id)

        if node_id in cls.created_objects['node']:
            cls.created_objects['node'].remove(node_id)

        return resp

    @classmethod
    def delete_port(cls, port_id):
        """Deletes a port having the specified UUID.

        :param port_id: The unique identifier of the port.
        :return: Server response.

        """

        resp, body = cls.client.delete_port(port_id)

        if port_id in cls.created_objects['port']:
            cls.created_objects['port'].remove(port_id)

        return resp

    @classmethod
    def delete_portgroup(cls, portgroup_ident):
        """Deletes a port group having the specified UUID or name.

        :param portgroup_ident: The name or UUID of the port group.
        :return: Server response.
        """
        resp, body = cls.client.delete_portgroup(portgroup_ident)

        if portgroup_ident in cls.created_objects['portgroup']:
            cls.created_objects['portgroup'].remove(portgroup_ident)

        return resp

    @classmethod
    def delete_volume_connector(cls, volume_connector_id):
        """Deletes a volume connector having the specified UUID.

        :param volume_connector_id: The UUID of the volume connector.
        :return: Server response.
        """
        resp, body = cls.client.delete_volume_connector(volume_connector_id)

        if volume_connector_id in cls.created_objects['volume_connector']:
            cls.created_objects['volume_connector'].remove(
                volume_connector_id)

        return resp

    @classmethod
    def delete_volume_target(cls, volume_target_id):
        """Deletes a volume target having the specified UUID.

        :param volume_target_id: The UUID of the volume target.
        :return: Server response.
        """
        resp, body = cls.client.delete_volume_target(volume_target_id)

        if volume_target_id in cls.created_objects['volume_target']:
            cls.created_objects['volume_target'].remove(volume_target_id)

        return resp

    def validate_self_link(self, resource, uuid, link):
        """Check whether the given self link formatted correctly."""
        expected_link = "{base}/{pref}/{res}/{uuid}".format(
                        base=self.client.base_url.rstrip('/'),
                        pref=self.client.uri_prefix,
                        res=resource,
                        uuid=uuid)
        self.assertEqual(expected_link, link)
