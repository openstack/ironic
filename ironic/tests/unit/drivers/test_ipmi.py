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
from ironic.drivers.modules import noop
from ironic.drivers.modules import noop_mgmt
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import cinder
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class IPMIHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IPMIHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['ipmi'],
                    enabled_power_interfaces=['ipmitool'],
                    enabled_management_interfaces=['ipmitool', 'noop'],
                    enabled_raid_interfaces=['no-raid', 'agent'],
                    enabled_console_interfaces=['no-console'],
                    enabled_vendor_interfaces=['ipmitool', 'no-vendor'])

    def _validate_interfaces(self, task, **kwargs):
        self.assertIsInstance(
            task.driver.management,
            kwargs.get('management', ipmitool.IPMIManagement))
        self.assertIsInstance(
            task.driver.power,
            kwargs.get('power', ipmitool.IPMIPower))
        self.assertIsInstance(
            task.driver.boot,
            kwargs.get('boot', pxe.PXEBoot))
        self.assertIsInstance(
            task.driver.deploy,
            kwargs.get('deploy', agent.AgentDeploy))
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
        self.assertIsInstance(
            task.driver.rescue,
            kwargs.get('rescue', noop.NoRescue))

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='ipmi')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task)

    def test_override_with_shellinabox(self):
        self.config(enabled_console_interfaces=['ipmitool-shellinabox',
                                                'ipmitool-socat'])
        node = obj_utils.create_test_node(
            self.context, driver='ipmi',
            raid_interface='agent',
            console_interface='ipmitool-shellinabox',
            vendor_interface='no-vendor')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(
                task,
                console=ipmitool.IPMIShellinaboxConsole,
                raid=agent.AgentRAID,
                vendor=noop.NoVendor)

    def test_override_with_cinder_storage(self):
        self.config(enabled_storage_interfaces=['noop', 'cinder'])
        node = obj_utils.create_test_node(
            self.context, driver='ipmi',
            storage_interface='cinder')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task, storage=cinder.CinderStorage)

    def test_override_with_agent_rescue(self):
        self.config(enabled_rescue_interfaces=['no-rescue', 'agent'])
        node = obj_utils.create_test_node(
            self.context, driver='ipmi',
            rescue_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task, rescue=agent.AgentRescue)

    def test_override_with_noop_mgmt(self):
        self.config(enabled_management_interfaces=['ipmitool', 'noop'])
        node = obj_utils.create_test_node(
            self.context, driver='ipmi',
            management_interface='noop')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task,
                                      management=noop_mgmt.NoopManagement)
