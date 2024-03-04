# Copyright 2018 DMTF. All rights reserved.
#
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


from unittest import mock

import sushy

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.drivers.modules.redfish import vendor as redfish_vendor
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_redfish_info()


class RedfishVendorPassthruTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishVendorPassthruTestCase, self).setUp()
        self.config(enabled_bios_interfaces=['redfish'],
                    enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_vendor_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    @mock.patch.object(redfish_boot, 'eject_vmedia', autospec=True)
    def test_eject_vmedia_all(self, mock_eject_vmedia):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.vendor.eject_vmedia(task)
            mock_eject_vmedia.assert_called_once_with(task, None)

    @mock.patch.object(redfish_boot, 'eject_vmedia', autospec=True)
    def test_eject_vmedia_cd(self, mock_eject_vmedia):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.vendor.eject_vmedia(task,
                                            boot_device=sushy.VIRTUAL_MEDIA_CD)
            mock_eject_vmedia.assert_called_once_with(task,
                                                      sushy.VIRTUAL_MEDIA_CD)

    @mock.patch.object(redfish_vendor, 'redfish_utils', autospec=True)
    def test_validate_invalid_dev(self, mock_redfish_utils):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_CD])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            kwargs = {'boot_device': 'foo'}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'eject_vmedia', **kwargs)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_validate_invalid_create_subscription(self,
                                                  mock_get_event_service):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kwargs = {'Destination': 10000}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'create_subscription',
                **kwargs)

            kwargs = {'Destination': 'https://someulr', 'Context': 10}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'create_subscription',
                **kwargs)

            kwargs = {'Destination': 'https://someulr', 'Protocol': 10}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'create_subscription',
                **kwargs)

            mock_evt_serv = mock_get_event_service.return_value
            mock_evt_serv.get_event_types_for_subscription.return_value = \
                ['Alert']
            kwargs = {'Destination': 'https://someulr',
                      'EventTypes': ['Other']}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'create_subscription',
                **kwargs)

            kwargs = {'Destination': 'https://someulr',
                      'HttpHeaders': {'Content-Type': 'application/json'}}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'create_subscription',
                **kwargs
            )

    def test_validate_invalid_delete_subscription(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kwargs = {}  # Empty missing id key
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'delete_subscription',
                **kwargs)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_delete_subscription(self, mock_get_event_service):
        kwargs = {'id': '30'}
        mock_subscriptions = mock.MagicMock()
        mock_evt_serv = mock_get_event_service.return_value
        mock_evt_serv.subscriptions = mock_subscriptions
        mock_subscriptions.path.return_value = \
            "/redfish/v1/EventService/Subscriptions/"
        subscription = mock_subscriptions.get_member.return_value
        subscription.delete.return_value = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.vendor.delete_subscription(task, **kwargs)

            self.assertTrue(subscription.delete.called)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_invalid_delete_subscription(self, mock_get_event_service):
        kwargs = {'id': '30'}
        mock_subscriptions = mock.MagicMock()
        mock_evt_serv = mock_get_event_service.return_value
        mock_evt_serv.subscriptions = mock_subscriptions
        mock_subscriptions.path.return_value = \
            "/redfish/v1/EventService/Subscriptions/"
        uri = "/redfish/v1/EventService/Subscriptions/" + kwargs.get('id')
        mock_subscriptions.get_member.side_effect = [
            sushy.exceptions.ResourceNotFoundError('GET', uri, mock.Mock())
        ]
        subscription = mock_subscriptions.get_member.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.RedfishError,
                              task.driver.vendor.delete_subscription,
                              task, **kwargs)
            self.assertFalse(subscription.delete.called)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_get_all_subscriptions_empty(self, mock_get_event_service):
        mock_subscriptions = mock.MagicMock()
        mock_evt_serv = mock_get_event_service.return_value
        mock_evt_serv.subscriptions = mock_subscriptions
        mock_subscriptions.json.return_value = {
            "@odata.context": "<some context>",
            "@odata.id": "/redfish/v1/EventService/Subscriptions",
            "@odata.type": "#EventDestinationCollection",
            "Description": "List of Event subscriptions",
            "Members": [],
            "Members@odata.count": 0,
            "Name": "Event Subscriptions Collection"
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            output = task.driver.vendor.get_all_subscriptions(task)
            self.assertEqual(len(output.return_value['Members']), 0)
            mock_get_event_service.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_get_all_subscriptions(self, mock_get_event_service):
        mock_subscriptions = mock.MagicMock()
        mock_evt_serv = mock_get_event_service.return_value
        mock_evt_serv.subscriptions = mock_subscriptions
        mock_subscriptions.json.return_value = {
            "@odata.context": "<some context>",
            "@odata.id": "/redfish/v1/EventService/Subscriptions",
            "@odata.type": "#EventDestinationCollection.",
            "Description": "List of Event subscriptions",
            "Members": [
                {
                    "@odata.id": "/redfish/v1/EventService/Subscriptions/33/"
                }
            ],
            "Members@odata.count": 1,
            "Name": "Event Subscriptions Collection"
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            output = task.driver.vendor.get_all_subscriptions(task)
            self.assertEqual(len(output.return_value['Members']), 1)
            mock_get_event_service.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_get_subscription_does_not_exist(self, mock_get_event_service):
        kwargs = {'id': '30'}
        mock_subscriptions = mock.MagicMock()
        mock_evt_serv = mock_get_event_service.return_value
        mock_evt_serv.subscriptions = mock_subscriptions
        mock_subscriptions.path.return_value = \
            "/redfish/v1/EventService/Subscriptions/"
        uri = "/redfish/v1/EventService/Subscriptions/" + kwargs.get('id')
        mock_subscriptions.get_member.side_effect = [
            sushy.exceptions.ResourceNotFoundError('GET', uri, mock.Mock())
        ]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.RedfishError,
                              task.driver.vendor.get_subscription,
                              task, **kwargs)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_create_subscription(self, mock_get_event_service):
        subscription_json = {
            "@odata.context": "",
            "@odata.etag": "",
            "@odata.id": "/redfish/v1/EventService/Subscriptions/100",
            "@odata.type": "#EventDestination.v1_0_0.EventDestination",
            "Id": "100",
            "Context": "Ironic",
            "Description": "iLO Event Subscription",
            "Destination": "https://someurl",
            "EventTypes": [
                "Alert"
            ],
            "HttpHeaders": [],
            "Name": "Event Subscription",
            "Oem": {
            },
            "Protocol": "Redfish"
        }
        mock_event_service = mock_get_event_service.return_value

        subscription = mock.MagicMock()
        subscription.json.return_value = subscription_json
        mock_event_service.subscriptions.create = subscription
        kwargs = {
            'Destination': 'https://someurl',
            'HttpHeaders': [{"Content-Type": "application/json"}]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.vendor.create_subscription(task, **kwargs)

    @mock.patch.object(redfish_utils, 'get_event_service', autospec=True)
    def test_get_subscription_exists(self, mock_get_event_service):
        kwargs = {'id': '36'}
        mock_subscriptions = mock.MagicMock()
        mock_evt_serv = mock_get_event_service.return_value
        mock_evt_serv.subscriptions = mock_subscriptions
        mock_subscriptions.path.return_value = \
            "/redfish/v1/EventService/Subscriptions/"
        subscription = mock_subscriptions.get_member.return_value
        subscription.json.return_value = {
            "@odata.context": "",
            "@odata.etag": "",
            "@odata.id": "/redfish/v1/EventService/Subscriptions/36",
            "@odata.type": "#EventDestination.v1_0_0.EventDestination",
            "Id": "36",
            "Context": "Ironic",
            "Description": "iLO Event Subscription",
            "Destination": "https://someurl",
            "EventTypes": [
                "Alert"
            ],
            "HttpHeaders": [],
            "Name": "Event Subscription",
            "Oem": {
            },
            "Protocol": "Redfish"
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.vendor.get_subscription(task, **kwargs)
