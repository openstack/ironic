# Copyright 2015 Hewlett-Packard Development Company, L.P.
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
Test class for PXE Drivers
"""

import mock
import testtools

from ironic.common import exception
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import deploy as ilo_deploy
from ironic.drivers.modules.ilo import inspect as ilo_inspect
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules import ipminative
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe as pxe_module
from ironic.drivers.modules import ssh
from ironic.drivers.modules import virtualbox
from ironic.drivers import pxe
from ironic.drivers import utils


class PXEDriversTestCase(testtools.TestCase):

    def test_pxe_ipmitool_driver(self):
        driver = pxe.PXEAndIPMIToolDriver()

        self.assertIsInstance(driver.power, ipmitool.IPMIPower)
        self.assertIsInstance(driver.console, ipmitool.IPMIShellinaboxConsole)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management, ipmitool.IPMIManagement)
        self.assertIsNone(driver.inspect)
        # TODO(rameshg87): Need better way of asserting the routes.
        self.assertIsInstance(driver.vendor, utils.MixinVendorInterface)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    def test_pxe_ssh_driver(self):
        driver = pxe.PXEAndSSHDriver()

        self.assertIsInstance(driver.power, ssh.SSHPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management, ssh.SSHManagement)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)
        self.assertIsNone(driver.inspect)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ipminative_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndIPMINativeDriver()

        self.assertIsInstance(driver.power, ipminative.NativeIPMIPower)
        self.assertIsInstance(driver.console,
                              ipminative.NativeIPMIShellinaboxConsole)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              ipminative.NativeIPMIManagement)
        # TODO(rameshg87): Need better way of asserting the routes.
        self.assertIsInstance(driver.vendor, utils.MixinVendorInterface)
        self.assertIsNone(driver.inspect)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ipminative_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndIPMINativeDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ilo_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndIloDriver()

        self.assertIsInstance(driver.power, ilo_power.IloPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)
        self.assertIsInstance(driver.console,
                              ilo_deploy.IloConsoleInterface)
        self.assertIsInstance(driver.management,
                              ilo_management.IloManagement)
        self.assertIsInstance(driver.inspect, ilo_inspect.IloInspect)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ilo_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndIloDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_vbox_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndVirtualBoxDriver()

        self.assertIsInstance(driver.power, virtualbox.VirtualBoxPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              virtualbox.VirtualBoxManagement)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)
        self.assertIsInstance(driver.raid, agent.AgentRAID)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_vbox_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndVirtualBoxDriver)
