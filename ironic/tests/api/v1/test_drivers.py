# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
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

import json

import mock
from six.moves import http_client
from testtools.matchers import HasLength

from ironic.api.controllers.v1 import driver
from ironic.common import exception
from ironic.conductor import rpcapi
from ironic.tests.api import base


class TestListDrivers(base.FunctionalTest):
    d1 = 'fake-driver1'
    d2 = 'fake-driver2'
    h1 = 'fake-host1'
    h2 = 'fake-host2'

    def register_fake_conductors(self):
        self.dbapi.register_conductor({
            'hostname': self.h1,
            'drivers': [self.d1, self.d2],
        })
        self.dbapi.register_conductor({
            'hostname': self.h2,
            'drivers': [self.d2],
        })

    def test_drivers(self):
        self.register_fake_conductors()
        expected = sorted([
            {'name': self.d1, 'hosts': [self.h1]},
            {'name': self.d2, 'hosts': [self.h1, self.h2]},
        ], key=lambda d: d['name'])
        data = self.get_json('/drivers')
        self.assertThat(data['drivers'], HasLength(2))
        drivers = sorted(data['drivers'], key=lambda d: d['name'])
        for i in range(len(expected)):
            d = drivers[i]
            self.assertEqual(expected[i]['name'], d['name'])
            self.assertEqual(sorted(expected[i]['hosts']), sorted(d['hosts']))
            self.validate_link(d['links'][0]['href'])
            self.validate_link(d['links'][1]['href'])

    def test_drivers_no_active_conductor(self):
        data = self.get_json('/drivers')
        self.assertThat(data['drivers'], HasLength(0))
        self.assertEqual([], data['drivers'])

    def test_drivers_get_one_ok(self):
        self.register_fake_conductors()
        data = self.get_json('/drivers/%s' % self.d1)
        self.assertEqual(self.d1, data['name'])
        self.assertEqual([self.h1], data['hosts'])
        self.validate_link(data['links'][0]['href'])
        self.validate_link(data['links'][1]['href'])

    def test_drivers_get_one_not_found(self):
        response = self.get_json('/drivers/%s' % self.d1, expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    @mock.patch.object(rpcapi.ConductorAPI, 'driver_vendor_passthru')
    def test_driver_vendor_passthru_sync(self, mocked_driver_vendor_passthru):
        self.register_fake_conductors()
        mocked_driver_vendor_passthru.return_value = {
            'return': {'return_key': 'return_value'},
            'async': False,
            'attach': False}
        response = self.post_json(
            '/drivers/%s/vendor_passthru/do_test' % self.d1,
            {'test_key': 'test_value'})
        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(mocked_driver_vendor_passthru.return_value['return'],
                         response.json)

    @mock.patch.object(rpcapi.ConductorAPI, 'driver_vendor_passthru')
    def test_driver_vendor_passthru_async(self, mocked_driver_vendor_passthru):
        self.register_fake_conductors()
        mocked_driver_vendor_passthru.return_value = {'return': None,
                                                      'async': True,
                                                      'attach': False}
        response = self.post_json(
            '/drivers/%s/vendor_passthru/do_test' % self.d1,
            {'test_key': 'test_value'})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertIsNone(mocked_driver_vendor_passthru.return_value['return'])

    @mock.patch.object(rpcapi.ConductorAPI, 'driver_vendor_passthru')
    def test_driver_vendor_passthru_put(self, mocked_driver_vendor_passthru):
        self.register_fake_conductors()
        return_value = {'return': None, 'async': True, 'attach': False}
        mocked_driver_vendor_passthru.return_value = return_value
        response = self.put_json(
            '/drivers/%s/vendor_passthru/do_test' % self.d1,
            {'test_key': 'test_value'})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(return_value['return'], response.json)

    @mock.patch.object(rpcapi.ConductorAPI, 'driver_vendor_passthru')
    def test_driver_vendor_passthru_get(self, mocked_driver_vendor_passthru):
        self.register_fake_conductors()
        return_value = {'return': 'foo', 'async': False, 'attach': False}
        mocked_driver_vendor_passthru.return_value = return_value
        response = self.get_json(
            '/drivers/%s/vendor_passthru/do_test' % self.d1)
        self.assertEqual(return_value['return'], response)

    @mock.patch.object(rpcapi.ConductorAPI, 'driver_vendor_passthru')
    def test_driver_vendor_passthru_delete(self, mock_driver_vendor_passthru):
        self.register_fake_conductors()
        return_value = {'return': None, 'async': True, 'attach': False}
        mock_driver_vendor_passthru.return_value = return_value
        response = self.delete(
            '/drivers/%s/vendor_passthru/do_test' % self.d1)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(return_value['return'], response.json)

    def test_driver_vendor_passthru_driver_not_found(self):
        # tests when given driver is not found
        # e.g. get_topic_for_driver fails to find the driver
        response = self.post_json(
            '/drivers/%s/vendor_passthru/do_test' % self.d1,
            {'test_key': 'test_value'},
            expect_errors=True)

        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_driver_vendor_passthru_method_not_found(self):
        response = self.post_json(
            '/drivers/%s/vendor_passthru' % self.d1,
            {'test_key': 'test_value'},
            expect_errors=True)

        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        error = json.loads(response.json['error_message'])
        self.assertEqual('Missing argument: "method"',
                         error['faultstring'])

    @mock.patch.object(rpcapi.ConductorAPI,
                       'get_driver_vendor_passthru_methods')
    def test_driver_vendor_passthru_methods(self, get_methods_mock):
        self.register_fake_conductors()
        return_value = {'foo': 'bar'}
        get_methods_mock.return_value = return_value
        path = '/drivers/%s/vendor_passthru/methods' % self.d1

        data = self.get_json(path)
        self.assertEqual(return_value, data)
        get_methods_mock.assert_called_once_with(mock.ANY, self.d1,
                                                 topic=mock.ANY)

        # Now let's test the cache: Reset the mock
        get_methods_mock.reset_mock()

        # Call it again
        data = self.get_json(path)
        self.assertEqual(return_value, data)
        # Assert RPC method wasn't called this time
        self.assertFalse(get_methods_mock.called)


@mock.patch.object(rpcapi.ConductorAPI, 'get_driver_properties')
@mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for_driver')
class TestDriverProperties(base.FunctionalTest):

    def test_driver_properties_fake(self, mock_topic, mock_properties):
        # Can get driver properties for fake driver.
        driver._DRIVER_PROPERTIES = {}
        driver_name = 'fake'
        mock_topic.return_value = 'fake_topic'
        mock_properties.return_value = {'prop1': 'Property 1. Required.'}
        data = self.get_json('/drivers/%s/properties' % driver_name)
        self.assertEqual(mock_properties.return_value, data)
        mock_topic.assert_called_once_with(driver_name)
        mock_properties.assert_called_once_with(mock.ANY, driver_name,
                                                topic=mock_topic.return_value)
        self.assertEqual(mock_properties.return_value,
                         driver._DRIVER_PROPERTIES[driver_name])

    def test_driver_properties_cached(self, mock_topic, mock_properties):
        # only one RPC-conductor call will be made and the info cached
        # for subsequent requests
        driver._DRIVER_PROPERTIES = {}
        driver_name = 'fake'
        mock_topic.return_value = 'fake_topic'
        mock_properties.return_value = {'prop1': 'Property 1. Required.'}
        data = self.get_json('/drivers/%s/properties' % driver_name)
        data = self.get_json('/drivers/%s/properties' % driver_name)
        data = self.get_json('/drivers/%s/properties' % driver_name)
        self.assertEqual(mock_properties.return_value, data)
        mock_topic.assert_called_once_with(driver_name)
        mock_properties.assert_called_once_with(mock.ANY, driver_name,
                                                topic=mock_topic.return_value)
        self.assertEqual(mock_properties.return_value,
                         driver._DRIVER_PROPERTIES[driver_name])

    def test_driver_properties_invalid_driver_name(self, mock_topic,
                                                   mock_properties):
        # Cannot get driver properties for an invalid driver; no RPC topic
        # exists for it.
        driver._DRIVER_PROPERTIES = {}
        driver_name = 'bad_driver'
        mock_topic.side_effect = exception.DriverNotFound(
            driver_name=driver_name)
        mock_properties.return_value = {'prop1': 'Property 1. Required.'}
        ret = self.get_json('/drivers/%s/properties' % driver_name,
                            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, ret.status_int)
        mock_topic.assert_called_once_with(driver_name)
        self.assertFalse(mock_properties.called)

    def test_driver_properties_cannot_load(self, mock_topic, mock_properties):
        # Cannot get driver properties for the driver. Although an RPC topic
        # exists for it, the conductor wasn't able to load it.
        driver._DRIVER_PROPERTIES = {}
        driver_name = 'driver'
        mock_topic.return_value = 'driver_topic'
        mock_properties.side_effect = exception.DriverNotFound(
            driver_name=driver_name)
        ret = self.get_json('/drivers/%s/properties' % driver_name,
                            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, ret.status_int)
        mock_topic.assert_called_once_with(driver_name)
        mock_properties.assert_called_once_with(mock.ANY, driver_name,
                                                topic=mock_topic.return_value)
