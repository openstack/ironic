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

import random
import string
from unittest import mock

from oslo_utils import uuidutils

from ironic.common import states
from ironic.conf import CONF
from ironic.pxe_filter import dnsmasq
from ironic.pxe_filter import service as pxe_filter_service
from ironic.tests.unit.db import base as test_base
from ironic.tests.unit.db import utils as db_utils


def generate_mac():
    return ':'.join(''.join(random.choice(string.hexdigits) for _ in range(2))
                    for _ in range(6))


@mock.patch.object(dnsmasq, 'sync', autospec=True)
class TestSync(test_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.service = pxe_filter_service.PXEFilterManager('host')

    def test_no_nodes(self, mock_sync):
        self.service._sync(self.dbapi)
        mock_sync.assert_called_once_with([], [], False)

    def test_no_nodes_with_discovery(self, mock_sync):
        CONF.set_override('enabled', True, group='auto_discovery')
        self.service._sync(self.dbapi)
        mock_sync.assert_called_once_with([], [], True)

    def test_sync(self, mock_sync):
        on_inspection = [
            db_utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      provision_state=state,
                                      inspect_interface='agent')
            for state in (states.INSPECTWAIT, states.INSPECTING)
        ]
        not_on_inspection = [
            db_utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      provision_state=state,
                                      inspect_interface='agent')
            for state in (states.ACTIVE, states.AVAILABLE, states.INSPECTFAIL)
        ]
        ignored = db_utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                            provision_state=states.INSPECTING,
                                            inspect_interface='no-inspect')
        ignored_port = db_utils.create_test_port(
            uuid=uuidutils.generate_uuid(),
            node_id=ignored.id,
            address=generate_mac())

        allow_macs, deny_macs = set(), {ignored_port.address}
        for count, node in enumerate(on_inspection):
            for _i in range(count):
                port = db_utils.create_test_port(
                    uuid=uuidutils.generate_uuid(),
                    node_id=node.id,
                    address=generate_mac())
                allow_macs.add(port.address)
        for count, node in enumerate(not_on_inspection):
            for _i in range(count):
                port = db_utils.create_test_port(
                    uuid=uuidutils.generate_uuid(),
                    node_id=node.id,
                    address=generate_mac())
                deny_macs.add(port.address)

        self.service._sync(self.dbapi)
        mock_sync.assert_called_once_with(mock.ANY, mock.ANY, True)
        self.assertEqual(allow_macs, set(mock_sync.call_args.args[0]))
        self.assertEqual(deny_macs, set(mock_sync.call_args.args[1]))

    def test_nothing_on_inspection(self, mock_sync):
        not_on_inspection = [
            db_utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                      provision_state=state,
                                      inspect_interface='agent')
            for state in (states.ACTIVE, states.AVAILABLE, states.INSPECTFAIL)
        ]

        deny_macs = set()
        for count, node in enumerate(not_on_inspection):
            for _i in range(count):
                port = db_utils.create_test_port(
                    uuid=uuidutils.generate_uuid(),
                    node_id=node.id,
                    address=generate_mac())
                deny_macs.add(port.address)

        self.service._sync(self.dbapi)
        mock_sync.assert_called_once_with([], mock.ANY, False)
        self.assertEqual(deny_macs, set(mock_sync.call_args.args[1]))


class TestManager(test_base.DbTestCase):

    @mock.patch('eventlet.spawn_after', lambda delay, func: func())
    @mock.patch('eventlet.event.Event', autospec=True)
    @mock.patch.object(pxe_filter_service.PXEFilterManager, '_sync',
                       autospec=True)
    def test_init_and_run(self, mock_sync, mock_event):
        mock_wait = mock_event.return_value.wait
        mock_wait.side_effect = [None, None, True]
        mock_sync.side_effect = [None, RuntimeError(), None]

        service = pxe_filter_service.PXEFilterManager('example.com')
        service.init_host(mock.sentinel.context)

        mock_sync.assert_called_with(service, mock.ANY)
        self.assertEqual(3, mock_sync.call_count)
        mock_wait.assert_called_with(timeout=45)
