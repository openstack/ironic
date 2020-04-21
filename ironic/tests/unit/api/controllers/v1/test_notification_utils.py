#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Test class for ironic-api notification utilities."""

import mock
from oslo_utils import uuidutils

from ironic.api.controllers.v1 import notification_utils as notif_utils
from ironic.api import types as atypes
from ironic.objects import fields
from ironic.objects import notification
from ironic.tests import base as tests_base
from ironic.tests.unit.objects import utils as obj_utils


class APINotifyTestCase(tests_base.TestCase):

    def setUp(self):
        super(APINotifyTestCase, self).setUp()
        self.node_notify_mock = mock.Mock()
        self.port_notify_mock = mock.Mock()
        self.chassis_notify_mock = mock.Mock()
        self.portgroup_notify_mock = mock.Mock()
        self.node_notify_mock.__name__ = 'NodeCRUDNotification'
        self.port_notify_mock.__name__ = 'PortCRUDNotification'
        self.chassis_notify_mock.__name__ = 'ChassisCRUDNotification'
        self.portgroup_notify_mock.__name__ = 'PortgroupCRUDNotification'
        _notification_mocks = {
            'chassis': (self.chassis_notify_mock,
                        notif_utils.CRUD_NOTIFY_OBJ['chassis'][1]),
            'node': (self.node_notify_mock,
                     notif_utils.CRUD_NOTIFY_OBJ['node'][1]),
            'port': (self.port_notify_mock,
                     notif_utils.CRUD_NOTIFY_OBJ['port'][1]),
            'portgroup': (self.portgroup_notify_mock,
                          notif_utils.CRUD_NOTIFY_OBJ['portgroup'][1])
        }
        self.addCleanup(self._restore, notif_utils.CRUD_NOTIFY_OBJ.copy())
        notif_utils.CRUD_NOTIFY_OBJ = _notification_mocks

    def _restore(self, value):
        notif_utils.CRUD_NOTIFY_OBJ = value

    def test_common_params(self):
        self.config(host='fake-host')
        node = obj_utils.get_test_node(self.context)
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils._emit_api_notification(self.context, node, 'create',
                                           test_level, test_status,
                                           chassis_uuid=None)
        init_kwargs = self.node_notify_mock.call_args[1]
        publisher = init_kwargs['publisher']
        event_type = init_kwargs['event_type']
        level = init_kwargs['level']
        self.assertEqual('fake-host', publisher.host)
        self.assertEqual('ironic-api', publisher.service)
        self.assertEqual('create', event_type.action)
        self.assertEqual(test_status, event_type.status)
        self.assertEqual(test_level, level)

    def test_node_notification(self):
        chassis_uuid = uuidutils.generate_uuid()
        node = obj_utils.get_test_node(self.context,
                                       instance_info={'foo': 'baz'},
                                       driver_info={'param': 104})
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils._emit_api_notification(self.context, node, 'create',
                                           test_level, test_status,
                                           chassis_uuid=chassis_uuid)
        init_kwargs = self.node_notify_mock.call_args[1]
        payload = init_kwargs['payload']
        event_type = init_kwargs['event_type']
        self.assertEqual('node', event_type.object)
        self.assertEqual(node.uuid, payload.uuid)
        self.assertEqual({'foo': 'baz'}, payload.instance_info)
        self.assertEqual({'param': 104}, payload.driver_info)
        self.assertEqual(chassis_uuid, payload.chassis_uuid)

    def test_node_notification_mask_secrets(self):
        test_info = {'password': 'secret123', 'some_value': 'fake-value'}
        node = obj_utils.get_test_node(self.context,
                                       driver_info=test_info)
        notification.mask_secrets(node)
        self.assertEqual('******', node.driver_info['password'])
        self.assertEqual('fake-value', node.driver_info['some_value'])

    def test_notification_uuid_unset(self):
        node = obj_utils.get_test_node(self.context)
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils._emit_api_notification(self.context, node, 'create',
                                           test_level, test_status,
                                           chassis_uuid=atypes.Unset)
        init_kwargs = self.node_notify_mock.call_args[1]
        payload = init_kwargs['payload']
        self.assertIsNone(payload.chassis_uuid)

    def test_chassis_notification(self):
        chassis = obj_utils.get_test_chassis(self.context,
                                             extra={'foo': 'boo'},
                                             description='bare01')
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils._emit_api_notification(self.context, chassis, 'create',
                                           test_level, test_status)
        init_kwargs = self.chassis_notify_mock.call_args[1]
        payload = init_kwargs['payload']
        event_type = init_kwargs['event_type']
        self.assertEqual('chassis', event_type.object)
        self.assertEqual(chassis.uuid, payload.uuid)
        self.assertEqual({'foo': 'boo'}, payload.extra)
        self.assertEqual('bare01', payload.description)

    def test_port_notification(self):
        node_uuid = uuidutils.generate_uuid()
        portgroup_uuid = uuidutils.generate_uuid()
        port = obj_utils.get_test_port(self.context,
                                       address='11:22:33:77:88:99',
                                       local_link_connection={'a': 25},
                                       extra={'as': 34},
                                       pxe_enabled=False)
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils._emit_api_notification(self.context, port, 'create',
                                           test_level, test_status,
                                           node_uuid=node_uuid,
                                           portgroup_uuid=portgroup_uuid)
        init_kwargs = self.port_notify_mock.call_args[1]
        payload = init_kwargs['payload']
        event_type = init_kwargs['event_type']
        self.assertEqual('port', event_type.object)
        self.assertEqual(port.uuid, payload.uuid)
        self.assertEqual(node_uuid, payload.node_uuid)
        self.assertEqual(portgroup_uuid, payload.portgroup_uuid)
        self.assertEqual('11:22:33:77:88:99', payload.address)
        self.assertEqual({'a': 25}, payload.local_link_connection)
        self.assertEqual({'as': 34}, payload.extra)
        self.assertIs(False, payload.pxe_enabled)

    def test_portgroup_notification(self):
        node_uuid = uuidutils.generate_uuid()
        portgroup = obj_utils.get_test_portgroup(self.context,
                                                 address='22:55:88:AA:BB:99',
                                                 name='new01',
                                                 mode='mode2',
                                                 extra={'bs': 11})
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils._emit_api_notification(self.context, portgroup, 'create',
                                           test_level, test_status,
                                           node_uuid=node_uuid)
        init_kwargs = self.portgroup_notify_mock.call_args[1]
        payload = init_kwargs['payload']
        event_type = init_kwargs['event_type']
        self.assertEqual('portgroup', event_type.object)
        self.assertEqual(portgroup.uuid, payload.uuid)
        self.assertEqual(node_uuid, payload.node_uuid)
        self.assertEqual(portgroup.address, payload.address)
        self.assertEqual(portgroup.name, payload.name)
        self.assertEqual(portgroup.mode, payload.mode)
        self.assertEqual(portgroup.extra, payload.extra)
        self.assertEqual(portgroup.standalone_ports_supported,
                         payload.standalone_ports_supported)

    @mock.patch('ironic.objects.node.NodeMaintenanceNotification')
    def test_node_maintenance_notification(self, maintenance_mock):
        maintenance_mock.__name__ = 'NodeMaintenanceNotification'
        node = obj_utils.get_test_node(self.context,
                                       maintenance=True,
                                       maintenance_reason='test reason')
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.START
        notif_utils._emit_api_notification(self.context, node,
                                           'maintenance_set',
                                           test_level, test_status)
        init_kwargs = maintenance_mock.call_args[1]
        payload = init_kwargs['payload']
        event_type = init_kwargs['event_type']
        self.assertEqual('node', event_type.object)
        self.assertEqual(node.uuid, payload.uuid)
        self.assertEqual(True, payload.maintenance)
        self.assertEqual('test reason', payload.maintenance_reason)

    @mock.patch.object(notification.NotificationBase, 'emit')
    def test_emit_maintenance_notification(self, emit_mock):
        node = obj_utils.get_test_node(self.context)
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.START
        notif_utils._emit_api_notification(self.context, node,
                                           'maintenance_set',
                                           test_level, test_status)
        emit_mock.assert_called_once_with(self.context)
