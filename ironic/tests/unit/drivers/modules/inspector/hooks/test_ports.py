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

from oslo_utils import uuidutils

from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import ports as ports_hook
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.drivers.modules.inspector.hooks. \
    test_validate_interfaces import _PXE_INTERFACE
from ironic.tests.unit.drivers.modules.inspector.hooks. \
    test_validate_interfaces import _VALID
from ironic.tests.unit.objects import utils as obj_utils


class AddPortsTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.interfaces = {key: value.copy() for key, value in _VALID.items()
                           if key not in ('lo', 'em4')}
        self.macs = {
            _PXE_INTERFACE,
            '11:11:11:11:11:11',
            '22:22:22:22:22:22',
            '33:33:33:33:33:33',
        }

    def test_add_ports(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            ports_hook.add_ports(task, self.interfaces)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            {mac: (mac == _PXE_INTERFACE) for mac in self.macs})

    def test_duplicates(self):
        obj_utils.create_test_port(self.context,
                                   node_id=self.node.id,
                                   address=_PXE_INTERFACE,
                                   pxe_enabled=False)
        with task_manager.acquire(self.context, self.node.id) as task:
            ports_hook.add_ports(task, self.interfaces)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Always False because the PXE port already existed
            {mac: False for mac in self.macs})


class UpdatePortsTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.macs = {
            _PXE_INTERFACE,
            '11:11:11:11:11:11',
            '22:22:22:22:22:22',
            '33:33:33:33:33:33',
        }
        self.present_macs = {i['mac_address'] for i in _VALID.values()}
        self.extra_mac = '00:11:00:11:00:11'
        self.all_macs = self.present_macs | {self.extra_mac}
        for mac in self.all_macs:
            obj_utils.create_test_port(self.context,
                                       uuid=uuidutils.generate_uuid(),
                                       node_id=self.node.id,
                                       address=mac,
                                       pxe_enabled=(mac == self.extra_mac))

    def test_keep_all(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            ports_hook.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Nothing is removed by default, pxe_enabled updated
            {mac: (mac == _PXE_INTERFACE) for mac in self.all_macs})

    def test_keep_pxe_enabled(self):
        CONF.set_override('update_pxe_enabled', False, group='inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            ports_hook.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Nothing is removed by default, pxe_enabled kept intact
            {mac: (mac == self.extra_mac) for mac in self.all_macs})

    def test_keep_added(self):
        CONF.set_override('keep_ports', 'added', group='inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            ports_hook.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Extra ports removed, pxe_enabled updated
            {mac: (mac == _PXE_INTERFACE) for mac in self.macs})

    def test_keep_present(self):
        CONF.set_override('keep_ports', 'present', group='inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            ports_hook.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Extra port removed, pxe_enabled updated
            {mac: (mac == _PXE_INTERFACE) for mac in self.present_macs})
