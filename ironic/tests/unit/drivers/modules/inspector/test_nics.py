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

import copy
from unittest import mock

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector import nics
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


_PXE_INTERFACE = 'aa:bb:cc:dd:ee:ff'


_INVENTORY = {
    'boot': {
        'pxe_interface': _PXE_INTERFACE,
    },
    'interfaces': [
        {
            'name': 'lo',
            'mac_address': '00:00:00:00:00:00',
            'ipv4_address': '127.0.0.1',
            'ipv6_address': '::1',
            'has_carrier': True,
        },
        {
            'name': 'em0',
            'mac_address': _PXE_INTERFACE,
            'ipv4_address': '192.0.2.1',
            'ipv6_address': '2001:db8::1',
            'has_carrier': True,
        },
        {
            'name': 'em1',
            'mac_address': '11:11:11:11:11:11',
            'ipv4_address': '192.0.2.2',
            'ipv6_address': '2001:db8::2',
            'has_carrier': True,
        },
        {
            'name': 'em2',
            'mac_address': '22:22:22:22:22:22',
            'ipv4_address': None,
            'ipv6_address': '2001:db8::3',
            'has_carrier': True,
        },
        {
            'name': 'em3',
            'mac_address': '33:33:33:33:33:33',
            'ipv4_address': '192.0.2.4',
            'ipv6_address': '2001:db8::4%em4',
            'has_carrier': True,
        },
        {
            'name': 'em4',
            'mac_address': '44:44:44:44:44:44',
            'ipv4_address': None,
            'ipv6_address': None,
            'has_carrier': False,
        },
    ],
}


_VALID = {
    'lo': {
        'name': 'lo',
        'mac_address': '00:00:00:00:00:00',
        'ipv4_address': '127.0.0.1',
        'ipv6_address': '::1',
        'has_carrier': True,
        'pxe_enabled': False,
    },
    'em0': {
        'name': 'em0',
        'mac_address': _PXE_INTERFACE,
        'ipv4_address': '192.0.2.1',
        'ipv6_address': '2001:db8::1',
        'has_carrier': True,
        'pxe_enabled': True,
    },
    'em1': {
        'name': 'em1',
        'mac_address': '11:11:11:11:11:11',
        'ipv4_address': '192.0.2.2',
        'ipv6_address': '2001:db8::2',
        'has_carrier': True,
        'pxe_enabled': False,
    },
    'em2': {
        'name': 'em2',
        'mac_address': '22:22:22:22:22:22',
        'ipv4_address': None,
        'ipv6_address': '2001:db8::3',
        'has_carrier': True,
        'pxe_enabled': False,
    },
    'em3': {
        'name': 'em3',
        'mac_address': '33:33:33:33:33:33',
        'ipv4_address': '192.0.2.4',
        'ipv6_address': '2001:db8::4',  # note: no scope
        'has_carrier': True,
        'pxe_enabled': False,
    },
    'em4': {
        'name': 'em4',
        'mac_address': '44:44:44:44:44:44',
        'ipv4_address': None,
        'ipv6_address': None,
        'has_carrier': False,
        'pxe_enabled': False,
    },
}


class GetInterfacesTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = copy.deepcopy(_INVENTORY)
        self.inventory['interfaces'].extend([
            # Broken records
            {
                'mac_address': '55:55:55:55:55:55',
                'ipv4_address': None,
                'ipv6_address': None,
                'has_carrier': False,
            },
            {
                'name': 'broken',
                'mac_address': 'banana!',
                'ipv4_address': None,
                'ipv6_address': None,
                'has_carrier': False,
            },
        ])

    def test_get_interfaces(self):
        result = nics.get_interfaces(self.node, self.inventory)
        self.assertEqual(_VALID, result)


class ValidateInterfacesTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = copy.deepcopy(_INVENTORY)
        self.interfaces = copy.deepcopy(_VALID)

    def test_pxe_only(self):
        expected = {'em0': _VALID['em0']}
        result = nics.validate_interfaces(
            self.node, self.inventory, self.interfaces)
        self.assertEqual(expected, result)
        # Make sure we don't modify the initial structures
        self.assertEqual(_INVENTORY, self.inventory)
        self.assertEqual(_VALID, self.interfaces)

    def test_all_interfaces(self):
        CONF.set_override('add_ports', 'all', group='inspector')
        expected = {key: value.copy() for key, value in _VALID.items()
                    if key != 'lo'}
        result = nics.validate_interfaces(
            self.node, self.inventory, self.interfaces)
        self.assertEqual(expected, result)

    @mock.patch.object(nics.LOG, 'warning', autospec=True)
    def test_no_pxe_fallback_to_all(self, mock_warn):
        del self.inventory['boot']
        expected = {key: value.copy() for key, value in _VALID.items()
                    if key != 'lo'}
        result = nics.validate_interfaces(
            self.node, self.inventory, self.interfaces)
        self.assertEqual(expected, result)
        self.assertTrue(mock_warn.called)

    def test_active_interfaces(self):
        CONF.set_override('add_ports', 'active', group='inspector')
        expected = {key: value.copy() for key, value in _VALID.items()
                    if key not in ('lo', 'em4')}
        result = nics.validate_interfaces(
            self.node, self.inventory, self.interfaces)
        self.assertEqual(expected, result)

    def test_nothing_to_add(self):
        CONF.set_override('add_ports', 'active', group='inspector')
        self.interfaces = {key: value.copy() for key, value in _VALID.items()
                           if key in ('lo', 'em4')}
        self.assertRaises(exception.InvalidNodeInventory,
                          nics.validate_interfaces,
                          self.node, self.inventory, self.interfaces)


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

    def test_add(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            nics.add_ports(task, self.interfaces)
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
            nics.add_ports(task, self.interfaces)
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
            nics.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Nothing is removed by default, pxe_enabled updated
            {mac: (mac == _PXE_INTERFACE) for mac in self.all_macs})

    def test_keep_pxe_enabled(self):
        CONF.set_override('update_pxe_enabled', False, group='inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            nics.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Nothing is removed by default, pxe_enabled kept intact
            {mac: (mac == self.extra_mac) for mac in self.all_macs})

    def test_keep_added(self):
        CONF.set_override('keep_ports', 'added', group='inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            nics.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Extra ports removed, pxe_enabled updated
            {mac: (mac == _PXE_INTERFACE) for mac in self.macs})

    def test_keep_present(self):
        CONF.set_override('keep_ports', 'present', group='inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            nics.update_ports(task, _VALID, self.macs)
        ports = objects.Port.list_by_node_id(self.context, self.node.id)
        self.assertEqual(
            {port.address: port.pxe_enabled for port in ports},
            # Extra port removed, pxe_enabled updated
            {mac: (mac == _PXE_INTERFACE) for mac in self.present_macs})
