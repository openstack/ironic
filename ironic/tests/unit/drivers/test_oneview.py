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

"""Test class for HPE OneView Drivers."""

import mock
import testtools

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import noop
from ironic.drivers.modules.oneview import deploy
from ironic.drivers.modules.oneview import management
from ironic.drivers.modules.oneview import power
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.drivers import oneview
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class OneViewHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['oneview'],
                    enabled_deploy_interfaces=[
                        'oneview-direct', 'oneview-iscsi'],
                    enabled_inspect_interfaces=['oneview'],
                    enabled_management_interfaces=['oneview'],
                    enabled_power_interfaces=['oneview'],
                    enabled_raid_interfaces=['no-raid', 'agent'],
                    enabled_console_interfaces=['no-console'],
                    enabled_vendor_interfaces=['no-vendor'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='oneview')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy,
                                  oneview.deploy.OneViewIscsiDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  oneview.inspect.OneViewInspect)
            self.assertIsInstance(task.driver.management,
                                  oneview.management.OneViewManagement)
            self.assertIsInstance(task.driver.power,
                                  oneview.power.OneViewPower),
            self.assertIsInstance(task.driver.storage,
                                  noop_storage.NoopStorage),
            self.assertIsInstance(task.driver.console,
                                  noop.NoConsole),
            self.assertIsInstance(task.driver.raid,
                                  noop.NoRAID)
            self.assertIsInstance(task.driver.vendor,
                                  noop.NoVendor)

    def test_default_with_inspector_interface_enabled(self):
        self.config(enabled_inspect_interfaces=['inspector', 'oneview'])
        node = obj_utils.create_test_node(
            self.context, driver='oneview',
            deploy_interface='oneview-direct',
            inspect_interface='oneview',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy,
                                  oneview.deploy.OneViewAgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  oneview.inspect.OneViewInspect)
            self.assertIsInstance(task.driver.management,
                                  oneview.management.OneViewManagement)
            self.assertIsInstance(task.driver.power,
                                  oneview.power.OneViewPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)
            self.assertIsInstance(task.driver.vendor,
                                  noop.NoVendor)

    def test_override_with_direct(self):
        node = obj_utils.create_test_node(
            self.context, driver='oneview',
            deploy_interface='oneview-direct',
            boot_interface='pxe',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy,
                                  oneview.deploy.OneViewAgentDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  oneview.inspect.OneViewInspect)
            self.assertIsInstance(task.driver.management,
                                  oneview.management.OneViewManagement)
            self.assertIsInstance(task.driver.power,
                                  oneview.power.OneViewPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)

    def test_override_with_iscsi(self):
        node = obj_utils.create_test_node(
            self.context, driver='oneview',
            deploy_interface='oneview-iscsi',
            boot_interface='pxe',
            raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.boot,
                                  pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy,
                                  oneview.deploy.OneViewIscsiDeploy)
            self.assertIsInstance(task.driver.inspect,
                                  oneview.inspect.OneViewInspect)
            self.assertIsInstance(task.driver.management,
                                  oneview.management.OneViewManagement)
            self.assertIsInstance(task.driver.power,
                                  oneview.power.OneViewPower)
            self.assertIsInstance(task.driver.raid,
                                  agent.AgentRAID)


@mock.patch.object(oneview.importutils, 'try_import', autospec=True)
class AgentPXEOneViewDriversTestCase(testtools.TestCase):

    def test_oneview_agent_driver(self, mock_try_import):
        mock_try_import.return_value = True
        driver = oneview.AgentPXEOneViewDriver()

        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.power, power.OneViewPower)
        self.assertIsInstance(driver.deploy, deploy.OneViewAgentDeploy)
        self.assertIsInstance(driver.management, management.OneViewManagement)

    def test_oneview_agent_driver_exc(self, mock_try_import):
        mock_try_import.return_value = None

        self.assertRaises(exception.DriverLoadError,
                          oneview.AgentPXEOneViewDriver)


@mock.patch.object(oneview.importutils, 'try_import', autospec=True)
class ISCSIPXEOneViewDriversTestCase(testtools.TestCase):

    def test_oneview_iscsi_driver(self, mock_try_import):
        mock_try_import.return_value = True

        driver = oneview.ISCSIPXEOneViewDriver()

        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.power, power.OneViewPower)
        self.assertIsInstance(driver.deploy, deploy.OneViewIscsiDeploy)
        self.assertIsInstance(driver.management, management.OneViewManagement)

    def test_oneview_iscsi_driver_exc(self, mock_try_import):
        mock_try_import.return_value = None

        self.assertRaises(exception.DriverLoadError,
                          oneview.ISCSIPXEOneViewDriver)
