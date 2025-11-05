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

"""Unit tests for networking RPC API."""

from oslo_config import cfg
import unittest.mock as mock

from ironic.common import exception
from ironic.common import rpc
from ironic.networking import rpcapi
from ironic.tests import base as test_base

CONF = cfg.CONF


class TestNetworkingAPI(test_base.TestCase):
    """Test cases for NetworkingAPI RPC client."""

    def setUp(self):
        super(TestNetworkingAPI, self).setUp()
        self.context = mock.Mock()
        self.api = rpcapi.NetworkingAPI()

    def test_init_default_topic(self):
        """Test NetworkingAPI initialization with default topic."""
        with mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic"):
            api = rpcapi.NetworkingAPI()
            self.assertEqual("test-topic", api.topic)

    def test_init_custom_topic(self):
        """Test NetworkingAPI initialization with custom topic."""
        api = rpcapi.NetworkingAPI(topic="custom-topic")
        self.assertEqual("custom-topic", api.topic)

    def test_get_topic(self):
        """Test get_topic method."""
        with mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic"):
            api = rpcapi.NetworkingAPI()
            self.assertEqual("test-topic", api.get_topic())

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_init_with_none_transport(self):
        """Test initialization with rpc_transport=none."""
        CONF.set_override("rpc_transport", "none")
        api = rpcapi.NetworkingAPI()
        self.assertIsNone(api.client)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_init_with_json_rpc_transport(self):
        """Test initialization with json-rpc transport."""
        CONF.set_override("rpc_transport", "json-rpc")
        api = rpcapi.NetworkingAPI()
        self.assertIsNotNone(api.client)
        # Ensure the client is configured to use networking group
        self.assertEqual("ironic_networking_json_rpc", api.client.conf_group)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_init_with_oslo_messaging_transport(self):
        """Test initialization with oslo.messaging transport."""
        CONF.set_override("rpc_transport", "oslo")
        api = rpcapi.NetworkingAPI()
        self.assertIsNotNone(api.client)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_init_with_json_rpc_uses_networking_host(self):
        """Test initialization with json-rpc uses networking host for topic."""
        CONF.set_override("rpc_transport", "json-rpc")
        CONF.set_override(
            "host_ip", "test-networking-host",
            group="ironic_networking_json_rpc"
        )
        CONF.set_override("port", 8089, group="ironic_networking_json_rpc")
        api = rpcapi.NetworkingAPI()
        self.assertEqual("ironic.test-networking-host:8089", api.topic)
        self.assertIsNotNone(api.client)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_init_with_oslo_messaging_uses_default_topic(self):
        """Test initialization with oslo.messaging uses default topic."""
        CONF.set_override("rpc_transport", "oslo")
        CONF.set_override("host", "test-networking-host")
        api = rpcapi.NetworkingAPI()
        self.assertEqual("test-topic", api.topic)
        self.assertIsNotNone(api.client)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_init_with_custom_topic_overrides_networking_host(self):
        """Test custom topic overrides networking host even for JSON-RPC."""
        CONF.set_override("rpc_transport", "json-rpc")
        CONF.set_override("host", "test-networking-host")
        api = rpcapi.NetworkingAPI(topic="custom-topic")
        self.assertEqual("custom-topic", api.topic)
        self.assertIsNotNone(api.client)

    def test_prepare_call_none_client(self):
        """Test _prepare_call with None client raises exception."""
        self.api.client = None
        exc = self.assertRaises(
            exception.ServiceUnavailable, self.api._prepare_call, topic="test"
        )
        self.assertIn("Cannot use 'none' RPC", str(exc))

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_update_port_success(self, mock_prepare):
        """Test successful update_port call."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "configured"}

        result = self.api.update_port(
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            allowed_vlans=None,
            lag_name=None,
            default_vlan=1
        )

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "update_port",
            switch_id="switch-01",
            port_name="port-01",
            description="Test port",
            mode="access",
            native_vlan=100,
            allowed_vlans=None,
            lag_name=None,
            default_vlan=1
        )
        self.assertEqual({"status": "configured"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_update_port_with_allowed_vlans(self, mock_prepare):
        """Test update_port call with allowed VLANs."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "configured"}

        result = self.api.update_port(
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "trunk",
            100,
            allowed_vlans=[101, 102],
            lag_name="po1",
            default_vlan=1
        )

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "update_port",
            switch_id="switch-01",
            port_name="port-01",
            description="Test port",
            mode="trunk",
            native_vlan=100,
            allowed_vlans=[101, 102],
            lag_name="po1",
            default_vlan=1
        )
        self.assertEqual({"status": "configured"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_update_port_with_custom_topic(self, mock_prepare):
        """Test update_port call with custom topic."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "configured"}

        result = self.api.update_port(
            self.context,
            "switch-01",
            "port-01",
            "Test port",
            "access",
            100,
            default_vlan=1,
            topic="custom-topic",
        )

        mock_prepare.assert_called_once_with(
            self.api, topic="custom-topic", version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "update_port",
            switch_id="switch-01",
            port_name="port-01",
            description="Test port",
            mode="access",
            native_vlan=100,
            allowed_vlans=None,
            lag_name=None,
            default_vlan=1,
        )
        self.assertEqual({"status": "configured"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_reset_port_success(self, mock_prepare):
        """Test successful reset_port call."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "reset"}

        result = self.api.reset_port(
            self.context,
            "switch-01",
            "port-01",
            100,
            default_vlan=1)

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "reset_port",
            switch_id="switch-01",
            port_name="port-01",
            native_vlan=100,
            allowed_vlans=None,
            default_vlan=1,
        )
        self.assertEqual({"status": "reset"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_reset_port_with_allowed_vlans(self, mock_prepare):
        """Test reset_port call with allowed VLANs."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "reset"}

        result = self.api.reset_port(
            self.context,
            "switch-01",
            "port-01",
            100,
            allowed_vlans=[101, 102],
            default_vlan=1
        )

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "reset_port",
            switch_id="switch-01",
            port_name="port-01",
            native_vlan=100,
            allowed_vlans=[101, 102],
            default_vlan=1,
        )
        self.assertEqual({"status": "reset"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_reset_port_with_custom_topic(self, mock_prepare):
        """Test reset_port call with custom topic."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "reset"}

        result = self.api.reset_port(
            self.context,
            "switch-01",
            "port-01",
            100,
            default_vlan=1,
            topic="custom-topic"
        )

        mock_prepare.assert_called_once_with(
            self.api, topic="custom-topic", version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "reset_port",
            switch_id="switch-01",
            port_name="port-01",
            native_vlan=100,
            allowed_vlans=None,
            default_vlan=1,
        )
        self.assertEqual({"status": "reset"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_get_switches_success(self, mock_prepare):
        """Test successful get_switches call."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        expected_switches = {
            "switch-01": {"name": "switch-01", "status": "connected"},
            "switch-02": {"name": "switch-02", "status": "connected"},
        }
        mock_cctxt.call.return_value = expected_switches

        result = self.api.get_switches(self.context)

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(self.context, "get_switches")
        self.assertEqual(expected_switches, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_get_switches_with_custom_topic(self, mock_prepare):
        """Test get_switches call with custom topic."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        expected_switches = {}
        mock_cctxt.call.return_value = expected_switches

        result = self.api.get_switches(self.context, topic="custom-topic")

        mock_prepare.assert_called_once_with(
            self.api, topic="custom-topic", version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(self.context, "get_switches")
        self.assertEqual(expected_switches, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_update_lag_success(self, mock_prepare):
        """Test successful update_lag call."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "configured"}

        result = self.api.update_lag(
            self.context,
            ["switch-01", "switch-02"],
            "lag-01",
            "Test LAG",
            "trunk",
            100,
            "lacp",
            allowed_vlans=[101, 102],
            default_vlan=1,
        )

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "update_lag",
            switch_ids=["switch-01", "switch-02"],
            lag_name="lag-01",
            description="Test LAG",
            mode="trunk",
            native_vlan=100,
            aggregation_mode="lacp",
            allowed_vlans=[101, 102],
            default_vlan=1,
        )
        self.assertEqual({"status": "configured"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_update_lag_without_allowed_vlans(self, mock_prepare):
        """Test update_lag call without allowed VLANs."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "configured"}

        result = self.api.update_lag(
            self.context,
            ["switch-01"],
            "lag-01",
            "Test LAG",
            "access",
            100,
            "static",
            default_vlan=1,
        )

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "update_lag",
            switch_ids=["switch-01"],
            lag_name="lag-01",
            description="Test LAG",
            mode="access",
            native_vlan=100,
            aggregation_mode="static",
            allowed_vlans=None,
            default_vlan=1,
        )
        self.assertEqual({"status": "configured"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_update_lag_with_custom_topic(self, mock_prepare):
        """Test update_lag call with custom topic."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "configured"}

        result = self.api.update_lag(
            self.context,
            ["switch-01"],
            "lag-01",
            "Test LAG",
            "access",
            100,
            "static",
            default_vlan=1,
            topic="custom-topic",
        )

        mock_prepare.assert_called_once_with(
            self.api, topic="custom-topic", version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "update_lag",
            switch_ids=["switch-01"],
            lag_name="lag-01",
            description="Test LAG",
            mode="access",
            native_vlan=100,
            aggregation_mode="static",
            allowed_vlans=None,
            default_vlan=1,
        )
        self.assertEqual({"status": "configured"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_delete_lag_success(self, mock_prepare):
        """Test successful delete_lag call."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "deleted"}

        result = self.api.delete_lag(
            self.context, ["switch-01", "switch-02"], "lag-01"
        )

        mock_prepare.assert_called_once_with(
            self.api, topic=None, version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "delete_lag",
            switch_ids=["switch-01", "switch-02"],
            lag_name="lag-01",
        )
        self.assertEqual({"status": "deleted"}, result)

    @mock.patch.object(rpcapi.NetworkingAPI, "_prepare_call", autospec=True)
    def test_delete_lag_with_custom_topic(self, mock_prepare):
        """Test delete_lag call with custom topic."""
        mock_cctxt = mock.Mock()
        mock_prepare.return_value = mock_cctxt
        mock_cctxt.call.return_value = {"status": "deleted"}

        result = self.api.delete_lag(
            self.context, ["switch-01"], "lag-01", topic="custom-topic"
        )

        mock_prepare.assert_called_once_with(
            self.api, topic="custom-topic", version="1.0"
        )
        mock_cctxt.call.assert_called_once_with(
            self.context,
            "delete_lag",
            switch_ids=["switch-01"],
            lag_name="lag-01",
        )
        self.assertEqual({"status": "deleted"}, result)


class TestNetworkingAPIVersionCap(test_base.TestCase):
    """Test cases for NetworkingAPI version cap handling."""

    def setUp(self):
        super(TestNetworkingAPIVersionCap, self).setUp()
        self.context = mock.Mock()

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_version_cap_from_release_mapping(self):
        """Test version cap is set from release mapping."""
        with mock.patch.object(
            rpcapi.versions,
            "RELEASE_MAPPING",
            {"zed": {"rpc": "1.0"}}):
            CONF.set_override("pin_release_version", "zed")
            api = rpcapi.NetworkingAPI()
            # Version cap should be applied from release mapping
            self.assertIsNotNone(api.client)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_version_cap_fallback_to_current(self):
        """Test version cap falls back to current version."""
        with mock.patch.object(rpcapi.versions, "RELEASE_MAPPING", {}):
            CONF.set_override("pin_release_version", None)
            api = rpcapi.NetworkingAPI()
            # Should use current RPC_API_VERSION
            self.assertIsNotNone(api.client)

    @mock.patch.object(rpc, "NETWORKING_TOPIC", "test-topic")
    def test_version_cap_no_pin_release_version(self):
        """Test version cap when pin_release_version is not set."""
        with mock.patch.object(
            rpcapi.versions,
            "RELEASE_MAPPING",
            {"zed": {"rpc": "1.0"}}
        ):
            CONF.set_override("pin_release_version", None)
            api = rpcapi.NetworkingAPI()
            # Should use current RPC_API_VERSION
            self.assertIsNotNone(api.client)
