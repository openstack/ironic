# coding: utf-8
#
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

from http import client as http_client
import platform

import mock
import webtest
import wsme

from ironic.api.controllers.v1 import types
from ironic.common import exception
from ironic.common import utils
from ironic.tests import base
from ironic.tests.unit.api.utils import fake_event_validator


class TestMacAddressType(base.TestCase):

    def test_valid_mac_addr(self):
        test_mac = 'aa:bb:cc:11:22:33'
        with mock.patch.object(utils, 'validate_and_normalize_mac') as m_mock:
            types.MacAddressType.validate(test_mac)
            m_mock.assert_called_once_with(test_mac)

    def test_invalid_mac_addr(self):
        self.assertRaises(exception.InvalidMAC,
                          types.MacAddressType.validate, 'invalid-mac')


class TestUuidType(base.TestCase):

    def test_valid_uuid(self):
        test_uuid = '1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'
        self.assertEqual(test_uuid, types.UuidType.validate(test_uuid))

    def test_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID,
                          types.UuidType.validate, 'invalid-uuid')


@mock.patch("ironic.api.request")
class TestNameType(base.TestCase):

    def test_valid_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 10
        test_name = 'hal-9000'
        self.assertEqual(test_name, types.NameType.validate(test_name))

    def test_invalid_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 10
        self.assertRaises(exception.InvalidName,
                          types.NameType.validate, '-this is not valid-')


@mock.patch("ironic.api.request")
class TestUuidOrNameType(base.TestCase):

    def test_valid_uuid(self, mock_pecan_req):
        mock_pecan_req.version.minor = 10
        test_uuid = '1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'
        self.assertTrue(types.UuidOrNameType.validate(test_uuid))

    def test_valid_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 10
        test_name = 'dc16-database5'
        self.assertTrue(types.UuidOrNameType.validate(test_name))

    def test_invalid_uuid_or_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 10
        self.assertRaises(exception.InvalidUuidOrName,
                          types.UuidOrNameType.validate, 'inval#uuid%or*name')


class MyBaseType(object):
    """Helper class, patched by objects of type MyPatchType"""
    mandatory = wsme.wsattr(str, mandatory=True)


class MyPatchType(types.JsonPatchType):
    """Helper class for TestJsonPatchType tests."""
    _api_base = MyBaseType
    _extra_non_removable_attrs = {'/non_removable'}

    @staticmethod
    def internal_attrs():
        return ['/internal']


class MyRoot(wsme.WSRoot):
    """Helper class for TestJsonPatchType tests."""

    @wsme.expose([str], body=[MyPatchType])
    @wsme.validate([MyPatchType])
    def test(self, patch):
        return patch


class TestJsonPatchType(base.TestCase):

    @mock.patch.object(platform, '_syscmd_uname', lambda *x: '')
    def setUp(self):
        super(TestJsonPatchType, self).setUp()
        self.app = webtest.TestApp(MyRoot(['restjson']).wsgiapp())

    def _patch_json(self, params, expect_errors=False):
        return self.app.patch_json('/test', params=params,
                                   headers={'Accept': 'application/json'},
                                   expect_errors=expect_errors)

    def test_valid_patches(self):
        valid_patches = [{'path': '/extra/foo', 'op': 'remove'},
                         {'path': '/extra/foo', 'op': 'add', 'value': 'bar'},
                         {'path': '/str', 'op': 'replace', 'value': 'bar'},
                         {'path': '/bool', 'op': 'add', 'value': True},
                         {'path': '/int', 'op': 'add', 'value': 1},
                         {'path': '/float', 'op': 'add', 'value': 0.123},
                         {'path': '/list', 'op': 'add', 'value': [1, 2]},
                         {'path': '/none', 'op': 'add', 'value': None},
                         {'path': '/empty_dict', 'op': 'add', 'value': {}},
                         {'path': '/empty_list', 'op': 'add', 'value': []},
                         {'path': '/dict', 'op': 'add',
                          'value': {'cat': 'meow'}}]
        ret = self._patch_json(valid_patches, False)
        self.assertEqual(http_client.OK, ret.status_int)
        self.assertItemsEqual(valid_patches, ret.json)

    def test_cannot_update_internal_attr(self):
        patch = [{'path': '/internal', 'op': 'replace', 'value': 'foo'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_update_internal_dict_attr(self):
        patch = [{'path': '/internal/test', 'op': 'replace',
                 'value': 'foo'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_mandatory_attr(self):
        patch = [{'op': 'replace', 'path': '/mandatory', 'value': 'foo'}]
        ret = self._patch_json(patch, False)
        self.assertEqual(http_client.OK, ret.status_int)
        self.assertEqual(patch, ret.json)

    def test_cannot_remove_mandatory_attr(self):
        patch = [{'op': 'remove', 'path': '/mandatory'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_remove_extra_non_removable_attr(self):
        patch = [{'op': 'remove', 'path': '/non_removable'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_missing_required_fields_path(self):
        missing_path = [{'op': 'remove'}]
        ret = self._patch_json(missing_path, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_missing_required_fields_op(self):
        missing_op = [{'path': '/foo'}]
        ret = self._patch_json(missing_op, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_invalid_op(self):
        patch = [{'path': '/foo', 'op': 'invalid'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_invalid_path(self):
        patch = [{'path': 'invalid-path', 'op': 'remove'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_add_with_no_value(self):
        patch = [{'path': '/extra/foo', 'op': 'add'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_replace_with_no_value(self):
        patch = [{'path': '/foo', 'op': 'replace'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_int)
        self.assertTrue(ret.json['faultstring'])


class TestBooleanType(base.TestCase):

    def test_valid_true_values(self):
        v = types.BooleanType()
        self.assertTrue(v.validate("true"))
        self.assertTrue(v.validate("TRUE"))
        self.assertTrue(v.validate("True"))
        self.assertTrue(v.validate("t"))
        self.assertTrue(v.validate("1"))
        self.assertTrue(v.validate("y"))
        self.assertTrue(v.validate("yes"))
        self.assertTrue(v.validate("on"))

    def test_valid_false_values(self):
        v = types.BooleanType()
        self.assertFalse(v.validate("false"))
        self.assertFalse(v.validate("FALSE"))
        self.assertFalse(v.validate("False"))
        self.assertFalse(v.validate("f"))
        self.assertFalse(v.validate("0"))
        self.assertFalse(v.validate("n"))
        self.assertFalse(v.validate("no"))
        self.assertFalse(v.validate("off"))

    def test_invalid_value(self):
        v = types.BooleanType()
        self.assertRaises(exception.Invalid, v.validate, "invalid-value")
        self.assertRaises(exception.Invalid, v.validate, "01")


class TestJsonType(base.TestCase):

    def test_valid_values(self):
        vt = types.jsontype
        value = vt.validate("hello")
        self.assertEqual("hello", value)
        value = vt.validate(10)
        self.assertEqual(10, value)
        value = vt.validate(0.123)
        self.assertEqual(0.123, value)
        value = vt.validate(True)
        self.assertTrue(value)
        value = vt.validate([1, 2, 3])
        self.assertEqual([1, 2, 3], value)
        value = vt.validate({'foo': 'bar'})
        self.assertEqual({'foo': 'bar'}, value)
        value = vt.validate(None)
        self.assertIsNone(value)

    def test_invalid_values(self):
        vt = types.jsontype
        self.assertRaises(exception.Invalid, vt.validate, object())

    def test_apimultitype_tostring(self):
        vts = str(types.jsontype)
        self.assertIn(str(str), vts)
        self.assertIn(str(int), vts)
        self.assertIn(str(float), vts)
        self.assertIn(str(types.BooleanType), vts)
        self.assertIn(str(list), vts)
        self.assertIn(str(dict), vts)
        self.assertIn(str(None), vts)


class TestListType(base.TestCase):

    def test_list_type(self):
        v = types.ListType()
        self.assertEqual(['foo', 'bar'], v.validate('foo,bar'))
        self.assertNotEqual(['bar', 'foo'], v.validate('foo,bar'))

        self.assertEqual(['cat', 'meow'], v.validate("cat  ,  meow"))
        self.assertEqual(['spongebob', 'squarepants'],
                         v.validate("SpongeBob,SquarePants"))
        self.assertEqual(['foo', 'bar'], v.validate("foo, ,,bar"))
        self.assertEqual(['foo', 'bar'], v.validate("foo,foo,foo,bar"))
        self.assertIsInstance(v.validate('foo,bar'), list)


class TestLocalLinkConnectionType(base.TestCase):

    def test_local_link_connection_type(self):
        v = types.locallinkconnectiontype
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'value2',
                 'switch_info': 'value3'}
        self.assertItemsEqual(value, v.validate(value))

    def test_local_link_connection_type_datapath_id(self):
        v = types.locallinkconnectiontype
        value = {'switch_id': '0000000000000000',
                 'port_id': 'value2',
                 'switch_info': 'value3'}
        self.assertItemsEqual(value,
                              v.validate(value))

    def test_local_link_connection_type_not_mac_or_datapath_id(self):
        v = types.locallinkconnectiontype
        value = {'switch_id': 'badid',
                 'port_id': 'value2',
                 'switch_info': 'value3'}
        self.assertRaises(exception.InvalidSwitchID, v.validate, value)

    def test_local_link_connection_type_invalid_key(self):
        v = types.locallinkconnectiontype
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'value2',
                 'switch_info': 'value3',
                 'invalid_key': 'value'}
        self.assertRaisesRegex(exception.Invalid, 'are invalid keys',
                               v.validate, value)

    def test_local_link_connection_type_missing_local_link_mandatory_key(self):
        v = types.locallinkconnectiontype
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'switch_info': 'value3'}
        self.assertRaisesRegex(exception.Invalid, 'Missing mandatory',
                               v.validate, value)

    def test_local_link_connection_type_local_link_keys_mandatory(self):
        v = types.locallinkconnectiontype
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'value2'}
        self.assertItemsEqual(value, v.validate(value))

    def test_local_link_connection_type_empty_value(self):
        v = types.locallinkconnectiontype
        value = {}
        self.assertItemsEqual(value, v.validate(value))

    def test_local_link_connection_type_smart_nic_keys_mandatory(self):
        v = types.locallinkconnectiontype
        value = {'port_id': 'rep0-0',
                 'hostname': 'hostname'}
        self.assertTrue(v.validate_for_smart_nic(value))
        self.assertTrue(v.validate(value))

    def test_local_link_connection_type_smart_nic_keys_with_optional(self):
        v = types.locallinkconnectiontype
        value = {'port_id': 'rep0-0',
                 'hostname': 'hostname',
                 'switch_id': '0a:1b:2c:3d:4e:5f',
                 'switch_info': 'sw_info'}
        self.assertTrue(v.validate_for_smart_nic(value))
        self.assertTrue(v.validate(value))

    def test_local_link_connection_type_smart_nic_keys_hostname_missing(self):
        v = types.locallinkconnectiontype
        value = {'port_id': 'rep0-0'}
        self.assertFalse(v.validate_for_smart_nic(value))
        self.assertRaises(exception.Invalid, v.validate, value)

    def test_local_link_connection_type_smart_nic_keys_port_id_missing(self):
        v = types.locallinkconnectiontype
        value = {'hostname': 'hostname'}
        self.assertFalse(v.validate_for_smart_nic(value))
        self.assertRaises(exception.Invalid, v.validate, value)

    def test_local_link_connection_net_type_unmanaged(self):
        v = types.locallinkconnectiontype
        value = {'network_type': 'unmanaged'}
        self.assertItemsEqual(value, v.validate(value))

    def test_local_link_connection_net_type_unmanaged_combine_ok(self):
        v = types.locallinkconnectiontype
        value = {'network_type': 'unmanaged',
                 'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'rep0-0'}
        self.assertItemsEqual(value, v.validate(value))

    def test_local_link_connection_net_type_invalid(self):
        v = types.locallinkconnectiontype
        value = {'network_type': 'invalid'}
        self.assertRaises(exception.Invalid, v.validate, value)


@mock.patch("ironic.api.request", mock.Mock(version=mock.Mock(minor=10)))
class TestVifType(base.TestCase):

    def test_vif_type(self):
        v = types.viftype
        value = {'id': 'foo'}
        self.assertItemsEqual(value, v.validate(value))

    def test_vif_type_missing_mandatory_key(self):
        v = types.viftype
        value = {'foo': 'bar'}
        self.assertRaisesRegex(exception.Invalid, 'Missing mandatory',
                               v.validate, value)

    def test_vif_type_optional_key(self):
        v = types.viftype
        value = {'id': 'foo', 'misc': 'something'}
        self.assertItemsEqual(value, v.frombasetype(value))

    def test_vif_type_bad_id(self):
        v = types.viftype
        self.assertRaises(exception.InvalidUuidOrName,
                          v.frombasetype, {'id': 5678})


class TestEventType(base.TestCase):

    def setUp(self):
        super(TestEventType, self).setUp()
        self.v = types.eventtype

    @mock.patch.object(types.EventType, 'event_validators',
                       {'valid.event': fake_event_validator})
    @mock.patch.object(types.EventType, 'valid_events', set(['valid.event']))
    def test_simple_event_type(self):
        value = {'event': 'valid.event'}
        self.assertItemsEqual(value, self.v.validate(value))

    @mock.patch.object(types.EventType, 'valid_events', set(['valid.event']))
    def test_invalid_event_type(self):
        value = {'event': 'invalid.event'}
        self.assertRaisesRegex(exception.Invalid,
                               'invalid.event is not one of valid events:',
                               self.v.validate, value)

    def test_event_missing_madatory_field(self):
        value = {'invalid': 'invalid'}
        self.assertRaisesRegex(exception.Invalid, 'Missing mandatory keys:',
                               self.v.validate, value)

    def test_network_port_event(self):
        value = {'event': 'network.bind_port',
                 'port_id': '11111111-aaaa-bbbb-cccc-555555555555',
                 'mac_address': 'de:ad:ca:fe:ba:be',
                 'status': 'ACTIVE',
                 'device_id': '22222222-aaaa-bbbb-cccc-555555555555',
                 'binding:host_id': '22222222-aaaa-bbbb-cccc-555555555555',
                 'binding:vnic_type': 'baremetal'
                 }
        self.assertItemsEqual(value, self.v.validate(value))

    def test_invalid_mac_network_port_event(self):
        value = {'event': 'network.bind_port',
                 'port_id': '11111111-aaaa-bbbb-cccc-555555555555',
                 'mac_address': 'INVALID_MAC_ADDRESS',
                 'status': 'ACTIVE',
                 'device_id': '22222222-aaaa-bbbb-cccc-555555555555',
                 'binding:host_id': '22222222-aaaa-bbbb-cccc-555555555555',
                 'binding:vnic_type': 'baremetal'
                 }
        self.assertRaisesRegex(exception.Invalid,
                               'Event validation failure for mac_address.',
                               self.v.validate, value)

    def test_missing_mandatory_fields_network_port_event(self):
        value = {'event': 'network.bind_port',
                 'device_id': '22222222-aaaa-bbbb-cccc-555555555555',
                 'binding:host_id': '22222222-aaaa-bbbb-cccc-555555555555',
                 'binding:vnic_type': 'baremetal'
                 }
        self.assertRaisesRegex(exception.Invalid, 'Missing mandatory keys:',
                               self.v.validate, value)
