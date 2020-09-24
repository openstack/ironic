# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
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

from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import fake
from ironic.drivers.modules import noop
from ironic.drivers.modules import noop_mgmt
from ironic.drivers.modules import pxe
from ironic.drivers.modules import snmp
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class SNMPHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SNMPHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['snmp'],
                    enabled_management_interfaces=['noop'],
                    enabled_power_interfaces=['snmp'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='snmp')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.power, snmp.SNMPPower)
            self.assertIsInstance(task.driver.boot, pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy, agent.AgentDeploy)
            self.assertIsInstance(task.driver.management,
                                  noop_mgmt.NoopManagement)
            self.assertIsInstance(task.driver.console, noop.NoConsole)
            self.assertIsInstance(task.driver.raid, noop.NoRAID)

    @mock.patch.object(fake.LOG, 'warning', autospec=True)
    def test_fake_management(self, mock_warn):
        self.config(enabled_management_interfaces=['noop', 'fake'])
        node = obj_utils.create_test_node(self.context, driver='snmp',
                                          management_interface='fake')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.management,
                                  fake.FakeManagement)
            task.driver.management.validate(task)
            self.assertTrue(mock_warn.called)
