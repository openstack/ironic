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
from ironic.drivers import irmc
from ironic.drivers.modules import agent
from ironic.drivers.modules import iscsi_deploy


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
        self.assertIsInstance(driver.vendor, iscsi_deploy.VendorPassthru)
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
        self.assertIsInstance(driver.vendor, irmc.agent.AgentVendorInterface)
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
