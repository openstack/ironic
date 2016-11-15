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

from ironic.drivers import agent
from ironic.drivers.modules import agent as agent_module
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import pxe
from ironic.tests import base


class AgentAndIPMIToolDriverTestCase(base.TestCase):

    def test___init__(self):
        driver = agent.AgentAndIPMIToolDriver()

        self.assertIsInstance(driver.power, ipmitool.IPMIPower)
        self.assertIsInstance(driver.console, ipmitool.IPMIShellinaboxConsole)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.management, ipmitool.IPMIManagement)
        self.assertIsInstance(driver.vendor, ipmitool.VendorPassthru)
        self.assertIsInstance(driver.raid, agent_module.AgentRAID)


class AgentAndIPMIToolAndSocatDriverTestCase(base.TestCase):

    def test___init__(self):
        driver = agent.AgentAndIPMIToolAndSocatDriver()

        self.assertIsInstance(driver.power, ipmitool.IPMIPower)
        self.assertIsInstance(driver.console, ipmitool.IPMISocatConsole)
        self.assertIsInstance(driver.boot, pxe.PXEBoot)
        self.assertIsInstance(driver.deploy, agent_module.AgentDeploy)
        self.assertIsInstance(driver.management, ipmitool.IPMIManagement)
        self.assertIsInstance(driver.vendor, ipmitool.VendorPassthru)
        self.assertIsInstance(driver.raid, agent_module.AgentRAID)
