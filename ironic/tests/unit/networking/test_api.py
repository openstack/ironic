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
"""Unit tests for ``ironic.networking.api``."""
import unittest
from unittest import mock

from ironic.networking import api


class NetworkingApiTestCase(unittest.TestCase):
    """Test cases for helper functions in ``ironic.networking.api``."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, api, "_NETWORKING_API", None)

    def test_get_networking_api_singleton(self):
        with mock.patch(
            "ironic.networking.api.rpcapi.NetworkingAPI",
            autospec=True,
        ) as mock_cls:
            instance = mock_cls.return_value

            result1 = api.get_networking_api()
            result2 = api.get_networking_api()

            self.assertIs(result1, instance)
            self.assertIs(result2, instance)
            mock_cls.assert_called_once_with()

    def test_update_port_delegates_to_rpc(self):
        api_mock = mock.Mock()
        with mock.patch.object(
            api, "get_networking_api", return_value=api_mock,
            autospec=True
        ):
            context = object()
            result = api.update_port(
                context,
                "switch0",
                "eth0",
                "description",
                "access",
                24,
                allowed_vlans=[10],
                lag_name="pc1",
            )

            api_mock.update_port.assert_called_once_with(
                context,
                "switch0",
                "eth0",
                "description",
                "access",
                24,
                allowed_vlans=[10],
                lag_name="pc1",
                default_vlan=None,
            )
            self.assertIs(result, api_mock.update_port.return_value)

    def test_reset_port_delegates_to_rpc(self):
        api_mock = mock.Mock()
        with mock.patch.object(
            api, "get_networking_api", return_value=api_mock,
            autospec=True
        ):
            context = object()
            result = api.reset_port(
                context, "switch1", "eth1", default_vlan=11
            )

            api_mock.reset_port.assert_called_once_with(
                context, "switch1", "eth1", None, allowed_vlans=None,
                default_vlan=11
            )
            self.assertIs(result, api_mock.reset_port.return_value)

    def test_update_lag_delegates_to_rpc(self):
        api_mock = mock.Mock()
        with mock.patch.object(
            api, "get_networking_api", return_value=api_mock,
            autospec=True
        ):
            context = object()
            result = api.update_lag(
                context,
                ["switch1", "switch2"],
                "pc",
                "desc",
                "trunk",
                100,
                "lacp",
                allowed_vlans=[200],
            )

            api_mock.update_lag.assert_called_once_with(
                context,
                ["switch1", "switch2"],
                "pc",
                "desc",
                "trunk",
                100,
                "lacp",
                allowed_vlans=[200],
                default_vlan=None,
            )
            self.assertIs(
                result, api_mock.update_lag.return_value
            )

    def test_delete_lag_delegates_to_rpc(self):
        api_mock = mock.Mock()
        with mock.patch.object(
            api, "get_networking_api", return_value=api_mock,
            autospec=True
        ):
            context = object()
            result = api.delete_lag(
                context, ["switch1"], "pc"
            )

            api_mock.delete_lag.assert_called_once_with(
                context, ["switch1"], "pc"
            )
            self.assertIs(
                result, api_mock.delete_lag.return_value
            )
