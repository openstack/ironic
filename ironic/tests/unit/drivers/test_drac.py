# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_utils import uuidutils

from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import drac
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipxe
from ironic.drivers.modules.network import flat as flat_net
from ironic.drivers.modules import noop
from ironic.drivers.modules import redfish
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class IDRACHardwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IDRACHardwareTestCase, self).setUp()
        self.config_temp_dir('http_root', group='deploy')
        self.config(enabled_hardware_types=['idrac'],
                    enabled_boot_interfaces=[
                        'idrac-redfish-virtual-media', 'ipxe', 'pxe'],
                    enabled_management_interfaces=['idrac-redfish'],
                    enabled_power_interfaces=['idrac-redfish', 'redfish'],
                    enabled_inspect_interfaces=[
                        'idrac-redfish', 'inspector',
                        'no-inspect'],
                    enabled_network_interfaces=['flat', 'neutron', 'noop'],
                    enabled_raid_interfaces=[
                        'idrac-redfish', 'no-raid',
                        'agent'],
                    enabled_vendor_interfaces=[
                        'idrac-redfish', 'redfish', 'no-vendor'],
                    enabled_bios_interfaces=[
                        'idrac-redfish', 'redfish', 'no-bios'])

    def _validate_interfaces(self, driver, **kwargs):
        self.assertIsInstance(
            driver.boot,
            kwargs.get('boot', ipxe.iPXEBoot))
        self.assertIsInstance(
            driver.deploy,
            kwargs.get('deploy', agent.AgentDeploy))
        self.assertIsInstance(
            driver.management,
            kwargs.get('management', drac.management.DracRedfishManagement))
        self.assertIsInstance(
            driver.power,
            kwargs.get('power', drac.power.DracRedfishPower))

        self.assertIsInstance(
            driver.bios,
            kwargs.get('bios', drac.bios.DracRedfishBIOS))

        self.assertIsInstance(
            driver.console,
            kwargs.get('console', noop.NoConsole))

        self.assertIsInstance(
            driver.inspect,
            kwargs.get('inspect', drac.inspect.DracRedfishInspect))

        self.assertIsInstance(
            driver.network,
            kwargs.get('network', flat_net.FlatNetwork))

        self.assertIsInstance(
            driver.raid,
            kwargs.get('raid', drac.raid.DracRedfishRAID))

        self.assertIsInstance(
            driver.storage,
            kwargs.get('storage', noop_storage.NoopStorage))

        self.assertIsInstance(
            driver.vendor,
            kwargs.get('vendor',
                       drac.vendor_passthru.DracRedfishVendorPassthru))

    def test_default_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='idrac')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task.driver)

    def test_override_with_inspector(self):
        node = obj_utils.create_test_node(self.context, driver='idrac',
                                          inspect_interface='inspector')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task.driver,
                                      inspect=inspector.Inspector)

    def test_override_with_raid(self):
        for iface, impl in [('agent', agent.AgentRAID),
                            ('no-raid', noop.NoRAID)]:
            node = obj_utils.create_test_node(self.context,
                                              uuid=uuidutils.generate_uuid(),
                                              driver='idrac',
                                              raid_interface=iface)
            with task_manager.acquire(self.context, node.id) as task:
                self._validate_interfaces(task.driver, raid=impl)

    def test_override_with_redfish_raid(self):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='idrac',
                                          raid_interface='idrac-redfish')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(task.driver,
                                      raid=drac.raid.DracRedfishRAID)

    def test_override_with_redfish_vendor(self):
        for iface, impl in [('redfish',
                             redfish.vendor.RedfishVendorPassthru),
                            ('no-vendor', noop.NoVendor)]:
            node = obj_utils.create_test_node(self.context,
                                              uuid=uuidutils.generate_uuid(),
                                              driver='idrac',
                                              vendor_interface=iface)
            with task_manager.acquire(self.context, node.id) as task:
                self._validate_interfaces(task.driver,
                                          vendor=impl)

    def test_override_with_redfish_management_and_power(self):
        node = obj_utils.create_test_node(self.context, driver='idrac',
                                          management_interface='idrac-redfish',
                                          power_interface='redfish')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(
                task.driver,
                management=drac.management.DracRedfishManagement,
                power=redfish.power.RedfishPower)

    def test_override_with_redfish_bios(self):
        for iface, impl in [('redfish', redfish.bios.RedfishBIOS),
                            ('no-bios', noop.NoBIOS)]:
            node = obj_utils.create_test_node(self.context,
                                              uuid=uuidutils.generate_uuid(),
                                              driver='idrac',
                                              bios_interface=iface)
            with task_manager.acquire(self.context, node.id) as task:
                self._validate_interfaces(task.driver, bios=impl)

    def test_override_with_redfish_inspect(self):
        node = obj_utils.create_test_node(self.context, driver='idrac',
                                          inspect_interface='idrac-redfish')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(
                task.driver,
                inspect=drac.inspect.DracRedfishInspect)

    def test_override_with_redfish_virtual_media_boot(self):
        node = obj_utils.create_test_node(
            self.context, driver='idrac',
            boot_interface='idrac-redfish-virtual-media')
        with task_manager.acquire(self.context, node.id) as task:
            self._validate_interfaces(
                task.driver,
                boot=drac.boot.DracRedfishVirtualMediaBoot)
