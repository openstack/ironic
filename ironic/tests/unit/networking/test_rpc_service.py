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

from unittest import mock

from oslo_config import cfg

from ironic.common.json_rpc import server as json_rpc_server
from ironic.common import rpc_service
from ironic.networking import manager as networking_manager
from ironic.tests import base as tests_base


CONF = cfg.CONF


class TestNetworkingRPCService(tests_base.TestCase):

    @mock.patch.object(json_rpc_server, "WSGIService", autospec=True)
    @mock.patch.object(
        rpc_service.objects_base, "IronicObjectSerializer", autospec=True
    )
    @mock.patch.object(rpc_service.context, "get_admin_context", autospec=True)
    def test_json_rpc_uses_networking_group(self, mock_ctx, mock_ser, mock_ws):
        CONF.set_override("rpc_transport", "json-rpc")
        # Ensure ironic networking group is registered and distinguishable
        CONF.set_override("port", 9999, group="ironic_networking_json_rpc")
        CONF.set_override("port", 8089, group="json_rpc")

        networking_manager.NetworkingManager(host="hostA")
        svc = rpc_service.BaseRPCService(
            "hostA", "ironic.networking.manager", "NetworkingManager"
        )

        # Trigger start path to build server
        with mock.patch.object(svc.manager, "prepare_host", autospec=True):
            with mock.patch.object(svc.manager, "init_host", autospec=True):
                svc._real_start()

        self.assertTrue(mock_ws.called)
        # Ensure conf_group was propagated to WSGIService
        _, kwargs = mock_ws.call_args
        self.assertEqual("ironic_networking_json_rpc",
                         kwargs.get("conf_group"))
