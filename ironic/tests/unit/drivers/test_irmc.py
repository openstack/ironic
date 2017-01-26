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

import mock
import testtools

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers import irmc
from ironic.drivers.modules import agent
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class IRMCVirtualMediaIscsiTestCase(testtools.TestCase):

    def setUp(self):
        irmc.boot.check_share_fs_mounted_patcher.start()
        self.addCleanup(irmc.boot.check_share_fs_mounted_patcher.stop)
        super(IRMCVirtualMediaIscsiTestCase, self).setUp()

    @mock.patch.object(irmc.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test___init___share_fs_mounted_ok(self,
                                          mock_try_import):
        mock_try_import.return_value = True

        driver = irmc.IRMCVirtualMediaIscsiDriver()

        self.assertIsInstance(driver.power, irmc.power.IRMCPower)
        self.assertIsInstance(driver.boot,
                              irmc.boot.IRMCVirtualMediaBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.console,
                              irmc.ipmitool.IPMIShellinaboxConsole)
        self.assertIsInstance(driver.management,
                              irmc.management.IRMCManagement)
        self.assertIsInstance(driver.inspect, irmc.inspect.IRMCInspect)

    @mock.patch.object(irmc.importutils, 'try_import')
    def test___init___try_import_exception(self, mock_try_import):
        mock_try_import.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          irmc.IRMCVirtualMediaIscsiDriver)

    @mock.patch.object(irmc.boot.IRMCVirtualMediaBoot, '__init__',
                       spec_set=True, autospec=True)
    def test___init___share_fs_not_mounted_exception(self, __init___mock):
        __init___mock.side_effect = exception.IRMCSharedFileSystemNotMounted(
            share='/share')

        self.assertRaises(exception.IRMCSharedFileSystemNotMounted,
                          irmc.IRMCVirtualMediaIscsiDriver)


class IRMCVirtualMediaAgentTestCase(testtools.TestCase):

    def setUp(self):
        irmc.boot.check_share_fs_mounted_patcher.start()
        self.addCleanup(irmc.boot.check_share_fs_mounted_patcher.stop)
        super(IRMCVirtualMediaAgentTestCase, self).setUp()

    @mock.patch.object(irmc.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test___init___share_fs_mounted_ok(self,
                                          mock_try_import):
        mock_try_import.return_value = True

        driver = irmc.IRMCVirtualMediaAgentDriver()

        self.assertIsInstance(driver.power, irmc.power.IRMCPower)
        self.assertIsInstance(driver.boot,
                              irmc.boot.IRMCVirtualMediaBoot)
        self.assertIsInstance(driver.deploy, agent.AgentDeploy)
        self.assertIsInstance(driver.console,
                              irmc.ipmitool.IPMIShellinaboxConsole)
        self.assertIsInstance(driver.management,
                              irmc.management.IRMCManagement)
        self.assertIsInstance(driver.inspect, irmc.inspect.IRMCInspect)

    @mock.patch.object(irmc.importutils, 'try_import')
    def test___init___try_import_exception(self, mock_try_import):
        mock_try_import.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          irmc.IRMCVirtualMediaAgentDriver)

    @mock.patch.object(irmc.boot.IRMCVirtualMediaBoot, '__init__',
                       spec_set=True, autospec=True)
    def test___init___share_fs_not_mounted_exception(self, __init___mock):
        __init___mock.side_effect = exception.IRMCSharedFileSystemNotMounted(
            share='/share')

        self.assertRaises(exception.IRMCSharedFileSystemNotMounted,
                          irmc.IRMCVirtualMediaAgentDriver)


class IRMCHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        irmc.boot.check_share_fs_mounted_patcher.start()
        self.addCleanup(irmc.boot.check_share_fs_mounted_patcher.stop)
        super(IRMCHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['irmc'],
                    enabled_boot_interfaces=['irmc-virtual-media'],
                    enabled_console_interfaces=['ipmitool-socat'],
                    enabled_deploy_interfaces=['iscsi', 'direct'],
                    enabled_inspect_interfaces=['irmc'],
                    enabled_management_interfaces=['irmc'],
                    enabled_power_interfaces=['irmc'],
                    enabled_raid_interfaces=['no-raid', 'agent'])

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
