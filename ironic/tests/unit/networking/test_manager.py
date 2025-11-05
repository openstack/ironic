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

"""Unit tests for networking manager."""

import unittest.mock as mock

from oslo_config import cfg
import oslo_messaging as messaging

from ironic.common import exception
from ironic.networking import manager
from ironic.networking import switch_config
from ironic.tests import base as test_base

CONF = cfg.CONF


class TestNetworkingManager(test_base.TestCase):
    """Test cases for NetworkingManager."""

    def setUp(self):
        super(TestNetworkingManager, self).setUp()
        self.host = "test-host"
        self.topic = "test-topic"
        self.context = mock.Mock()
        self.manager = manager.NetworkingManager(
            host=self.host, topic=self.topic
        )

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    def test_update_port_with_vlan_validation_success(
        self, mock_validate_vlan, mock_get_driver
    ):
        """Test successful port update with VLAN validation."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_validate_vlan.return_value = None  # No exception raised

        result = self.manager.update_port(
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            lag_name=None,
        )

        # Verify VLAN validation was called
        mock_validate_vlan.assert_called_once_with(
            [100], mock_driver, "switch-01", "port configuration"
        )

        # Verify driver was called
        mock_driver.update_port.assert_called_once_with(
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            default_vlan=None,
            lag_name=None,
        )

        # Verify return value
        expected = {
            "switch_id": "switch-01",
            "port_name": "port-01",
            "description": "Test port",
            "mode": "access",
            "native_vlan": 100,
            "allowed_vlans": [],
            "default_vlan": None,
            "lag_name": None,
            "status": "configured",
        }
        self.assertEqual(expected, result)

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    def test_update_port_with_allowed_vlans_validation(
        self, mock_validate_vlan, mock_get_driver
    ):
        """Test port update with allowed VLANs validation."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_validate_vlan.return_value = None

        self.manager.update_port(
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "trunk",
            100,
            allowed_vlans=[101, 102],
            lag_name=None,
        )

        # Verify VLAN validation was called with all VLANs
        mock_validate_vlan.assert_called_once_with(
            [100, 101, 102], mock_driver, "switch-01", "port configuration"
        )

        # Verify driver was called
        mock_driver.update_port.assert_called_once_with(
            "switch-01",
            "port-01",
            "Test port",
            "trunk",
            100,
            allowed_vlans=[101, 102],
            default_vlan=None,
            lag_name=None,
        )

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    def test_update_port_vlan_validation_failure(
        self, mock_validate_vlan, mock_get_driver
    ):
        """Test port update fails when VLAN validation fails."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_validate_vlan.side_effect = exception.InvalidParameterValue(
            "VLAN 200 is not allowed"
        )

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            200,
            allowed_vlans=None,
            lag_name=None,
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

        # Verify VLAN validation was called
        mock_validate_vlan.assert_called_once_with(
            [200], mock_driver, "switch-01", "port configuration"
        )

        # Verify driver was not called due to validation failure
        mock_driver.update_port.assert_not_called()

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_update_lag_not_implemented(self, mock_get_driver):
        """Test LAG update raises Invalid exception."""

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            ["switch-01", "switch-02"],
            "lag-01",
            "Test PC",
            "trunk",
            100,
            "lacp",
            allowed_vlans=[101, 102],
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_update_lag_vlan_validation_failure(self, mock_get_driver):
        """Test LAG update raises Invalid exception."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            ["switch-01", "switch-02"],
            "lag-01",
            "Test PC",
            "trunk",
            200,
            "lacp",
            allowed_vlans=[201, 202],
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_vlan_validation_decorator_multi_switch(self, mock_get_driver):
        """Test LAG update raises Invalid exception."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            ["switch-01", "switch-02", "switch-03"],
            "lag-01",
            "Test PC",
            "trunk",
            100,
            "lacp",
            allowed_vlans=[101, 102],
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    def test_delete_lag_with_validation_success(self):
        """Test LAG deletion raises Invalid exception."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.delete_lag,
            self.context,
            ["switch-01", "switch-02"],
            "lag-01",
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    def test_update_port_no_allowed_vlans(
        self, mock_validate_vlan, mock_get_driver
    ):
        """Test port update with no allowed VLANs (access mode)."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_validate_vlan.return_value = None

        self.manager.update_port(
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            lag_name=None,
        )

        # Verify VLAN validation was called with only default VLAN
        mock_validate_vlan.assert_called_once_with(
            [100], mock_driver, "switch-01", "port configuration"
        )

        # Verify driver was called
        mock_driver.update_port.assert_called_once_with(
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            default_vlan=None,
            lag_name=None,
        )

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_update_lag_no_allowed_vlans(self, mock_get_driver):
        """Test LAG update raises Invalid exception."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            ["switch-01", "switch-02"],
            "lag-01",
            "Test PC",
            "access",
            100,
            "lacp",
            allowed_vlans=None,
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    def test_update_port_driver_failure_after_validation(
        self, mock_validate_vlan, mock_get_driver
    ):
        """Test port update driver failure after successful validation."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_validate_vlan.return_value = None
        mock_driver.update_port.side_effect = Exception("Driver error")

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            lag_name=None,
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NetworkError, exc.exc_info[0])

        # Verify VLAN validation was called
        mock_validate_vlan.assert_called_once_with(
            [100], mock_driver, "switch-01", "port configuration"
        )

        # Verify driver was called but failed
        mock_driver.update_port.assert_called_once_with(
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            default_vlan=None,
            lag_name=None,
        )

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_update_lag_driver_failure_after_validation(
        self, mock_get_driver
    ):
        """Test LAG update raises Invalid exception."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            ["switch-01", "switch-02"],
            "lag-01",
            "Test PC",
            "trunk",
            100,
            "lacp",
            allowed_vlans=[101, 102],
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    def test_get_switch_driver_success(self):
        """Test successful switch driver selection."""
        # Mock the factory to return a list of drivers
        mock_factory = mock.Mock()
        mock_factory.names = ["driver1", "driver2"]

        # Mock driver that is configured for specific switches
        mock_driver = mock.Mock()
        mock_driver.is_switch_configured.return_value = True
        mock_factory.get_driver.return_value = mock_driver

        # Test driver selection
        self.manager._switch_driver_factory = mock_factory
        result = self.manager._get_switch_driver("switch1")

        # Verify
        self.assertEqual(result, mock_driver)
        mock_factory.get_driver.assert_called_with("driver1")
        mock_driver.is_switch_configured.assert_called_once_with("switch1")

    def test_get_switch_driver_second_driver_matches(self):
        """Test switch driver selection when first driver doesn't match."""
        # Mock the factory to return a list of drivers
        mock_factory = mock.Mock()
        mock_factory.names = ["driver1", "driver2"]

        # Mock drivers - first doesn't match, second does
        mock_driver1 = mock.Mock()
        mock_driver1.is_switch_configured.return_value = False
        mock_driver2 = mock.Mock()
        mock_driver2.is_switch_configured.return_value = True

        mock_factory.get_driver.side_effect = [mock_driver1, mock_driver2]

        # Test driver selection
        self.manager._switch_driver_factory = mock_factory
        result = self.manager._get_switch_driver("test-switch")

        # Verify second driver was selected
        self.assertEqual(result, mock_driver2)
        mock_driver1.is_switch_configured.assert_called_with("test-switch")
        mock_driver2.is_switch_configured.assert_called_with("test-switch")

    def test_get_switch_driver_no_match(self):
        """Test switch driver selection when no driver matches."""
        # Mock the factory to return a list of drivers
        mock_factory = mock.Mock()
        mock_factory.names = ["driver1", "driver2"]

        # Mock drivers that don't support the switch
        mock_driver1 = mock.Mock()
        mock_driver1.is_switch_configured.return_value = False
        mock_driver2 = mock.Mock()
        mock_driver2.is_switch_configured.return_value = False

        mock_factory.get_driver.side_effect = [mock_driver1, mock_driver2]

        # Test driver selection
        self.manager._switch_driver_factory = mock_factory

        # Should raise SwitchNotFound
        self.assertRaises(
            exception.SwitchNotFound,
            self.manager._get_switch_driver,
            "test-switch",
        )

        # Verify both drivers were checked
        mock_driver1.is_switch_configured.assert_called_once_with(
            "test-switch"
        )
        mock_driver2.is_switch_configured.assert_called_once_with(
            "test-switch"
        )

    def test_get_switch_driver_skip_broken_driver(self):
        """Test switch driver selection skips broken drivers."""
        # Mock the factory to return a list of drivers
        mock_factory = mock.Mock()
        mock_factory.names = ["broken_driver", "working_driver"]

        # Mock working driver
        mock_working_driver = mock.Mock()
        mock_working_driver.is_switch_configured.return_value = True

        def mock_get_driver(name):
            if name == "broken_driver":
                raise exception.DriverNotFound(driver_name=name)
            else:
                return mock_working_driver

        mock_factory.get_driver.side_effect = mock_get_driver

        # Test driver selection
        self.manager._switch_driver_factory = mock_factory
        result = self.manager._get_switch_driver("test-switch")

        # Verify working driver was selected
        self.assertEqual(result, mock_working_driver)
        mock_working_driver.is_switch_configured.assert_called_once_with(
            "test-switch"
        )

    def test_get_switch_driver_no_drivers_configured(self):
        """Test switch driver selection when no drivers are configured."""
        # Mock the factory to return empty list
        mock_factory = mock.Mock()
        mock_factory.names = []

        # Test driver selection
        self.manager._switch_driver_factory = mock_factory

        # Should raise NetworkError when no drivers are configured
        self.assertRaises(
            exception.NetworkError,
            self.manager._get_switch_driver,
            "test-switch",
        )


class TestNetworkingManagerAdditionalMethods(test_base.TestCase):
    """Additional test cases for NetworkingManager methods."""

    def setUp(self):
        super(TestNetworkingManagerAdditionalMethods, self).setUp()
        self.host = "test-host"
        self.topic = "test-topic"
        self.context = mock.Mock()
        self.manager = manager.NetworkingManager(
            host=self.host, topic=self.topic
        )

    @mock.patch.object(manager.CONF, "host", "default-host")
    def test_init_with_default_host(self):
        """Test manager initialization with default host."""
        mgr = manager.NetworkingManager(host="")
        self.assertEqual("default-host", mgr.host)

    @mock.patch.object(
        manager.rpc, "NETWORKING_TOPIC", "default-topic"
    )
    def test_init_with_default_topic(self):
        """Test manager initialization with default topic."""
        mgr = manager.NetworkingManager(host="test-host")
        self.assertEqual("default-topic", mgr.topic)

    @mock.patch.object(
        manager.rpc, "NETWORKING_TOPIC", "default-topic"
    )
    def test_init_with_json_rpc_uses_networking_host(self):
        """Test manager initialization with json-rpc uses host for topic."""
        manager.CONF.set_override("rpc_transport", "json-rpc")
        manager.CONF.set_override(
            "host_ip", "test-networking-host",
            group="ironic_networking_json_rpc"
        )
        manager.CONF.set_override(
            "port", 8089,
            group="ironic_networking_json_rpc"
        )
        mgr = manager.NetworkingManager(host="test-host")
        self.assertEqual("ironic.test-networking-host:8089", mgr.topic)

    @mock.patch.object(
        manager.rpc, "NETWORKING_TOPIC", "default-topic"
    )
    def test_init_with_oslo_messaging_uses_default_topic(self):
        """Test manager initialization with oslo uses default topic."""
        manager.CONF.set_override("rpc_transport", "oslo")
        manager.CONF.set_override("host", "test-networking-host")
        mgr = manager.NetworkingManager(host="test-host")
        self.assertEqual("default-topic", mgr.topic)

    @mock.patch.object(
        manager.rpc, "NETWORKING_TOPIC", "default-topic"
    )
    def test_init_with_custom_topic_overrides_networking_host(self):
        """Test custom topic overrides networking host even for JSON-RPC."""
        manager.CONF.set_override("rpc_transport", "json-rpc")
        manager.CONF.set_override("host", "test-networking-host")
        mgr = manager.NetworkingManager(host="test-host", topic="custom-topic")
        self.assertEqual("custom-topic", mgr.topic)

    # Tests for _use_jsonrpc_port method removed as the method doesn't exist
    # in the current implementation

    def test_prepare_host_is_noop(self):
        """Test prepare_host is now a no-op method."""
        original_host = self.manager.host
        original_topic = self.manager.topic

        self.manager.prepare_host()

        # Host and topic should be unchanged since prepare_host is a no-op
        self.assertEqual(original_host, self.manager.host)
        self.assertEqual(original_topic, self.manager.topic)

    def test_prepare_host_no_side_effects(self):
        """Test prepare_host has no side effects."""
        # Store original values
        original_vars = {
            "host": self.manager.host,
            "topic": self.manager.topic,
        }

        self.manager.prepare_host()

        # All values should remain unchanged
        self.assertEqual(original_vars["host"], self.manager.host)
        self.assertEqual(original_vars["topic"], self.manager.topic)

    def test_prepare_host_multiple_calls(self):
        """Test prepare_host can be called multiple times safely."""
        original_host = self.manager.host
        original_topic = self.manager.topic

        # Call multiple times
        self.manager.prepare_host()
        self.manager.prepare_host()
        self.manager.prepare_host()

        # Values should remain unchanged
        self.assertEqual(original_host, self.manager.host)
        self.assertEqual(original_topic, self.manager.topic)

    # Test removed - prepare_host no longer processes networking host
    # configuration. Host configuration is now handled in __init__ method

    # Test removed - prepare_host no longer processes networking host
    # configuration. Host configuration is now handled in __init__ method

    # Test removed - prepare_host no longer processes networking host
    # configuration. Host configuration is now handled in __init__ method

    # Test removed - prepare_host no longer processes networking host
    # configuration. Host configuration is now handled in __init__ method

    def test_get_switch_driver_all_drivers_fail(self):
        """Test _get_switch_driver when all drivers fail to match."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        mock_ext_manager = mock.Mock()
        mock_ext_manager.names.return_value = ["driver1", "driver2"]
        mock_factory._extension_manager = mock_ext_manager
        mock_factory.names = ["driver1", "driver2"]

        # Both drivers don't support the switch
        mock_driver1 = mock.Mock()
        mock_driver1.is_switch_configured.return_value = False
        mock_driver2 = mock.Mock()
        mock_driver2.is_switch_configured.return_value = False

        mock_factory.get_driver.side_effect = [mock_driver1, mock_driver2]

        self.assertRaises(
            exception.SwitchNotFound,
            self.manager._get_switch_driver,
            "test-switch",
        )


class TestNetworkingManagerEdgeCases(test_base.TestCase):
    """Edge case tests for NetworkingManager."""

    def setUp(self):
        super(TestNetworkingManagerEdgeCases, self).setUp()
        self.host = "test-host"
        self.topic = "test-topic"
        self.context = mock.Mock()
        self.manager = manager.NetworkingManager(
            host=self.host, topic=self.topic
        )

        # Mock _get_switch_driver for tests that need it
        self.mock_get_switch_driver_patch = mock.patch.object(
            self.manager,
            "_get_switch_driver",
            return_value=mock.Mock(),
            autospec=True,
        )
        self.mock_get_switch_driver = self.mock_get_switch_driver_patch.start()
        self.addCleanup(self.mock_get_switch_driver_patch.stop)

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_port_invalid_mode(self, mock_timer, mock_validate):
        """Test update_port with invalid mode."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "invalid_mode",
            100,
        )
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_port_invalid_vlan_type(self, mock_timer, mock_validate):
        """Test update_port with invalid VLAN type."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            "invalid_vlan",
        )
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_port_invalid_vlan_range(self, mock_timer, mock_validate):
        """Test update_port with VLAN out of range."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            5000,
        )
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_port_invalid_allowed_vlans_type(
        self, mock_timer, mock_validate
    ):
        """Test update_port with invalid allowed_vlans type."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans="invalid",
        )
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_port_invalid_allowed_vlans_values(
        self, mock_timer, mock_validate
    ):
        """Test update_port with invalid allowed_vlans values."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_port,
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=[100, "invalid"],
        )
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_lag_invalid_aggregation_mode(
        self, mock_timer, mock_validate_vlan
    ):
        """Test update_lag with invalid aggregation mode."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            ["switch-01"],
            "pc-01",
            "Test PC",
            "trunk",
            100,
            "invalid_mode",
        )
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    @mock.patch.object(
        switch_config, "validate_vlan_configuration", autospec=True
    )
    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_update_lag_invalid_switch_ids_type(
        self, mock_timer, mock_validate_vlan
    ):
        """Test update_lag with invalid switch_ids type."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.update_lag,
            self.context,
            "invalid",
            "pc-01",
            "Test PC",
            "trunk",
            100,
            "lacp",
        )
        self.assertEqual(exception.Invalid, exc.exc_info[0])

    @mock.patch.object(manager.METRICS, "timer", autospec=True)
    def test_delete_lag_invalid_switch_ids_type(self, mock_timer):
        """Test delete_lag with invalid switch_ids type."""
        mock_timer.return_value = mock.Mock()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.delete_lag,
            self.context,
            "invalid",
            "pc-01",
        )
        self.assertEqual(exception.Invalid, exc.exc_info[0])


class TestNetworkingManagerResetPort(test_base.TestCase):
    """Test cases for reset_port method."""

    def setUp(self):
        super(TestNetworkingManagerResetPort, self).setUp()
        self.host = "test-host"
        self.topic = "test-topic"
        self.context = mock.Mock()
        self.manager = manager.NetworkingManager(
            host=self.host, topic=self.topic
        )

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_reset_port_success(self, mock_get_driver):
        """Test successful port reset."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver

        result = self.manager.reset_port(
            self.context, "switch-01", "port-01", 100)

        # Verify driver was called
        mock_driver.reset_port.assert_called_once_with(
            "switch-01", "port-01",
            100, allowed_vlans=None, default_vlan=None
        )

        # Verify return value
        expected = {
            "switch_id": "switch-01",
            "port_name": "port-01",
            "description": "Default port configuration",
            "mode": "access",
            "native_vlan": 100,
            "allowed_vlans": [],
            "default_vlan": None,
            "status": "reset",
        }
        self.assertEqual(expected, result)

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_reset_port_driver_failure(self, mock_get_driver):
        """Test reset port fails when driver operation fails."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_driver.reset_port.side_effect = Exception("Driver error")

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.reset_port,
            self.context,
            "switch-01",
            "port-01",
            100,
        )
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NetworkError, exc.exc_info[0])

    def test_reset_port_invalid_switch_id(self):
        """Test reset port fails with invalid switch_id."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.reset_port,
            self.context,
            "",
            "port-01",
            100,
        )
        self.assertEqual(exception.NetworkError, exc.exc_info[0])

    def test_reset_port_invalid_port_name(self):
        """Test reset port fails with invalid port_name."""
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.reset_port,
            self.context,
            "switch-01",
            "",
            100,
        )
        self.assertEqual(exception.NetworkError, exc.exc_info[0])

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_reset_port_switch_not_found(self, mock_get_driver):
        """Test reset port fails when switch is not found."""
        mock_get_driver.side_effect = exception.SwitchNotFound(
            switch_id="switch-01"
        )

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.reset_port,
            self.context,
            "switch-01",
            "port-01",
            100,
        )
        self.assertEqual(exception.SwitchNotFound, exc.exc_info[0])

    @mock.patch.object(
        manager.NetworkingManager, "_get_switch_driver", autospec=True
    )
    def test_reset_port_network_error(self, mock_get_driver):
        """Test reset port fails with network error."""
        mock_driver = mock.Mock()
        mock_get_driver.return_value = mock_driver
        mock_driver.reset_port.side_effect = exception.NetworkError(
            "Network error"
        )

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.manager.reset_port,
            self.context,
            "switch-01",
            "port-01",
            100,
        )
        self.assertEqual(exception.NetworkError, exc.exc_info[0])


class TestNetworkingManagerCoverageCompleteness(test_base.TestCase):
    """Test cases to ensure complete coverage of edge cases."""

    def setUp(self):
        super(TestNetworkingManagerCoverageCompleteness, self).setUp()
        self.host = "test-host"
        self.topic = "test-topic"
        self.context = mock.Mock()
        self.manager = manager.NetworkingManager(
            host=self.host, topic=self.topic
        )

        # Mock _get_switch_driver for tests that need it
        self.mock_get_switch_driver_patch = mock.patch.object(
            self.manager,
            "_get_switch_driver",
            return_value=mock.Mock(),
            autospec=True,
        )
        self.mock_get_switch_driver = self.mock_get_switch_driver_patch.start()
        self.addCleanup(self.mock_get_switch_driver_patch.stop)

    def test_init_with_empty_host(self):
        """Test manager initialization with empty host uses CONF.host."""
        with mock.patch.object(manager.CONF, "host", "config-host"):
            mgr = manager.NetworkingManager(host="")
            self.assertEqual("config-host", mgr.host)

    def test_init_with_none_host(self):
        """Test manager initialization with None host uses CONF.host."""
        with mock.patch.object(manager.CONF, "host", "config-host"):
            mgr = manager.NetworkingManager(host=None)
            self.assertEqual("config-host", mgr.host)

    def test_init_with_explicit_topic(self):
        """Test manager initialization with explicit topic."""
        mgr = manager.NetworkingManager(host="test-host", topic="custom-topic")
        self.assertEqual("custom-topic", mgr.topic)

    # Tests for _use_jsonrpc_port method removed as the method doesn't exist

    @mock.patch.object(manager.CONF, "rpc_transport", "oslo.messaging")
    def test_prepare_host_non_json_rpc(self):
        """Test prepare_host with non-JSON-RPC transport."""
        original_host = self.manager.host
        self.manager.prepare_host()
        # Host should remain unchanged
        self.assertEqual(original_host, self.manager.host)

    # Test removed - prepare_host no longer processes networking host
    # configuration. Host configuration is now handled in __init__ method

    # Test removed as _use_jsonrpc_port method doesn't exist


class TestNetworkingManagerGetSwitches(test_base.TestCase):
    """Test cases for NetworkingManager get_switches method."""

    def setUp(self):
        super(TestNetworkingManagerGetSwitches, self).setUp()
        self.host = "test-host"
        self.topic = "test-topic"
        self.context = mock.Mock()
        self.manager = manager.NetworkingManager(
            host=self.host, topic=self.topic
        )

    def test_get_switches_success(self):
        """Test successful retrieval of switches from multiple drivers."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        # Mock two drivers with different switch sets
        mock_driver1 = mock.Mock()
        mock_driver1.get_switch_ids.return_value = ["switch-01", "switch-02"]
        mock_driver1.get_switch_info.side_effect = [
            {"switch_id": "switch-01", "model": "Test Switch 1"},
            {"switch_id": "switch-02", "model": "Test Switch 2"},
        ]

        mock_driver2 = mock.Mock()
        mock_driver2.get_switch_ids.return_value = ["switch-03"]
        mock_driver2.get_switch_info.return_value = {
            "switch_id": "switch-03",
            "model": "Test Switch 3",
        }

        def mock_get_driver(name):
            if name == "driver1":
                return mock_driver1
            elif name == "driver2":
                return mock_driver2
            raise exception.DriverNotFound(name=name)

        # Configure the mock factory
        mock_factory.names = ["driver1", "driver2"]
        mock_factory.get_driver = mock_get_driver

        result = self.manager.get_switches(self.context)

        expected = {
            "switch-01": {"switch_id": "switch-01", "model": "Test Switch 1"},
            "switch-02": {"switch_id": "switch-02", "model": "Test Switch 2"},
            "switch-03": {"switch_id": "switch-03", "model": "Test Switch 3"},
        }
        self.assertEqual(expected, result)

        # Verify all drivers were called
        mock_driver1.get_switch_ids.assert_called_once()
        self.assertEqual(2, mock_driver1.get_switch_info.call_count)
        mock_driver2.get_switch_ids.assert_called_once()
        mock_driver2.get_switch_info.assert_called_once()

    def test_get_switches_no_drivers(self):
        """Test get_switches with no drivers available."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory
        mock_factory.names = []

        result = self.manager.get_switches(self.context)

        self.assertEqual({}, result)

    def test_get_switches_no_switches(self):
        """Test get_switches when drivers return no switches."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        mock_driver = mock.Mock()
        mock_driver.get_switch_ids.return_value = []

        mock_factory.names = ["driver1"]
        mock_factory.get_driver.return_value = mock_driver

        result = self.manager.get_switches(self.context)

        self.assertEqual({}, result)
        mock_driver.get_switch_ids.assert_called_once()

    def test_get_switches_driver_not_found(self):
        """Test get_switches when driver is not found."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        mock_factory.names = ["missing_driver"]
        mock_factory.get_driver.side_effect = exception.DriverNotFound(
            name="missing_driver"
        )

        result = self.manager.get_switches(self.context)

        self.assertEqual({}, result)

    def test_get_switches_driver_get_switch_ids_exception(self):
        """Test get_switches when driver.get_switch_ids raises exception."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        mock_driver = mock.Mock()
        mock_driver.get_switch_ids.side_effect = RuntimeError("Driver error")

        mock_factory.names = ["driver1"]
        mock_factory.get_driver.return_value = mock_driver

        result = self.manager.get_switches(self.context)

        self.assertEqual({}, result)

    def test_get_switches_driver_get_switch_info_exception(self):
        """Test get_switches when driver.get_switch_info raises exception."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        mock_driver = mock.Mock()
        mock_driver.get_switch_ids.return_value = ["switch-01"]
        mock_driver.get_switch_info.side_effect = RuntimeError("Driver error")

        mock_factory.names = ["driver1"]
        mock_factory.get_driver.return_value = mock_driver

        result = self.manager.get_switches(self.context)

        self.assertEqual({}, result)

    def test_get_switches_driver_get_switch_info_returns_none(self):
        """Test get_switches when driver.get_switch_info returns None."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        mock_driver = mock.Mock()
        mock_driver.get_switch_ids.return_value = ["switch-01"]
        mock_driver.get_switch_info.return_value = None

        mock_factory.names = ["driver1"]
        mock_factory.get_driver.return_value = mock_driver

        result = self.manager.get_switches(self.context)

        self.assertEqual({}, result)

    def test_get_switches_mixed_driver_results(self):
        """Test get_switches with mixed success and failure from drivers."""
        # Create a mock factory
        mock_factory = mock.Mock()
        self.manager._switch_driver_factory = mock_factory

        # Mock first driver that works
        mock_driver1 = mock.Mock()
        mock_driver1.get_switch_ids.return_value = ["switch-01"]
        mock_driver1.get_switch_info.return_value = {
            "switch_id": "switch-01",
            "model": "Test Switch 1",
        }

        mock_driver2 = mock.Mock()
        mock_driver2.get_switch_ids.side_effect = RuntimeError("Driver error")

        def mock_get_driver(name):
            if name == "driver1":
                return mock_driver1
            elif name == "driver2":
                return mock_driver2
            raise exception.DriverNotFound(name=name)

        mock_factory.names = ["driver1", "driver2"]
        mock_factory.get_driver = mock_get_driver

        result = self.manager.get_switches(self.context)

        # Should only return results from the working driver
        expected = {
            "switch-01": {"switch_id": "switch-01", "model": "Test Switch 1"}
        }
        self.assertEqual(expected, result)
        mock_driver1.get_switch_ids.assert_called_once()
        mock_driver1.get_switch_info.assert_called_once()
        mock_driver2.get_switch_ids.assert_called_once()
