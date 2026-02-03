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

import inspect
from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import network
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.network import (
    ironic_networking as standalone)

from ironic.networking import api as networking_api
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class IronicNetworkingTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IronicNetworkingTestCase, self).setUp()
        self.config(enabled_hardware_types=['fake-hardware'],
                    enabled_network_interfaces=['ironic-networking'])
        self.node = obj_utils.create_test_node(
            self.context,
            network_interface='ironic-networking')
        self.interface = standalone.IronicNetworking()

    def _generate_test_mac(self):
        rand = uuidutils.generate_uuid().replace('-', '')
        sections = [rand[i:i + 2] for i in range(0, 8, 2)]
        return '52:54:%s:%s:%s:%s' % tuple(sections)

    def _create_test_port(self, node_id=None, **kwargs):
        """Create a test port with default values."""
        port_kwargs = {
            'uuid': uuidutils.generate_uuid(),
            'node_id': node_id or self.node.id,
            'address': kwargs.pop('address', self._generate_test_mac()),
            'local_link_connection': {
                'switch_id': '00:11:22:33:44:55',
                'port_id': 'GigE1/0/1',
                'switch_info': 'test-switch'
            },
            'extra': {}
        }
        port_kwargs.update(kwargs)
        return obj_utils.create_test_port(self.context, **port_kwargs)

    def _create_test_portgroup(self, node_id=None, **kwargs):
        """Create a test portgroup with default values."""
        portgroup_kwargs = {
            'node_id': node_id or self.node.id,
            'name': 'test-portgroup',
            'extra': {}
        }
        portgroup_kwargs.update(kwargs)
        return obj_utils.create_test_portgroup(
            self.context, **portgroup_kwargs)

    def _create_port_copy(self, original_port, **kwargs):
        """Create a copy of a port with modified attributes.

        (not persisted to DB).
        """
        # Create a copy of the port object for testing "current" state
        port_copy = objects.Port(self.context)
        for field in original_port.fields:
            if (hasattr(original_port, field)
                    and original_port.obj_attr_is_set(field)):
                setattr(port_copy, field, getattr(original_port, field))

        # Apply any overrides
        for key, value in kwargs.items():
            setattr(port_copy, key, value)

        return port_copy


class IronicNetworkingValidationTestCase(IronicNetworkingTestCase):

    def test_validate_with_valid_switchport_access(self):
        """Test validation with valid access switchport configuration."""
        port = self._create_test_port(
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_with_valid_switchport_trunk(self):
        """Test validation with valid trunk switchport configuration."""
        port = self._create_test_port(
            pxe_enabled=False,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_with_valid_switchport_hybrid(self):
        """Test validation with valid hybrid switchport configuration."""
        port = self._create_test_port(
            pxe_enabled=False,
            extra={
                'switchport': {
                    'mode': 'hybrid',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_with_invalid_switchport_mode(self):
        """Test validation with invalid switchport mode."""
        port = self._create_test_port(
            extra={
                'switchport': {
                    'mode': 'invalid',
                    'native_vlan': 100
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_with_invalid_lag_schema(self):
        """Portgroup validation fails when schema invalid."""
        portgroup = self._create_test_portgroup(
            extra={'lag': {'mode': 'access'}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = []
            task.portgroups = [portgroup]
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_portgroup_no_member_ports(self):
        """Portgroup validation fails when members missing."""
        portgroup = self._create_test_portgroup(
            extra={'lag': {
                'mode': 'access',
                'aggregation_mode': 'static'
            }}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = []
            task.portgroups = [portgroup]
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_switchport_missing_switch_id(self):
        """Port validation fails when switch_id missing."""
        port = self._create_test_port(
            local_link_connection={'port_id': 'GigE1/0/1'},
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_switchport_missing_port_id(self):
        """Port validation fails when port_id missing."""
        port = self._create_test_port(
            local_link_connection={'switch_id': '00:11:22:33:44:55'},
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_pxe_enabled_port_with_access_mode(self):
        """Test validation passes for PXE-enabled port with access mode."""
        port = self._create_test_port(
            pxe_enabled=True,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_pxe_enabled_port_with_trunk_mode_fails(self):
        """Test validation fails for PXE-enabled port with trunk mode."""
        port = self._create_test_port(
            pxe_enabled=True,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_pxe_enabled_port_with_hybrid_mode_fails(self):
        """Test validation fails for PXE-enabled port with hybrid mode."""
        port = self._create_test_port(
            pxe_enabled=True,
            extra={
                'switchport': {
                    'mode': 'hybrid',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_pxe_disabled_port_with_trunk_mode(self):
        """Test validation passes for non-PXE port with trunk mode."""
        port = self._create_test_port(
            pxe_enabled=False,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_pxe_disabled_port_with_hybrid_mode(self):
        """Test validation passes for non-PXE port with hybrid mode."""
        port = self._create_test_port(
            pxe_enabled=False,
            extra={
                'switchport': {
                    'mode': 'hybrid',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_pxe_enabled_port_without_switchport(self):
        """Test validation passes for PXE-enabled port without switchport."""
        port = self._create_test_port(
            pxe_enabled=True,
            extra={}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.interface.validate(task)

    def test_validate_switchport_missing_local_link_outside_inspection(self):
        """Port validation fails when not in inspection state.

        When a port has switchport configuration but is missing
        local_link_connection and the node is not in an inspection state,
        validation should raise an error since we cannot determine which
        physical switchport to configure.
        """
        # Set node to a non-inspection state (e.g., MANAGEABLE)
        self.node.provision_state = states.MANAGEABLE
        self.node.save()

        port = self._create_test_port(
            local_link_connection=None,
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)

    def test_validate_switchport_missing_local_link_during_inspection(self):
        """Port validation passes when in inspection state.

        When a port has switchport configuration but is missing
        local_link_connection while the node is in an inspection state,
        validation should pass with a debug log since local_link_connection
        may be populated during inspection.
        """
        # Set node to an inspection state
        self.node.provision_state = states.INSPECTING
        self.node.save()

        port = self._create_test_port(
            local_link_connection=None,
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            task.portgroups = []
            # Should not raise an exception
            self.interface.validate(task)


class IronicNetworkingPortChangedTestCase(
        IronicNetworkingTestCase):

    def setUp(self):
        super(IronicNetworkingPortChangedTestCase, self).setUp()
        # Ensure node is in a state where a network should be active so that
        # port_changed triggers networking API calls.
        self.node.provision_state = states.DEPLOYING
        self.node.save()

    @mock.patch.object(networking_api, 'reset_port', autospec=True)
    def test_port_changed_deleted_case(self, mock_reset_port):
        """Test port_changed when switchport config is deleted."""
        mock_reset_port.return_value = {'status': 'reset'}

        # Create port with switchport config
        original_port = self._create_test_port(
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        # Current port without switchport config
        current_port = self._create_port_copy(original_port, extra={})

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_reset_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=None, default_vlan=None)

    @mock.patch.object(networking_api, 'reset_port', autospec=True)
    def test_port_changed_deleted_skips_without_active_network(
            self, mock_reset_port):
        """Deletion skips when no active network should be configured."""
        self.node.provision_state = states.ENROLL
        self.node.save()
        mock_reset_port.return_value = {'status': 'reset'}
        original_port = self._create_test_port(
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        current_port = self._create_port_copy(original_port, extra={})
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)
        mock_reset_port.assert_not_called()

    @mock.patch.object(networking_api, 'reset_port', autospec=True)
    def test_port_changed_deleted_case_trunk_mode(self, mock_reset_port):
        """Test port_changed when trunk switchport config is deleted."""
        mock_reset_port.return_value = {'status': 'reset'}

        # Create port with trunk switchport config
        original_port = self._create_test_port(
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )

        # Current port without switchport config
        current_port = self._create_port_copy(original_port, extra={})

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_reset_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=[100, 200, 300], default_vlan=None)

    @mock.patch.object(networking_api, 'reset_port', autospec=True)
    def test_port_changed_deleted_case_hybrid_mode(self, mock_reset_port):
        """Test port_changed when hybrid switchport config is deleted."""
        mock_reset_port.return_value = {'status': 'reset'}

        # Create port with hybrid switchport config
        original_port = self._create_test_port(
            extra={
                'switchport': {
                    'mode': 'hybrid',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300]
                }
            }
        )

        # Current port without switchport config
        current_port = self._create_port_copy(original_port, extra={})

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_reset_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=[100, 200, 300], default_vlan=None)

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_created_case_access(self, mock_update_port):
        """Test port_changed when switchport config is created.

        (access mode).
        """
        mock_update_port.return_value = {'status': 'updated'}

        # Original port without switchport config
        original_port = self._create_test_port(extra={})

        # Current port with access switchport config
        current_port = self._create_port_copy(
            original_port,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_update_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1',
            'Ironic Port ' + str(current_port.uuid), 'access', 100,
            allowed_vlans=None, lag_name=None, default_vlan=None)

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_switchport_added_no_local_link(
            self, mock_update_port):
        """Switchport addition skipped if local_link missing."""
        original_port = self._create_test_port(
            local_link_connection=None,
            extra={}
        )
        current_port = self._create_port_copy(
            original_port,
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)
        mock_update_port.assert_not_called()

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_created_case_trunk(self, mock_update_port):
        """Test port_changed when switchport config is created (trunk mode)."""
        mock_update_port.return_value = {'status': 'updated'}

        # Original port without switchport config
        original_port = self._create_test_port(pxe_enabled=False, extra={})

        # Current port with trunk switchport config
        current_port = self._create_port_copy(
            original_port,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300],
                    'lag_name': 'port-channel1'
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_update_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1',
            'Ironic Port ' + str(current_port.uuid), 'trunk', 100,
            allowed_vlans=[100, 200, 300],
            lag_name='port-channel1',
            default_vlan=None)

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_switchport_added_uses_network_override(
            self, mock_update_port):
        """Network override from config takes precedence over switchport."""
        mock_update_port.return_value = {'status': 'updated'}
        original_port = self._create_test_port(extra={})
        current_port = self._create_port_copy(
            original_port,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 111
                }
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.config(provisioning_network='trunk/native_vlan=222',
                        group='ironic_networking')
            self.interface.port_changed(task, current_port)
        mock_update_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1',
            'Ironic Port ' + str(current_port.uuid), 'trunk', 222,
            allowed_vlans=None, lag_name=None, default_vlan=None)

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_created_case_hybrid(self, mock_update_port):
        """Test port_changed when switchport config is created.

        (hybrid mode).
        """
        mock_update_port.return_value = {'status': 'updated'}

        # Original port without switchport config
        original_port = self._create_test_port(pxe_enabled=False, extra={})

        # Current port with hybrid switchport config
        current_port = self._create_port_copy(
            original_port,
            extra={
                'switchport': {
                    'mode': 'hybrid',
                    'native_vlan': 100,
                    'allowed_vlans': [100, 200, 300],
                    'lag_name': 'port-channel1'
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_update_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1',
            'Ironic Port ' + str(current_port.uuid), 'hybrid', 100,
            allowed_vlans=[100, 200, 300],
            lag_name='port-channel1',
            default_vlan=None)

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_updated_case(self, mock_update_port):
        """Test port_changed when switchport config is updated."""
        mock_update_port.return_value = {'status': 'updated'}

        # Original port with access switchport config
        original_port = self._create_test_port(
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        # Current port with different access switchport config
        current_port = self._create_port_copy(
            original_port,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 200
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        mock_update_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1',
            'Ironic Port ' + str(current_port.uuid), 'access', 200,
            allowed_vlans=None, lag_name=None, default_vlan=None)

    def test_port_changed_no_change(self):
        """Test port_changed when no switchport config changes."""
        # Same switchport config in both original and current
        switchport_config = {
            'mode': 'access',
            'native_vlan': 100
        }

        original_port = self._create_test_port(
            extra={'switchport': switchport_config}
        )

        current_port = self._create_port_copy(
            original_port,
            extra={'switchport': switchport_config.copy()}
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            # Should not raise any exceptions and should not call
            # networking API
            self.interface.port_changed(task, current_port)

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    @mock.patch.object(networking_api, 'reset_port', autospec=True)
    def test_port_changed_handles_local_link_change(
            self, mock_reset_port, mock_update_port):
        """Local link change triggers reset then update."""
        mock_reset_port.return_value = {'status': 'reset'}
        mock_update_port.return_value = {'status': 'updated'}
        original_port = self._create_test_port(
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        current_port = self._create_port_copy(
            original_port,
            local_link_connection={
                'switch_id': '00:11:22:33:44:66',
                'port_id': 'GigE1/0/2'
            }
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)
        mock_reset_port.assert_called_once_with(
            task.context, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=None, default_vlan=None)
        mock_update_port.assert_called_once_with(
            task.context, '00:11:22:33:44:66', 'GigE1/0/2',
            'Ironic Port ' + str(current_port.uuid), 'access', 100,
            allowed_vlans=None, lag_name=None, default_vlan=None)

    @mock.patch.object(networking_api, 'reset_port', autospec=True)
    def test_port_changed_deleted_missing_required_fields(self,
                                                          mock_reset_port):
        """Test port_changed deletion case with missing required fields."""
        # Create port with switchport config but missing local_link_connection
        original_port = self._create_test_port(
            # Empty instead of None to pass validation
            local_link_connection={},
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        # Current port without switchport config
        current_port = self._create_port_copy(original_port, extra={})

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.interface.port_changed(task, current_port)

        # Should not call reset_port due to missing fields
        mock_reset_port.assert_not_called()

    @mock.patch.object(networking_api, 'update_port', autospec=True)
    def test_port_changed_created_missing_required_fields(self,
                                                          mock_update_port):
        """Test port_changed creation case with missing required fields."""
        # Original port without switchport config
        original_port = self._create_test_port(extra={})

        # Current port with switchport config but missing native_vlan
        current_port = self._create_port_copy(
            original_port,
            extra={
                'switchport': {
                    'mode': 'access'
                    # Missing native_vlan
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [original_port]
            self.assertRaises(
                exception.InvalidParameterValue,
                self.interface.port_changed, task, current_port)

        # Should not call update_port due to invalid config
        mock_update_port.assert_not_called()


class IronicNetworkingPortgroupChangedTestCase(
        IronicNetworkingTestCase):

    def test_portgroup_changed_logs_message(self):
        """Test that portgroup_changed logs an appropriate message."""
        portgroup = self._create_test_portgroup(name='test-pg')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            with mock.patch('ironic.drivers.modules.network.'
                            'ironic_networking.LOG',
                            autospec=True) as mock_log:
                self.interface.portgroup_changed(task, portgroup)
                mock_log.debug.assert_called_once_with(
                    "Portgroup %(portgroup)s (%(name)s) configuration "
                    "changed - portgroup changes not currently supported by "
                    "ironic-networking interface",
                    {'portgroup': portgroup.uuid, 'name': 'test-pg'})

    def test_portgroup_changed_logs_message_unnamed(self):
        """Test that portgroup_changed logs an appropriate message.

        For unnamed portgroup.
        """
        portgroup = self._create_test_portgroup(name=None)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            with mock.patch('ironic.drivers.modules.network.'
                            'ironic_networking.LOG',
                            autospec=True) as mock_log:
                self.interface.portgroup_changed(task, portgroup)
                mock_log.debug.assert_called_once_with(
                    "Portgroup %(portgroup)s (%(name)s) configuration "
                    "changed - portgroup changes not currently supported by "
                    "ironic-networking interface",
                    {'portgroup': portgroup.uuid, 'name': 'unnamed'})


class IronicNetworkingHelperMethodsTestCase(
        IronicNetworkingTestCase):

    def test_get_port_switch_info(self):
        """Test _get_port_switch_info method."""
        port = self._create_test_port()
        switch_id, port_name = self.interface._get_port_switch_info(port)
        self.assertEqual('00:11:22:33:44:55', switch_id)
        self.assertEqual('GigE1/0/1', port_name)

    def test_get_port_switch_info_no_local_link_connection(self):
        """Test _get_port_switch_info with no local_link_connection."""
        port = self._create_test_port(local_link_connection=None)
        switch_id, port_name = self.interface._get_port_switch_info(port)
        self.assertIsNone(switch_id)
        self.assertIsNone(port_name)

    def test_get_port_description(self):
        """Test _get_port_description method."""
        port = self._create_test_port()
        description = self.interface._get_port_description(port)
        self.assertEqual(f'Ironic Port {port.uuid}', description)

    def test_get_portgroup_description_named(self):
        """Test _get_portgroup_description for a named portgroup."""
        portgroup = self._create_test_portgroup(name='pg-name')
        description = self.interface._get_portgroup_description(portgroup)
        self.assertEqual(f'Ironic PortGroup {portgroup.uuid}', description)

    def test_get_portgroup_description_unnamed(self):
        """Test _get_portgroup_description fallback."""
        portgroup = self._create_test_portgroup(name=None)
        description = self.interface._get_portgroup_description(portgroup)
        expected = f'Ironic PortGroup {portgroup.uuid}'
        self.assertEqual(expected, description)

    def test_get_portgroup_lag_name_named(self):
        """Test _get_portgroup_lag_name with explicit name."""
        portgroup = self._create_test_portgroup(name='named-group')
        name = self.interface._get_portgroup_lag_name(portgroup)
        self.assertEqual('named-group', name)

    def test_get_portgroup_lag_name_unnamed(self):
        """Test _get_portgroup_lag_name without name."""
        portgroup = self._create_test_portgroup(name=None)
        name = self.interface._get_portgroup_lag_name(portgroup)
        expected = f'lag-{portgroup.uuid[:8]}'
        self.assertEqual(expected, name)

    def test_get_portgroup_switch_ids(self):
        """Test _get_portgroup_switch_ids collects unique IDs."""
        portgroup = self._create_test_portgroup(
            extra={'lag': {
                'mode': 'access',
                'aggregation_mode': 'static'
            }}
        )
        port_one = self._create_test_port(
            portgroup_id=portgroup.id,
            local_link_connection={
                'switch_id': 'switch-1',
                'port_id': 'Eth1/1'
            },
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        port_two = self._create_test_port(
            portgroup_id=portgroup.id,
            local_link_connection={
                'switch_id': 'switch-2',
                'port_id': 'Eth1/2'
            },
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.portgroups = [portgroup]
            task.ports = [port_one, port_two]
            result = self.interface._get_portgroup_switch_ids(
                task, portgroup)
        self.assertCountEqual(['switch-1', 'switch-2'], result)

    def test_get_portgroup_switch_ids_no_lag(self):
        """Test _get_portgroup_switch_ids returns None when unused."""
        portgroup = self._create_test_portgroup(extra={})
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.portgroups = [portgroup]
            task.ports = []
            result = self.interface._get_portgroup_switch_ids(
                task, portgroup)
        self.assertIsNone(result)

    def test_get_network_type_for_state_mappings(self):
        """Test get_network_type_for_state state mappings."""
        state_map = {
            states.INSPECTING: 'inspection',
            states.INSPECTWAIT: 'inspection',
            states.CLEANING: 'cleaning',
            states.CLEANWAIT: 'cleaning',
            states.DEPLOYING: 'provisioning',
            states.DEPLOYWAIT: 'provisioning',
            states.ACTIVE: 'tenant',
            states.RESCUE: 'rescuing',
            states.RESCUING: 'rescuing',
            states.RESCUEWAIT: 'rescuing',
            states.SERVICING: 'servicing',
            states.SERVICEWAIT: 'servicing'
        }
        for provision_state, expected in state_map.items():
            self.assertEqual(
                expected,
                network.get_network_type_for_state(provision_state))

    def test_get_network_type_for_state_default_idle(self):
        """Test get_network_type_for_state returns idle for unknown states."""
        self.assertEqual(
            'idle', network.get_network_type_for_state(states.MANAGEABLE))
        self.assertEqual(
            'idle', network.get_network_type_for_state(states.ENROLL))

    def test_get_network_mode_and_vlan_driver_info(self):
        """Driver info overrides networking configuration."""
        driver_info = dict(self.node.driver_info or {})
        driver_info['provisioning_network'] = (
            'access/native_vlan=66')
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mode, native_vlan, allowed = (
                self.interface._get_network_mode_and_vlan(
                    task, 'provisioning'))
        self.assertEqual('access', mode)
        self.assertEqual(66, native_vlan)
        self.assertIsNone(allowed)

    def test_get_network_mode_and_vlan_conf_fallback(self):
        """Global networking configuration is used when no override."""
        driver_info = dict(self.node.driver_info or {})
        driver_info.pop('cleaning_network', None)
        self.node.driver_info = driver_info
        self.node.save()
        self.config(cleaning_network='trunk/native_vlan=77',
                    group='ironic_networking')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mode, native_vlan, allowed = (
                self.interface._get_network_mode_and_vlan(
                    task, 'cleaning'))
        self.assertEqual('trunk', mode)
        self.assertEqual(77, native_vlan)
        self.assertIsNone(allowed)

    def test_get_network_mode_and_vlan_invalid_format(self):
        """Invalid configuration raises InvalidParameterValue."""
        driver_info = dict(self.node.driver_info or {})
        driver_info['provisioning_network'] = 'invalid'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface._get_network_mode_and_vlan,
                              task, 'provisioning')

    def test_resolve_network_configuration_prefers_network(self):
        """_resolve_network_configuration prefers global network config."""
        driver_info = dict(self.node.driver_info or {})
        driver_info['provisioning_network'] = (
            'hybrid/native_vlan=88')
        self.node.driver_info = driver_info
        self.node.save()
        port = self._create_test_port(
            extra={'switchport': {
                'mode': 'access',
                'native_vlan': 10,
                'allowed_vlans': [10, 11]
            }}
        )
        with (task_manager.acquire(self.context, self.node.uuid) as task):
            task.ports = [port]
            mode, vlan, allowed = (
                self.interface._resolve_network_configuration(
                    task, port, 'provisioning')
            )
        self.assertEqual('hybrid', mode)
        self.assertEqual(88, vlan)
        self.assertIsNone(allowed)

    def test_resolve_network_configuration_fallback_switchport(self):
        """_resolve_network_configuration falls back to switchport."""
        driver_info = dict(self.node.driver_info or {})
        driver_info.pop('provisioning_network', None)
        self.node.driver_info = driver_info
        self.node.save()
        port = self._create_test_port(
            extra={'switchport': {
                'mode': 'hybrid',
                'native_vlan': 55,
                'allowed_vlans': [55, 56]
            }}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            mode, vlan, allowed = (
                self.interface._resolve_network_configuration(
                    task, port, 'provisioning')
            )
        self.assertEqual('hybrid', mode)
        self.assertEqual(55, vlan)
        self.assertEqual([55, 56], allowed)

    def test_validate_portgroup_members_missing_switchport(self):
        """Portgroup validation raises when member lacks switchport."""
        portgroup = self._create_test_portgroup(
            extra={'lag': {
                'mode': 'access',
                'aggregation_mode': 'static'
            }}
        )
        member_port = self._create_test_port(
            portgroup_id=portgroup.id,
            extra={}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.portgroups = [portgroup]
            task.ports = [member_port]
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)


class IronicNetworkingNetworkActionsTestCase(
        IronicNetworkingTestCase):

    def setUp(self):
        super(IronicNetworkingNetworkActionsTestCase, self).setUp()
        self.port = self._create_test_port(
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )

    def _expected_update_call(self, description, mode, native_vlan,
                              allowed_vlans=None, default_vlan=None):
        signature = inspect.signature(networking_api.update_port)
        expected_kwargs = {'allowed_vlans': allowed_vlans}
        if 'lag_name' in signature.parameters:
            expected_kwargs['lag_name'] = None
        if 'default_vlan' in signature.parameters:
            expected_kwargs['default_vlan'] = default_vlan
        return (mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', description,
                mode, native_vlan), expected_kwargs

    def _prepare_task(self, provision_state):
        self.node.provision_state = provision_state
        self.node.save()
        task = task_manager.acquire(self.context, self.node.uuid)
        task.ports = [self.port]
        return task

    def _configure_driver_info(self, network_type, value):
        key = f'{network_type}_network'
        driver_info = dict(self.node.driver_info or {})
        driver_info[key] = value
        self.node.driver_info = driver_info
        self.node.save()

    def _test_add_network(self, method_name, provision_state,
                          network_type, config_value=None):
        if config_value is not None:
            self._configure_driver_info(network_type, config_value)
        with mock.patch.object(networking_api, 'update_port',
                               autospec=True) as update_mock:
            update_mock.return_value = {'status': 'updated'}
            with self._prepare_task(provision_state) as task:
                getattr(self.interface, method_name)(task)
        update_mock.assert_called()
        return update_mock

    def _test_remove_network(self, method_name, provision_state,
                             network_type, config_value=None):
        if config_value is not None:
            self._configure_driver_info(network_type, config_value)
        with mock.patch.object(networking_api, 'reset_port',
                               autospec=True) as reset_mock:
            reset_mock.return_value = {'status': 'reset'}
            with self._prepare_task(provision_state) as task:
                getattr(self.interface, method_name)(task)
        reset_mock.assert_called()
        return reset_mock

    def test_add_provisioning_network_with_config(self):
        mock_call = self._test_add_network(
            'add_provisioning_network', states.DEPLOYING, 'provisioning',
            'trunk/native_vlan=200')
        expected_args, expected_kwargs = self._expected_update_call(
            f'Ironic Port {self.port.uuid}', 'trunk', 200)
        mock_call.assert_called_with(*expected_args, **expected_kwargs)

    def test_remove_provisioning_network_with_config(self):
        mock_call = self._test_remove_network(
            'remove_provisioning_network', states.DEPLOYING,
            'provisioning', 'access/native_vlan=200')
        mock_call.assert_called_with(
            mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', 200,
            allowed_vlans=None, default_vlan=None)

    def test_add_provisioning_network_with_idle(self):
        CONF.set_override('idle_network', 'access/native_vlan=1',
                          group='ironic_networking')
        mock_call = self._test_add_network(
            'add_provisioning_network', states.DEPLOYING, 'provisioning',
            'trunk/native_vlan=200')
        expected_args, expected_kwargs = self._expected_update_call(
            f'Ironic Port {self.port.uuid}',
            'trunk', 200, default_vlan=1)
        mock_call.assert_called_with(*expected_args, **expected_kwargs)

    def test_remove_provisioning_network_with_idle(self):
        CONF.set_override('idle_network', 'access/native_vlan=1',
                          group='ironic_networking')
        mock_call = self._test_remove_network(
            'remove_provisioning_network', states.DEPLOYING,
            'provisioning', 'access/native_vlan=200')
        mock_call.assert_called_with(
            mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', 200,
            allowed_vlans=None, default_vlan=1)

    def test_add_cleaning_network_without_config(self):
        mock_call = self._test_add_network('add_cleaning_network',
                                           states.CLEANING, 'cleaning')
        expected_args, expected_kwargs = self._expected_update_call(
            f'Ironic Port {self.port.uuid}', 'access', 100)
        mock_call.assert_called_with(*expected_args, **expected_kwargs)

    def test_remove_cleaning_network_without_config(self):
        mock_call = self._test_remove_network('remove_cleaning_network',
                                              states.CLEANING, 'cleaning')
        mock_call.assert_called_with(
            mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=None, default_vlan=None)

    def test_add_rescuing_network_with_config(self):
        mock_call = self._test_add_network(
            'add_rescuing_network', states.RESCUING, 'rescuing',
            'access/native_vlan=333')
        expected_args, expected_kwargs = self._expected_update_call(
            f'Ironic Port {self.port.uuid}', 'access', 333)
        mock_call.assert_called_with(*expected_args, **expected_kwargs)

    def test_remove_rescuing_network_with_config(self):
        mock_call = self._test_remove_network(
            'remove_rescuing_network', states.RESCUING,
            'rescuing', 'access/native_vlan=333')
        mock_call.assert_called_with(
            mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', 333,
            allowed_vlans=None, default_vlan=None)

    def test_add_inspection_network_without_config(self):
        mock_call = self._test_add_network('add_inspection_network',
                                           states.INSPECTING, 'inspection')
        expected_args, expected_kwargs = self._expected_update_call(
            f'Ironic Port {self.port.uuid}', 'access', 100)
        mock_call.assert_called_with(*expected_args, **expected_kwargs)

    def test_remove_inspection_network_without_config(self):
        mock_call = self._test_remove_network('remove_inspection_network',
                                              states.INSPECTING,
                                              'inspection')
        mock_call.assert_called_with(
            mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=None, default_vlan=None)

    def test_add_servicing_network_with_config(self):
        mock_call = self._test_add_network(
            'add_servicing_network', states.SERVICING, 'servicing',
            'access/native_vlan=444')
        expected_args, expected_kwargs = self._expected_update_call(
            f'Ironic Port {self.port.uuid}', 'access', 444)
        mock_call.assert_called_with(*expected_args, **expected_kwargs)

    def test_remove_servicing_network_with_config(self):
        mock_call = self._test_remove_network(
            'remove_servicing_network', states.SERVICING,
            'servicing', 'access/native_vlan=444')
        mock_call.assert_called_with(
            mock.ANY, '00:11:22:33:44:55', 'GigE1/0/1', 444,
            allowed_vlans=None, default_vlan=None)

    def test_configure_tenant_networks(self):
        with mock.patch.object(networking_api, 'update_port',
                               autospec=True) as update_mock:
            update_mock.return_value = {'status': 'updated'}
            with task_manager.acquire(self.context, self.node.uuid) as task:
                task.ports = [self.port]
                self.interface.configure_tenant_networks(task)
        update_mock.assert_called_with(
            self.context, '00:11:22:33:44:55', 'GigE1/0/1',
            f'Ironic Port {self.port.uuid}', 'access', 100,
            allowed_vlans=None, lag_name=None, default_vlan=None)

    def test_unconfigure_tenant_networks(self):
        with mock.patch.object(networking_api, 'reset_port',
                               autospec=True) as reset_mock:
            reset_mock.return_value = {'status': 'reset'}
            with task_manager.acquire(self.context, self.node.uuid) as task:
                task.ports = [self.port]
                self.interface.unconfigure_tenant_networks(task)
        reset_mock.assert_called_with(
            self.context, '00:11:22:33:44:55', 'GigE1/0/1', 100,
            allowed_vlans=None, default_vlan=None)

    def test_validate_rescue_success(self):
        with self._prepare_task(states.RESCUING) as task:
            self.interface.validate_rescue(task)

    def test_validate_inspection_success(self):
        with self._prepare_task(states.INSPECTING) as task:
            self.interface.validate_inspection(task)

    def test_validate_rescue_missing_configuration(self):
        port = self._create_test_port(extra={})
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port]
            self.assertIsNone(
                self.interface._validate_network_requirements(
                    task, 'rescuing'))

    def test_need_power_on(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertFalse(self.interface.need_power_on(task))

    def test_get_node_network_data_present(self):
        self.node.network_data = {'foo': 'bar'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual({'foo': 'bar'},
                             self.interface.get_node_network_data(task))

    def test_get_node_network_data_default(self):
        """Generates network data from ports when static data not set."""
        self.node.network_data = None
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)
            # Should generate links from the port created in setUp
            self.assertIn('links', result)
            self.assertEqual(1, len(result['links']))
            # Verify the physical link was created
            link = result['links'][0]
            self.assertEqual(self.port.uuid, link['id'])
            self.assertEqual('phy', link['type'])
            self.assertEqual(self.port.address, link['ethernet_mac_address'])
            self.assertEqual(1500, link['mtu'])

    def test_validate_portgroup_members_missing_local_link(self):
        """Portgroup validation raises when member lacks local link."""
        portgroup = self._create_test_portgroup(
            extra={'lag': {
                'mode': 'access',
                'aggregation_mode': 'static'
            }}
        )
        member_port = self._create_test_port(
            portgroup_id=portgroup.id,
            local_link_connection={
                'switch_id': None,
                'port_id': None
            },
            extra={'switchport': {'mode': 'access', 'native_vlan': 100}}
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.portgroups = [portgroup]
            task.ports = [member_port]
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate, task)


class GetNodeNetworkDataTestCase(IronicNetworkingTestCase):
    """Test cases for get_node_network_data method."""

    def test_get_node_network_data_static_precedence(self):
        """Static network_data takes precedence over generated data."""
        static_data = {
            'links': [{'id': 'static', 'type': 'phy'}],
            'networks': [],
            'services': []
        }
        self.node.network_data = static_data
        self.node.save()

        # Create a port that would generate data if static wasn't present
        self._create_test_port()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        self.assertEqual(static_data, result)

    def test_get_node_network_data_empty_ports(self):
        """Returns empty links when no ports exist."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        self.assertEqual({'links': []}, result)

    def test_get_node_network_data_single_port_access_mode(self):
        """Generates physical link for port in access mode (no VLANs)."""
        mac = self._generate_test_mac()
        port = self._create_test_port(
            address=mac,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Should have only one physical link, no VLANs
        self.assertEqual(1, len(result['links']))
        link = result['links'][0]
        self.assertEqual(port.uuid, link['id'])
        self.assertEqual('phy', link['type'])
        self.assertEqual(mac, link['ethernet_mac_address'])
        self.assertEqual(1500, link['mtu'])
        self.assertNotIn('vif_id', link)

    def test_get_node_network_data_single_port_trunk_mode(self):
        """Generates physical link and VLAN interfaces for trunk mode."""
        mac = self._generate_test_mac()
        allowed_vlans = [100, 200, 300]
        port = self._create_test_port(
            address=mac,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': allowed_vlans
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Should have 1 physical link + 3 VLAN links
        self.assertEqual(4, len(result['links']))

        # Check physical link
        phy_link = result['links'][0]
        self.assertEqual(port.uuid, phy_link['id'])
        self.assertEqual('phy', phy_link['type'])
        self.assertEqual(mac, phy_link['ethernet_mac_address'])
        self.assertEqual(1500, phy_link['mtu'])

        # Check VLAN links
        vlan_links = result['links'][1:]
        self.assertEqual(3, len(vlan_links))
        for i, vlan_link in enumerate(vlan_links):
            expected_vlan_id = allowed_vlans[i]
            self.assertEqual(f'{port.uuid}_vlan_{expected_vlan_id}',
                             vlan_link['id'])
            self.assertEqual('vlan', vlan_link['type'])
            self.assertEqual(mac, vlan_link['vlan_mac_address'])
            self.assertEqual(expected_vlan_id, vlan_link['vlan_id'])
            self.assertEqual(port.uuid, vlan_link['vlan_link'])
            self.assertEqual(1500, vlan_link['mtu'])

    def test_get_node_network_data_single_port_hybrid_mode(self):
        """Generates physical link and VLAN interfaces for hybrid mode."""
        mac = self._generate_test_mac()
        allowed_vlans = [200, 300]
        port = self._create_test_port(
            address=mac,
            extra={
                'switchport': {
                    'mode': 'hybrid',
                    'native_vlan': 100,
                    'allowed_vlans': allowed_vlans
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Should have 1 physical link + 2 VLAN links
        self.assertEqual(3, len(result['links']))

        # Check physical link
        phy_link = result['links'][0]
        self.assertEqual(port.uuid, phy_link['id'])
        self.assertEqual('phy', phy_link['type'])

        # Check VLAN links
        vlan_links = result['links'][1:]
        self.assertEqual(2, len(vlan_links))
        vlan_ids = [vl['vlan_id'] for vl in vlan_links]
        self.assertEqual(allowed_vlans, vlan_ids)

    def test_get_node_network_data_multiple_ports(self):
        """Generates links for multiple ports with mixed configurations."""
        mac1 = self._generate_test_mac()
        mac2 = self._generate_test_mac()

        port1 = self._create_test_port(
            address=mac1,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        port2 = self._create_test_port(
            address=mac2,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': [200, 300]
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Port1: 1 phy, Port2: 1 phy + 2 vlans = 4 total
        self.assertEqual(4, len(result['links']))

        # Find links by MAC to verify correct association
        port1_links = [l1 for l1 in result['links']
                       if l1.get('ethernet_mac_address') == mac1
                       or l1.get('vlan_mac_address') == mac1]
        port2_links = [l2 for l2 in result['links']
                       if l2.get('ethernet_mac_address') == mac2
                       or l2.get('vlan_mac_address') == mac2]

        self.assertEqual(1, len(port1_links))  # Only physical
        self.assertEqual(3, len(port2_links))  # Physical + 2 VLANs

        self.assertEqual(port1.uuid, result['links'][0]['id'])
        self.assertEqual(port2.uuid, result['links'][1]['id'])

    def test_get_node_network_data_port_without_mac(self):
        """Skips ports without MAC addresses."""
        port1 = self._create_test_port(
            address=None,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        mac2 = self._generate_test_mac()
        port2 = self._create_test_port(
            address=mac2,
            extra={
                'switchport': {
                    'mode': 'access',
                    'native_vlan': 100
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Only port2 should generate a link
        self.assertEqual(1, len(result['links']))
        self.assertEqual(port2.uuid, result['links'][0]['id'])
        self.assertEqual(mac2, result['links'][0]['ethernet_mac_address'])

        # port1 should be ignored
        self.assertNotEqual(port1.uuid, result['links'][0]['id'])

    def test_get_node_network_data_port_without_switchport(self):
        """Generates physical link only for port without switchport config."""
        mac = self._generate_test_mac()
        port = self._create_test_port(address=mac, extra={})

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Should have only physical link, no VLANs
        self.assertEqual(1, len(result['links']))
        link = result['links'][0]
        self.assertEqual(port.uuid, link['id'])
        self.assertEqual('phy', link['type'])
        self.assertEqual(mac, link['ethernet_mac_address'])

    def test_get_node_network_data_port_with_empty_allowed_vlans(self):
        """Port with empty allowed_vlans generates only physical link."""
        mac = self._generate_test_mac()
        port = self._create_test_port(
            address=mac,
            extra={
                'switchport': {
                    'mode': 'trunk',
                    'native_vlan': 100,
                    'allowed_vlans': []
                }
            }
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Should have only physical link, no VLANs
        self.assertEqual(1, len(result['links']))
        link = result['links'][0]
        self.assertEqual(port.uuid, link['id'])
        self.assertEqual('phy', link['type'])

    def test_get_node_network_data_port_with_none_extra(self):
        """Handles port with None extra field gracefully."""
        mac = self._generate_test_mac()
        port = self._create_test_port(address=mac, extra=None)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.interface.get_node_network_data(task)

        # Should have only physical link
        self.assertEqual(1, len(result['links']))
        link = result['links'][0]
        self.assertEqual(port.uuid, link['id'])
        self.assertEqual('phy', link['type'])
        self.assertEqual(mac, link['ethernet_mac_address'])
