# Copyright 2017 Hewlett-Packard Enterprise Company, L.P.
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

"""
Test class for iLO Drivers
"""

from ironic.conductor import task_manager
from ironic.drivers import ilo
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import management
from ironic.drivers.modules.ilo import raid
from ironic.drivers.modules import inspector
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class IloHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['ilo'],
                    enabled_boot_interfaces=['ilo-virtual-media', 'ilo-pxe'],
                    enabled_bios_interfaces=['no-bios', 'ilo'],
                    enabled_console_interfaces=['ilo'],
                    enabled_deploy_interfaces=['iscsi', 'direct'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_management_interfaces=['ilo'],
                    enabled_power_interfaces=['ilo'],
                    enabled_raid_interfaces=['no-raid', 'agent'],
                    enabled_rescue_interfaces=['no-rescue', 'agent'],
                    enabled_vendor_interfaces=['ilo', 'no-vendor'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  ilo.boot.IloVirtualMediaBoot)
            self.assertIsInstance(task.driver.bios,
                                  ilo.bios.IloBIOS)
            self.assertIsInstance(task.driver.console,
                                  ilo.console.IloConsoleInterface)
            self.assertIsInstance(task.driver.deploy,
                                  iscsi_deploy.ISCSIDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  ilo.inspect.IloInspect)
            self.assertIsInstance(task.driver.management,
                                  ilo.management.IloManagement)
            self.assertIsInstance(task.driver.power,
                                  ilo.power.IloPower)
            self.assertIsInstance(task.driver.raid,
                                  noop.NoRAID)
            self.assertIsInstance(task.driver.vendor,
                                  ilo.vendor.VendorPassthru)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)

    def test_override_with_inspector(self):
        self.config(enabled_inspect_interfaces=['inspector', 'ilo'])
        node = obj_utils.create_test_node(
            self.context, driver='ilo',
            deploy_interface='direct',
            inspect_interface='inspector',
            raid_interface='agent',
            vendor_interface='no-vendor')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  ilo.boot.IloVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ilo.console.IloConsoleInterface)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  inspector.Inspector)
            self.assertIsInstance(task.driver.management,
                                  ilo.management.IloManagement)
            self.assertIsInstance(task.driver.power,
                                  ilo.power.IloPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)
            self.assertIsInstance(task.driver.vendor,
                                  noop.NoVendor)

    def test_override_with_pxe(self):
        node = obj_utils.create_test_node(
            self.context, driver='ilo',
            boot_interface='ilo-pxe',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  ilo.boot.IloPXEBoot)
            self.assertIsInstance(task.driver.console,
                                  ilo.console.IloConsoleInterface)
            self.assertIsInstance(task.driver.deploy,
                                  iscsi_deploy.ISCSIDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  ilo.inspect.IloInspect)
            self.assertIsInstance(task.driver.management,
                                  ilo.management.IloManagement)
            self.assertIsInstance(task.driver.power,
                                  ilo.power.IloPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)
            self.assertIsInstance(task.driver.vendor,
                                  ilo.vendor.VendorPassthru)

    def test_override_with_agent_rescue(self):
        self.config(enabled_inspect_interfaces=['inspector', 'ilo'])
        node = obj_utils.create_test_node(
            self.context, driver='ilo',
            deploy_interface='direct',
            rescue_interface='agent',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  ilo.boot.IloVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ilo.console.IloConsoleInterface)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  ilo.inspect.IloInspect)
            self.assertIsInstance(task.driver.management,
                                  ilo.management.IloManagement)
            self.assertIsInstance(task.driver.power,
                                  ilo.power.IloPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)
            self.assertIsInstance(task.driver.rescue,
                                  agent.AgentRescue)
            self.assertIsInstance(task.driver.vendor,
                                  ilo.vendor.VendorPassthru)

    def test_override_with_no_bios(self):
        node = obj_utils.create_test_node(
            self.context, driver='ilo',
            boot_interface='ilo-pxe',
            bios_interface='no-bios',
            deploy_interface='direct',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  ilo.boot.IloPXEBoot)
            self.assertIsInstance(task.driver.bios,
                                  noop.NoBIOS)
            self.assertIsInstance(task.driver.console,
                                  ilo.console.IloConsoleInterface)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)


class Ilo5HardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(Ilo5HardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['ilo5'],
                    enabled_boot_interfaces=['ilo-virtual-media', 'ilo-pxe'],
                    enabled_console_interfaces=['ilo'],
                    enabled_deploy_interfaces=['iscsi', 'direct'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_management_interfaces=['ilo5'],
                    enabled_power_interfaces=['ilo'],
                    enabled_raid_interfaces=['ilo5'],
                    enabled_rescue_interfaces=['no-rescue', 'agent'],
                    enabled_vendor_interfaces=['ilo', 'no-vendor'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='ilo5')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.raid, raid.Ilo5RAID)
            self.assertIsInstance(task.driver.management,
                                  management.Ilo5Management)

    def test_override_with_no_raid(self):
        self.config(enabled_raid_interfaces=['no-raid', 'ilo5'])
        node = obj_utils.create_test_node(self.context, driver='ilo5',
                                          raid_interface='no-raid')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.raid, noop.NoRAID)
            self.assertIsInstance(task.driver.boot,
                                  ilo.boot.IloVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ilo.console.IloConsoleInterface)
            self.assertIsInstance(task.driver.deploy,
                                  iscsi_deploy.ISCSIDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  ilo.inspect.IloInspect)
            self.assertIsInstance(task.driver.management,
                                  ilo.management.IloManagement)
            self.assertIsInstance(task.driver.power,
                                  ilo.power.IloPower)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)
            self.assertIsInstance(task.driver.vendor,
                                  ilo.vendor.VendorPassthru)
