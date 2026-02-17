# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Test class for autodetect deploy."""

from unittest import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules import autodetect
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class AutodetectDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AutodetectDeployTestCase, self).setUp()

        # Enable required deploy interfaces for autodetect to use
        self.config(
            autodetect_deploy_interfaces=['bootc', 'direct'],
            enabled_deploy_interfaces=['autodetect', 'direct', 'bootc'],
            default_deploy_interface='autodetect',
        )

        # Create a test node
        instance_info = {'image_source': 'http://example.com/image'}
        self.node = obj_utils.create_test_node(
            self.context,
            bios_interface='fake',
            boot_interface='fake',
            console_interface='fake',
            deploy_interface='autodetect',
            firmware_interface='no-firmware',
            inspect_interface='no-inspect',
            management_interface='fake',
            network_interface='noop',
            power_interface='fake',
            raid_interface='no-raid',
            rescue_interface='no-rescue',
            storage_interface='noop',
            vendor_interface='no-vendor',
            instance_info=instance_info)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)
        self.deploy = autodetect.AutodetectDeploy()

    def test_init_validates_enabled_interfaces(self):
        """Test __init__ validates interfaces are enabled."""
        # This should not raise since setUp configured both bootc and direct
        # as enabled
        deploy = autodetect.AutodetectDeploy()
        self.assertIsNotNone(deploy)

    def test_init_raises_when_interface_not_enabled(self):
        """Test __init__ raises when autodetect interface not enabled."""
        # Configure autodetect to use 'ansible' but don't enable it
        self.config(
            autodetect_deploy_interfaces=['ansible', 'direct'],
            enabled_deploy_interfaces=['autodetect', 'direct'],
        )

        # Should raise InvalidParameterValue
        exc = self.assertRaises(exception.InvalidParameterValue,
                                autodetect.AutodetectDeploy)
        self.assertIn('ansible', str(exc))
        self.assertIn('enabled_deploy_interfaces', str(exc))

    def test_init_raises_when_multiple_interfaces_not_enabled(self):
        """Test __init__ raises for first non-enabled interface."""
        # Configure multiple autodetect interfaces that aren't enabled
        self.config(
            autodetect_deploy_interfaces=['ansible', 'ramdisk', 'direct'],
            enabled_deploy_interfaces=['autodetect', 'direct'],
        )

        # Should raise for the first one encountered (ansible)
        exc = self.assertRaises(exception.InvalidParameterValue,
                                autodetect.AutodetectDeploy)
        self.assertIn('ansible', str(exc))

    def test_get_properties(self):
        """Test get_properties returns an empty dict."""
        props = self.deploy.get_properties()
        self.assertEqual({}, props)

    @mock.patch.object(autodetect.AutodetectDeploy,
                      '_create_switchable_interface', autospec=True)
    def test_validate(self, mock_create_switch):
        """Test validate calls validate on the switched interface."""
        mock_interface = mock.MagicMock()
        mock_create_switch.return_value = (mock_interface, 'direct', True)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.validate(task)
            mock_create_switch.assert_called_once_with(self.deploy, task)
            mock_interface.validate.assert_called_once_with(task)

    def test_deploy_raises_exception(self):
        """Test deploy raises InstanceDeployFailure.

        The deploy method should never be called since autodetect
        should switch to a concrete interface before deployment.
        """
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                            self.deploy.deploy, task)

    def test_tear_down(self):
        """Test tear_down completes without error."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.deploy.tear_down(task)
            # Should return None and not raise any exceptions
            self.assertIsNone(result)

    def test_prepare_raises_exception(self):
        """Test prepare raises InstanceDeployFailure.

        The prepare method should never be called since autodetect
        should switch to a concrete interface before deployment.
        """
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                            self.deploy.prepare, task)

    def test_clean_up(self):
        """Test clean_up completes without error."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.deploy.clean_up(task)
            # Should return None and not raise any exceptions
            self.assertIsNone(result)

    def test_take_over(self):
        """Test take_over completes without error."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = self.deploy.take_over(task)
            # Should return None and not raise any exceptions
            self.assertIsNone(result)

    @mock.patch('ironic.common.driver_factory.get_interface', autospec=True)
    @mock.patch('ironic.common.driver_factory.get_hardware_type',
                autospec=True)
    def test__create_switchable_interface_bootc(self, mock_get_hw_type,
                                                mock_get_interface):
        """Test _create_switchable_interface selects bootc."""
        mock_hw_type = mock.MagicMock()
        mock_get_hw_type.return_value = mock_hw_type

        # Mock bootc to support
        mock_bootc_interface = mock.MagicMock()
        mock_bootc_interface.supports_deploy.return_value = True

        # Return different interfaces based on the interface_name argument
        def get_interface_side_effect(hw_type, iface_type, iface_name):
            if iface_name == 'bootc':
                return mock_bootc_interface
            return mock.MagicMock()

        mock_get_interface.side_effect = get_interface_side_effect

        with task_manager.acquire(self.context, self.node.uuid) as task:
            switchable = self.deploy._create_switchable_interface(task)
            interface, name, supports = switchable

            # Should select bootc (second in priority list)
            self.assertEqual('bootc', name)
            self.assertTrue(supports)
            self.assertEqual(mock_bootc_interface, interface)

    @mock.patch('ironic.common.driver_factory.get_interface', autospec=True)
    @mock.patch('ironic.common.driver_factory.get_hardware_type',
                autospec=True)
    def test__create_switchable_interface_fallback(self, mock_get_hw_type,
                                                   mock_get_interface):
        """Test _create_switchable_interface falls back to last interface."""
        mock_hw_type = mock.MagicMock()
        mock_get_hw_type.return_value = mock_hw_type

        # Mock all interfaces to not support
        mock_ramdisk_interface = mock.MagicMock()
        mock_ramdisk_interface.supports_deploy.return_value = False

        mock_bootc_interface = mock.MagicMock()
        mock_bootc_interface.supports_deploy.return_value = False

        mock_direct_interface = mock.MagicMock()
        mock_direct_interface.supports_deploy.return_value = False

        def get_interface_side_effect(hw_type, iface_type, iface_name):
            if iface_name == 'bootc':
                return mock_bootc_interface
            elif iface_name == 'direct':
                return mock_direct_interface
            return mock.MagicMock()

        mock_get_interface.side_effect = get_interface_side_effect

        with task_manager.acquire(self.context, self.node.uuid) as task:
            switchable = self.deploy._create_switchable_interface(task)
            interface, name, supports = switchable

            # Should fallback to direct (last in priority list)
            self.assertEqual('direct', name)
            self.assertFalse(supports)
            self.assertEqual(mock_direct_interface, interface)

    @mock.patch('ironic.common.driver_factory.get_interface', autospec=True)
    @mock.patch('ironic.common.driver_factory.get_hardware_type',
                autospec=True)
    def test__create_switchable_interface_no_valid_interfaces(
            self, mock_get_hw_type, mock_get_interface):
        """Test _create_switchable_interface with empty config."""
        # Configure empty autodetect_deploy_interfaces
        self.config(
            autodetect_deploy_interfaces=[],
        )

        mock_hw_type = mock.MagicMock()
        mock_get_hw_type.return_value = mock_hw_type

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                            self.deploy._create_switchable_interface, task)

    @mock.patch.object(autodetect.LOG, 'info', autospec=True)
    @mock.patch.object(autodetect.AutodetectDeploy,
                      '_create_switchable_interface', autospec=True)
    def test_switch_interface(self, mock_create_switch, mock_log_info):
        """Test switch_interface switches to detected interface."""
        mock_interface = mock.MagicMock()
        mock_create_switch.return_value = (mock_interface, 'bootc', True)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            original_interface = task.node.deploy_interface
            self.deploy.switch_interface(task)

            # Verify the interface was switched
            self.assertEqual('bootc', task.node.deploy_interface)
            self.assertEqual(mock_interface, task.driver.deploy)

            # Verify original interface was saved
            self.assertEqual(
                original_interface,
                task.node.driver_internal_info['original_deploy_interface'])

            # Verify log message
            mock_log_info.assert_called_once_with(
                "autodetect switching to deploy interface: %s", "bootc")

    @mock.patch.object(autodetect.LOG, 'warning', autospec=True)
    @mock.patch.object(autodetect.LOG, 'info', autospec=True)
    @mock.patch.object(autodetect.AutodetectDeploy,
                      '_create_switchable_interface', autospec=True)
    def test_switch_interface_not_supported(self, mock_create_switch,
                                            mock_log_info, mock_log_warning):
        """Test switch_interface with no supported interface."""
        mock_interface = mock.MagicMock()
        # Interface is not supported (last parameter is False)
        mock_create_switch.return_value = (mock_interface, 'direct', False)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.switch_interface(task)

            # Verify warning was logged
            self.assertTrue(mock_log_warning.called)
            warning_msg, interface = mock_log_warning.call_args[0]
            self.assertIn("No deploy interfaces", warning_msg)
            self.assertEqual("direct", interface)

            # Verify the interface was still switched to the fallback
            self.assertEqual('direct', task.node.deploy_interface)
            self.assertEqual(mock_interface, task.driver.deploy)

    @mock.patch.object(autodetect.AutodetectDeploy,
                      '_create_switchable_interface', autospec=True)
    def test_switch_interface_preserves_node_state(self, mock_create_switch):
        """Test switch_interface saves node state correctly."""
        mock_interface = mock.MagicMock()
        mock_create_switch.return_value = (mock_interface, 'bootc', True)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            original_interface = task.node.deploy_interface

            self.deploy.switch_interface(task)

            # Reload the node from the database
            task.node.refresh()

            # Verify changes were persisted
            self.assertEqual('bootc', task.node.deploy_interface)
            self.assertEqual(
                original_interface,
                task.node.driver_internal_info['original_deploy_interface'])
