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

import mock
import testtools

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers import ilo
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import boot
from ironic.drivers.modules.ilo import console
from ironic.drivers.modules.ilo import inspect
from ironic.drivers.modules.ilo import management
from ironic.drivers.modules.ilo import power
from ironic.drivers.modules.ilo import vendor
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
                    enabled_console_interfaces=['ilo'],
                    enabled_deploy_interfaces=['iscsi', 'direct'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_management_interfaces=['ilo'],
                    enabled_power_interfaces=['ilo'],
                    enabled_raid_interfaces=['no-raid', 'agent'],
                    enabled_vendor_interfaces=['no-vendor'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo')
        with task_manager.acquire(self.context, node.id) as task:
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
            self.assertIsInstance(task.driver.raid,
                                  noop.NoRAID)
            self.assertIsInstance(task.driver.vendor,
                                  noop.NoVendor)

    def test_override_with_inspector(self):
        self.config(enabled_inspect_interfaces=['inspector', 'ilo'])
        node = obj_utils.create_test_node(
            self.context, driver='ilo',
            deploy_interface='direct',
            inspect_interface='inspector',
            raid_interface='agent')
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
            self.assertIsInstance(task.driver.vendor,
                                  noop.NoVendor)


@mock.patch.object(ilo.importutils, 'try_import', spec_set=True,
                   autospec=True)
class IloVirtualMediaIscsiDriversTestCase(testtools.TestCase):

    def test_ilo_iscsi_driver(self, mock_try_import):
        mock_try_import.return_value = True

        driver = ilo.IloVirtualMediaIscsiDriver()

        self.assertIsInstance(driver.power, power.IloPower)
        self.assertIsInstance(driver.boot, boot.IloVirtualMediaBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.console, console.IloConsoleInterface)
        self.assertIsInstance(driver.management, management.IloManagement)
        self.assertIsInstance(driver.vendor, vendor.VendorPassthru)
        self.assertIsInstance(driver.inspect, inspect.IloInspect)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    def test_ilo_iscsi_driver_exc(self, mock_try_import):
        mock_try_import.return_value = None

        self.assertRaises(exception.DriverLoadError,
                          ilo.IloVirtualMediaIscsiDriver)


@mock.patch.object(ilo.importutils, 'try_import', spec_set=True,
                   autospec=True)
class IloVirtualMediaAgentDriversTestCase(testtools.TestCase):

    def test_ilo_agent_driver(self, mock_try_import):
        mock_try_import.return_value = True

        driver = ilo.IloVirtualMediaAgentDriver()

        self.assertIsInstance(driver.power, power.IloPower)
        self.assertIsInstance(driver.boot, boot.IloVirtualMediaBoot)
        self.assertIsInstance(driver.deploy, agent.AgentDeploy)
        self.assertIsInstance(driver.console, console.IloConsoleInterface)
        self.assertIsInstance(driver.management, management.IloManagement)
        self.assertIsInstance(driver.inspect, inspect.IloInspect)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    def test_ilo_iscsi_driver_exc(self, mock_try_import):
        mock_try_import.return_value = None

        self.assertRaises(exception.DriverLoadError,
                          ilo.IloVirtualMediaAgentDriver)
