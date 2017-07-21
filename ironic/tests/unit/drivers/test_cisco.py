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

from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

from ironic.drivers.modules.cimc import management as cimc_mgmt
from ironic.drivers.modules.cimc import power as cimc_power

from ironic.drivers.modules.ucs import management as ucs_mgmt
from ironic.drivers.modules.ucs import power as ucs_power


class CiscoUCSStandaloneHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(CiscoUCSStandaloneHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['cisco-ucs-standalone'],
                    enabled_power_interfaces=['cimc', 'ipmitool'],
                    enabled_management_interfaces=['cimc', 'ipmitool'],
                    enabled_raid_interfaces=['no-raid', 'agent'],
                    enabled_console_interfaces=['no-console'],
                    enabled_vendor_interfaces=['ipmitool', 'no-vendor'])

    def _validate_interfaces(self, task, **kwargs):
            self.assertIsInstance(
                task.driver.management,
                kwargs.get('management', cimc_mgmt.CIMCManagement))
            self.assertIsInstance(
                task.driver.power,
                kwargs.get('power', cimc_power.Power))
            self.assertIsInstance(
                task.driver.boot,
                kwargs.get('boot', pxe.PXEBoot))
            self.assertIsInstance(
                task.driver.deploy,
                kwargs.get('deploy', iscsi_deploy.ISCSIDeploy))
            self.assertIsInstance(
                task.driver.console,
                kwargs.get('console', noop.NoConsole))
            self.assertIsInstance(
                task.driver.raid,
                kwargs.get('raid', noop.NoRAID))
            self.assertIsInstance(
                task.driver.vendor,
                kwargs.get('vendor', ipmitool.VendorPassthru))
            self.assertIsInstance(
                task.driver.storage,
                kwargs.get('storage', noop_storage.NoopStorage))

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='cisco-ucs-standalone')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task)

    def test_override_with_ipmi_interfaces(self):
        node = obj_utils.create_test_node(
            self.context, driver='cisco-ucs-standalone',
            power_interface='ipmitool',
            management_interface='ipmitool',
            deploy_interface='direct',
            raid_interface='agent',
            console_interface='no-console',
            vendor_interface='no-vendor')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(
                task,
                deploy=agent.AgentDeploy,
                console=noop.NoConsole,
                raid=agent.AgentRAID,
                vendor=noop.NoVendor,
                power=ipmitool.IPMIPower,
                management=ipmitool.IPMIManagement)


class CiscoUCSManagedHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(CiscoUCSManagedHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['cisco-ucs-managed'],
                    enabled_power_interfaces=['ucsm', 'cimc'],
                    enabled_management_interfaces=['ucsm', 'cimc'],
                    enabled_raid_interfaces=['no-raid', 'agent'],
                    enabled_console_interfaces=['no-console'],
                    enabled_vendor_interfaces=['ipmitool', 'no-vendor'])

    def _validate_interfaces(self, task, **kwargs):
            self.assertIsInstance(
                task.driver.management,
                kwargs.get('management', ucs_mgmt.UcsManagement))
            self.assertIsInstance(
                task.driver.power,
                kwargs.get('power', ucs_power.Power))
            self.assertIsInstance(
                task.driver.boot,
                kwargs.get('boot', pxe.PXEBoot))
            self.assertIsInstance(
                task.driver.deploy,
                kwargs.get('deploy', iscsi_deploy.ISCSIDeploy))
            self.assertIsInstance(
                task.driver.console,
                kwargs.get('console', noop.NoConsole))
            self.assertIsInstance(
                task.driver.raid,
                kwargs.get('raid', noop.NoRAID))
            self.assertIsInstance(
                task.driver.vendor,
                kwargs.get('vendor', ipmitool.VendorPassthru))
            self.assertIsInstance(
                task.driver.storage,
                kwargs.get('storage', noop_storage.NoopStorage))

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='cisco-ucs-managed')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task)

    def test_override_with_cimc_interfaces(self):
        node = obj_utils.create_test_node(
            self.context, driver='cisco-ucs-managed',
            power_interface='cimc',
            management_interface='cimc',
            deploy_interface='direct',
            raid_interface='agent',
            console_interface='no-console',
            vendor_interface='no-vendor')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(
                task,
                deploy=agent.AgentDeploy,
                console=noop.NoConsole,
                raid=agent.AgentRAID,
                vendor=noop.NoVendor,
                power=cimc_power.Power,
                management=cimc_mgmt.CIMCManagement)
