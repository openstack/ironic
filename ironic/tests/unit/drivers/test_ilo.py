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
from ironic.drivers import ilo
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import boot
from ironic.drivers.modules.ilo import console
from ironic.drivers.modules.ilo import deploy
from ironic.drivers.modules.ilo import inspect
from ironic.drivers.modules.ilo import management
from ironic.drivers.modules.ilo import power
from ironic.drivers.modules.ilo import vendor


@mock.patch.object(ilo.importutils, 'try_import', spec_set=True,
                   autospec=True)
class IloVirtualMediaIscsiDriversTestCase(testtools.TestCase):

    def test_ilo_iscsi_driver(self, mock_try_import):
        mock_try_import.return_value = True

        driver = ilo.IloVirtualMediaIscsiDriver()

        self.assertIsInstance(driver.power, power.IloPower)
        self.assertIsInstance(driver.boot, boot.IloVirtualMediaBoot)
        self.assertIsInstance(driver.deploy, deploy.IloVirtualMediaIscsiDeploy)
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
        self.assertIsInstance(driver.deploy, deploy.IloVirtualMediaAgentDeploy)
        self.assertIsInstance(driver.console, console.IloConsoleInterface)
        self.assertIsInstance(driver.management, management.IloManagement)
        self.assertIsInstance(driver.inspect, inspect.IloInspect)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    def test_ilo_iscsi_driver_exc(self, mock_try_import):
        mock_try_import.return_value = None

        self.assertRaises(exception.DriverLoadError,
                          ilo.IloVirtualMediaAgentDriver)
