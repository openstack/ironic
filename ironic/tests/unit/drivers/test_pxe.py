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
from ironic.drivers.modules.amt import management as amt_management
from ironic.drivers.modules.amt import power as amt_power
from ironic.drivers.modules.amt import vendor as amt_vendor
from ironic.drivers.modules.cimc import management as cimc_management
from ironic.drivers.modules.cimc import power as cimc_power
from ironic.drivers.modules import iboot
from ironic.drivers.modules.ilo import console as ilo_console
from ironic.drivers.modules.ilo import inspect as ilo_inspect
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules import ipminative
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules.msftocs import management as msftocs_management
from ironic.drivers.modules.msftocs import power as msftocs_power
from ironic.drivers.modules import pxe as pxe_module
from ironic.drivers.modules import seamicro
from ironic.drivers.modules import snmp
from ironic.drivers.modules import ssh
from ironic.drivers.modules.ucs import management as ucs_management
from ironic.drivers.modules.ucs import power as ucs_power
from ironic.drivers.modules import virtualbox
from ironic.drivers.modules import wol
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

    def test_pxe_ipmitool_socat_driver(self):
        driver = pxe.PXEAndIPMIToolAndSocatDriver()

        self.assertIsInstance(driver.power, ipmitool.IPMIPower)
        self.assertIsInstance(driver.console, ipmitool.IPMISocatConsole)
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
    def test_pxe_seamicro_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndSeaMicroDriver()

        self.assertIsInstance(driver.power, seamicro.Power)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management, seamicro.Management)
        self.assertIsInstance(driver.seamicro_vendor, seamicro.VendorPassthru)
        self.assertIsInstance(driver.iscsi_vendor, iscsi_deploy.VendorPassthru)
        self.assertIsInstance(driver.vendor, utils.MixinVendorInterface)
        self.assertIsInstance(driver.console, seamicro.ShellinaboxConsole)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_seamicro_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndSeaMicroDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_iboot_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndIBootDriver()

        self.assertIsInstance(driver.power, iboot.IBootPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_iboot_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndIBootDriver)

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
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)
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
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              irmc_management.IRMCManagement)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_irmc_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndIRMCDriver)

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

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_amt_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndAMTDriver()

        self.assertIsInstance(driver.power, amt_power.AMTPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              amt_management.AMTManagement)
        self.assertIsInstance(driver.vendor, amt_vendor.AMTPXEVendorPassthru)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_amt_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndAMTDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_msftocs_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndMSFTOCSDriver()

        self.assertIsInstance(driver.power, msftocs_power.MSFTOCSPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.management,
                              msftocs_management.MSFTOCSManagement)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)

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
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)

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
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_cimc_driver_import_error(self, try_import_mock):
        try_import_mock.return_value = False

        self.assertRaises(exception.DriverLoadError,
                          pxe.PXEAndCIMCDriver)

    @mock.patch.object(pxe.importutils, 'try_import', spec_set=True,
                       autospec=True)
    def test_pxe_wakeonlan_driver(self, try_import_mock):
        try_import_mock.return_value = True

        driver = pxe.PXEAndWakeOnLanDriver()

        self.assertIsInstance(driver.power, wol.WakeOnLanPower)
        self.assertIsInstance(driver.boot, pxe_module.PXEBoot)
        self.assertIsInstance(driver.deploy, iscsi_deploy.ISCSIDeploy)
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)
