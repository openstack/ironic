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

from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import noop
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import inspect as redfish_inspect
from ironic.drivers.modules.redfish import management as redfish_mgmt
from ironic.drivers.modules.redfish import power as redfish_power
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class RedfishHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'],
                    enabled_firmware_interfaces=['redfish'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='redfish')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.inspect,
                                  redfish_inspect.RedfishInspect)
            self.assertIsInstance(task.driver.management,
                                  redfish_mgmt.RedfishManagement)
            self.assertIsInstance(task.driver.power,
                                  redfish_power.RedfishPower)
            self.assertIsInstance(task.driver.boot,
                                  redfish_boot.RedfishVirtualMediaBoot)
            self.assertIsInstance(task.driver.deploy, agent.AgentDeploy)
            self.assertIsInstance(task.driver.console, noop.NoConsole)
            self.assertIsInstance(task.driver.raid, noop.NoRAID)
