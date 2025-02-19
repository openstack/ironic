#
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

import datetime
from unittest import mock

from oslo_config import cfg
from oslo_utils import timeutils

from ironic.drivers.modules import fake
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class TestGraphicalConsole(db_base.DbTestCase):

    def setUp(self):
        super(TestGraphicalConsole, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware')
        self.task = mock.Mock(node=self.node)
        self.console = fake.FakeGraphicalConsole()

    def test_start_console(self):
        self.assertFalse(self.node.console_enabled)

        self.console.start_console(self.task)
        dii = self.node.driver_internal_info

        # assert start_console has set internal info
        self.assertEqual('192.0.2.1', dii['vnc_host'])
        self.assertEqual(5900, dii['vnc_port'])
        self.assertIn('novnc_secret_token', dii)
        self.assertIn('novnc_secret_token_created', dii)
        self.assertTrue(self.node.console_enabled)

    def test_stop_console(self):
        self.console.start_console(self.task)
        dii = self.node.driver_internal_info
        self.assertIn('vnc_host', dii)
        self.assertIn('vnc_port', dii)
        self.assertIn('novnc_secret_token', dii)
        self.assertIn('novnc_secret_token_created', dii)
        self.assertTrue(self.node.console_enabled)

        # assert stop_console has cleared internal info
        self.console.stop_console(self.task)
        self.assertNotIn('vnc_host', dii)
        self.assertNotIn('vnc_port', dii)
        self.assertNotIn('novnc_secret_token', dii)
        self.assertNotIn('novnc_secret_token_created', dii)
        self.assertFalse(self.node.console_enabled)

    def test__expire_console_sessions(self):
        self.console.start_console(self.task)
        dii = self.node.driver_internal_info

        # assert active session
        self.assertFalse(self.console._expire_console_sessions(self.task))
        self.assertTrue(self.node.console_enabled)

        timeout = CONF.vnc.token_timeout + 10
        time_delta = datetime.timedelta(seconds=timeout)
        created_time_in_past = timeutils.utcnow() - time_delta
        self.node.set_driver_internal_info('novnc_secret_token_created',
                                           created_time_in_past.isoformat())

        # assert expired, console is closed
        self.assertTrue(self.console._expire_console_sessions(self.task))
        self.assertNotIn('novnc_secret_token', dii)
        self.assertFalse(self.node.console_enabled)
