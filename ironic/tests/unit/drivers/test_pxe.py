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
from ironic.drivers.modules.cimc import management as cimc_management
from ironic.drivers.modules.cimc import power as cimc_power
from ironic.drivers.modules.ilo import console as ilo_console
from ironic.drivers.modules.ilo import inspect as ilo_inspect
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules.ilo import vendor as ilo_vendor
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe as pxe_module
from ironic.drivers.modules import snmp
from ironic.drivers.modules.ucs import management as ucs_management
from ironic.drivers.modules.ucs import power as ucs_power
from ironic.drivers import pxe


class PXEDriversTestCase(testtools.TestCase):

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ilo_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndIloDriver()

        self.assertIsInstance(driver.power, ilo_power.IloPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.vendor, ilo_vendor.VendorPassthru)
        self.assertIsInstance(driver.console,
                              ilo_console.IloConsoleInterface)
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
    def test_pxe_snmp_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndSNMPDriver()

        self.assertIsInstance(driver.power, snmp.SNMPPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsNone(driver.management)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_snmp_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndSNMPDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_irmc_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndIRMCDriver()

        self.assertIsInstance(driver.power, irmc_power.IRMCPower)
        self.assertIsInstance(driver.console, ipmitool.IPMIShellinaboxConsole)
        self.assertIsInstance(driver.boot, irmc_boot.IRMCPXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              irmc_management.IRMCManagement)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_irmc_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndIRMCDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ucs_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndUcsDriver()

        self.assertIsInstance(driver.power, ucs_power.Power)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              ucs_management.UcsManagement)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_ucs_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndUcsDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_cimc_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndCIMCDriver()

        self.assertIsInstance(driver.power, cimc_power.Power)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              cimc_management.CIMCManagement)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_cimc_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndCIMCDriver)
