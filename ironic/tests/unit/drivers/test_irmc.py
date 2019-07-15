# Copyright 2015 FUJITSU LIMITED
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
Test class for iRMC Deploy Driver
"""

from ironic.conductor import task_manager
from ironic.drivers import irmc
from ironic.drivers.modules import agent
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import ipxe
from ironic.drivers.modules.irmc import bios as irmc_bios
from ironic.drivers.modules.irmc import raid
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class IRMCHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        irmc.boot.check_share_fs_mounted_patcher.start()
        self.addCleanup(irmc.boot.check_share_fs_mounted_patcher.stop)
        super(IRMCHardwareTestCase, self).setUp()
        self.config_temp_dir('http_root', group='deploy')
        self.config(enabled_hardware_types=['irmc'],
                    enabled_boot_interfaces=['irmc-virtual-media', 'ipxe'],
                    enabled_console_interfaces=['ipmitool-socat'],
                    enabled_deploy_interfaces=['iscsi', 'direct'],
                    enabled_inspect_interfaces=['irmc'],
                    enabled_management_interfaces=['irmc'],
                    enabled_power_interfaces=['irmc', 'ipmitool'],
                    enabled_raid_interfaces=['no-raid', 'agent', 'irmc'],
                    enabled_rescue_interfaces=['no-rescue', 'agent'],
                    enabled_bios_interfaces=['irmc', 'no-bios', 'fake'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='irmc')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  irmc.boot.IRMCVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ipmitool.IPMISocatConsole)
            self.assertIsInstance(task.driver.deploy,
                                  iscsi_deploy.ISCSIDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  irmc.inspect.IRMCInspect)
            self.assertIsInstance(task.driver.management,
                                  irmc.management.IRMCManagement)
            self.assertIsInstance(task.driver.power,
                                  irmc.power.IRMCPower)
            self.assertIsInstance(task.driver.raid,
                                  noop.NoRAID)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)
            self.assertIsInstance(task.driver.bios,
                                  irmc_bios.IRMCBIOS)

    def test_override_with_inspector(self):
        self.config(enabled_inspect_interfaces=['inspector', 'irmc'])
        node = obj_utils.create_test_node(
            self.context, driver='irmc',
            deploy_interface='direct',
            inspect_interface='inspector',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  irmc.boot.IRMCVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ipmitool.IPMISocatConsole)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  inspector.Inspector)
            self.assertIsInstance(task.driver.management,
                                  irmc.management.IRMCManagement)
            self.assertIsInstance(task.driver.power,
                                  irmc.power.IRMCPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)

    def test_override_with_agent_rescue(self):
        node = obj_utils.create_test_node(
            self.context, driver='irmc',
            deploy_interface='direct',
            rescue_interface='agent',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  irmc.boot.IRMCVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ipmitool.IPMISocatConsole)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  irmc.inspect.IRMCInspect)
            self.assertIsInstance(task.driver.management,
                                  irmc.management.IRMCManagement)
            self.assertIsInstance(task.driver.power,
                                  irmc.power.IRMCPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)
            self.assertIsInstance(task.driver.rescue,
                                  agent.AgentRescue)

    def test_override_with_ipmitool_power(self):
        node = obj_utils.create_test_node(
            self.context, driver='irmc', power_interface='ipmitool')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  irmc.boot.IRMCVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ipmitool.IPMISocatConsole)
            self.assertIsInstance(task.driver.deploy,
                                  iscsi_deploy.ISCSIDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  irmc.inspect.IRMCInspect)
            self.assertIsInstance(task.driver.management,
                                  irmc.management.IRMCManagement)
            self.assertIsInstance(task.driver.power,
                                  ipmitool.IPMIPower)
            self.assertIsInstance(task.driver.raid,
                                  noop.NoRAID)
            self.assertIsInstance(task.driver.rescue,
                                  noop.NoRescue)

    def test_override_with_raid_configuration(self):
        node = obj_utils.create_test_node(
            self.context, driver='irmc',
            deploy_interface='direct',
            rescue_interface='agent',
            raid_interface='irmc')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  irmc.boot.IRMCVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ipmitool.IPMISocatConsole)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  irmc.inspect.IRMCInspect)
            self.assertIsInstance(task.driver.management,
                                  irmc.management.IRMCManagement)
            self.assertIsInstance(task.driver.power,
                                  irmc.power.IRMCPower)
            self.assertIsInstance(task.driver.raid,
                                  raid.IRMCRAID)
            self.assertIsInstance(task.driver.rescue,
                                  agent.AgentRescue)

    def test_override_with_bios_configuration(self):
        node = obj_utils.create_test_node(
            self.context, driver='irmc',
            deploy_interface='direct',
            rescue_interface='agent',
            bios_interface='no-bios')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  irmc.boot.IRMCVirtualMediaBoot)
            self.assertIsInstance(task.driver.console,
                                  ipmitool.IPMISocatConsole)
            self.assertIsInstance(task.driver.deploy,
                                  agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  irmc.inspect.IRMCInspect)
            self.assertIsInstance(task.driver.management,
                                  irmc.management.IRMCManagement)
            self.assertIsInstance(task.driver.power,
                                  irmc.power.IRMCPower)
            self.assertIsInstance(task.driver.bios,
                                  noop.NoBIOS)
            self.assertIsInstance(task.driver.rescue,
                                  agent.AgentRescue)

    def test_override_with_boot_configuration(self):
        node = obj_utils.create_test_node(
            self.context, driver='irmc',
            boot_interface='ipxe')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot, ipxe.iPXEBoot)
