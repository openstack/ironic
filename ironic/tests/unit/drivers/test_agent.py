# Copyright 2015 Rackspace, Inc.
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
Test class for Agent Deploy Driver
"""

import mock
import testtools

from ironic.common import exception
from ironic.drivers import agent
from ironic.drivers.modules import agent as agent_module
from ironic.drivers.modules.amt import management as amt_management
from ironic.drivers.modules.amt import power as amt_power
from ironic.drivers.modules import iboot
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import pxe
from ironic.drivers.modules import wol
from ironic.drivers import utils
from ironic.tests import base


class AgentAndIPMIToolDriverTestCase(base.TestCase):

    def test___init__(self):
        driver = agent.AgentAndIPMIToolDriver()

        self.assertIsInstance(driver.power, ipmitool.IPMIPower)
        self.assertIsInstance(driver.console, ipmitool.IPMIShellinaboxConsole)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.management, ipmitool.IPMIManagement)
        self.assertIsInstance(driver.agent_vendor,
                              agent_module.AgentVendorInterface)
        self.assertIsInstance(driver.ipmi_vendor, ipmitool.VendorPassthru)
        self.assertIsInstance(driver.vendor, utils.MixinVendorInterface)
        self.assertIsInstance(driver.raid, agent_module.AgentRAID)


class AgentAndIPMIToolAndSocatDriverTestCase(base.TestCase):

    def test___init__(self):
        driver = agent.AgentAndIPMIToolAndSocatDriver()

        self.assertIsInstance(driver.power, ipmitool.IPMIPower)
        self.assertIsInstance(driver.console, ipmitool.IPMISocatConsole)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.management, ipmitool.IPMIManagement)
        self.assertIsInstance(driver.agent_vendor,
                              agent_module.AgentVendorInterface)
        self.assertIsInstance(driver.ipmi_vendor, ipmitool.VendorPassthru)
        self.assertIsInstance(driver.vendor, utils.MixinVendorInterface)
        self.assertIsInstance(driver.raid, agent_module.AgentRAID)


class AgentAndAMTDriverTestCase(testtools.TestCase):

    @mock.patch.object(agent.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test___init__(self, mock_try_import):
        mock_try_import.return_value = True
        driver = agent.AgentAndAMTDriver()

        self.assertIsInstance(driver.power, amt_power.AMTPower)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.management, amt_management.AMTManagement)
        self.assertIsInstance(driver.vendor, agent_module.AgentVendorInterface)

    @mock.patch.object(agent.importutils, 'try_import')
    def test___init___try_import_exception(self, mock_try_import):
        mock_try_import.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          agent.AgentAndAMTDriver)


class AgentAndWakeOnLanDriverTestCase(testtools.TestCase):

    def test___init__(self):
        driver = agent.AgentAndWakeOnLanDriver()

        self.assertIsInstance(driver.power, wol.WakeOnLanPower)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.vendor, agent_module.AgentVendorInterface)


class AgentAndIBootDriverTestCase(testtools.TestCase):

    def test___init__(self):
        driver = agent.AgentAndIBootDriver()

        self.assertIsInstance(driver.power, iboot.IBootPower)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.vendor, agent_module.AgentVendorInterface)
