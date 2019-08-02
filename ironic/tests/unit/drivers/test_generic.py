# Copyright 2016 Red Hat, Inc.
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

import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers import base as driver_base
from ironic.drivers.modules import agent
from ironic.drivers.modules import fake
from ironic.drivers.modules import inspector
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.drivers.modules import noop_mgmt
from ironic.drivers.modules import pxe
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class ManualManagementHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ManualManagementHardwareTestCase, self).setUp()
        self.config(enabled_hardware_types=['manual-management'],
                    enabled_power_interfaces=['fake'],
                    enabled_management_interfaces=['noop', 'fake'])

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='manual-management')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.management,
                                  noop_mgmt.NoopManagement)
            self.assertIsInstance(task.driver.power, fake.FakePower)
            self.assertIsInstance(task.driver.boot, pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy, iscsi_deploy.ISCSIDeploy)
            self.assertIsInstance(task.driver.inspect, noop.NoInspect)
            self.assertIsInstance(task.driver.raid, noop.NoRAID)

    def test_supported_interfaces(self):
        self.config(enabled_inspect_interfaces=['inspector', 'no-inspect'],
                    enabled_raid_interfaces=['agent'])
        node = obj_utils.create_test_node(self.context,
                                          driver='manual-management',
                                          management_interface='fake',
                                          deploy_interface='direct',
                                          raid_interface='agent')
        with task_manager.acquire(self.context, node.id) as task:
            self.assertIsInstance(task.driver.management, fake.FakeManagement)
            self.assertIsInstance(task.driver.power, fake.FakePower)
            self.assertIsInstance(task.driver.boot, pxe.PXEBoot)
            self.assertIsInstance(task.driver.deploy, agent.AgentDeploy)
            self.assertIsInstance(task.driver.inspect, inspector.Inspector)
            self.assertIsInstance(task.driver.raid, agent.AgentRAID)

    def test_get_properties(self):
        # These properties are from vendor (agent) and boot (pxe) interfaces
        expected_prop_keys = [
            'deploy_forces_oob_reboot', 'deploy_kernel', 'deploy_ramdisk',
            'force_persistent_boot_device', 'rescue_kernel', 'rescue_ramdisk']
        hardware_type = driver_factory.get_hardware_type("manual-management")
        properties = hardware_type.get_properties()
        self.assertEqual(sorted(expected_prop_keys), sorted(properties))

    @mock.patch.object(driver_factory, 'default_interface', autospec=True)
    def test_get_properties_none(self, mock_def_iface):
        hardware_type = driver_factory.get_hardware_type("manual-management")
        mock_def_iface.side_effect = exception.NoValidDefaultForInterface("no")
        properties = hardware_type.get_properties()
        self.assertEqual({}, properties)
        self.assertEqual(len(driver_base.ALL_INTERFACES),
                         mock_def_iface.call_count)
