# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

import re

import mock
import six
import webtest
import wsme

from ironic.api.controllers.v1 import types
from ironic.common import exception
from ironic.common import utils
from ironic.tests.api import base


class TestMacAddressType(base.FunctionalTest):

    def test_valid_mac_addr(self):
        test_mac = 'aa:bb:cc:11:22:33'
        with mock.patch.object(utils, 'validate_and_normalize_mac') as m_mock:
            types.MacAddressType.validate(test_mac)
            m_mock.assert_called_once_with(test_mac)

    def test_invalid_mac_addr(self):
        self.assertRaises(exception.InvalidMAC,
                          types.MacAddressType.validate, 'invalid-mac')


class TestUuidType(base.FunctionalTest):

    def test_valid_uuid(self):
        test_uuid = '1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'
        with mock.patch.object(utils, 'is_uuid_like') as uuid_mock:
            types.UuidType.validate(test_uuid)
            uuid_mock.assert_called_once_with(test_uuid)

    def test_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID,
                          types.UuidType.validate, 'invalid-uuid')


# TODO(lucasagomes): The tests for the StringType class were ported from
#                    WSME trunk remove it on the next WSME release (> 0.5b6)
class TestStringType(base.FunctionalTest):

    def test_validate_string_type(self):
        v = types.StringType(min_length=1, max_length=10,
                             pattern='^[a-zA-Z0-9]*$')
        v.validate('1')
        v.validate('12345')
        v.validate('1234567890')
        self.assertRaises(ValueError, v.validate, '')
        self.assertRaises(ValueError, v.validate, '12345678901')

        # Test a pattern validation
        v.validate('a')
        v.validate('A')
        self.assertRaises(ValueError, v.validate, '_')

    def test_validate_string_type_precompile(self):
        precompile = re.compile('^[a-zA-Z0-9]*$')
        v = types.StringType(min_length=1, max_length=10,
                             pattern=precompile)

        # Test a pattern validation
        v.validate('a')
        v.validate('A')
        self.assertRaises(ValueError, v.validate, '_')


class MyPatchType(types.JsonPatchType):
    """Helper class for TestJsonPatchType tests."""

    @staticmethod
    def mandatory_attrs():
        return ['/mandatory']

    @staticmethod
    def internal_attrs():
        return ['/internal']


class MyRoot(wsme.WSRoot):
    """Helper class for TestJsonPatchType tests."""

    @wsme.expose([wsme.types.text], body=[MyPatchType])
    @wsme.validate([MyPatchType])
    def test(self, patch):
        return patch


class TestJsonPatchType(base.FunctionalTest):

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
                         {'path': '/foo', 'op': 'replace', 'value': 'bar'}]
        ret = self._patch_json(valid_patches, False)
        self.assertEqual(200, ret.status_int)
        self.assertEqual(sorted(valid_patches), sorted(ret.json))

    def test_cannot_update_internal_attr(self):
        patch = [{'path': '/internal', 'op': 'replace', 'value': 'foo'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_mandatory_attr(self):
        patch = [{'op': 'replace', 'path': '/mandatory', 'value': 'foo'}]
        ret = self._patch_json(patch, False)
        self.assertEqual(200, ret.status_int)
        self.assertEqual(patch, ret.json)

    def test_cannot_remove_mandatory_attr(self):
        patch = [{'op': 'remove', 'path': '/mandatory'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_missing_required_fields_path(self):
        missing_path = [{'op': 'remove'}]
        ret = self._patch_json(missing_path, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_missing_required_fields_op(self):
        missing_op = [{'path': '/foo'}]
        ret = self._patch_json(missing_op, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_invalid_op(self):
        patch = [{'path': '/foo', 'op': 'invalid'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_invalid_path(self):
        patch = [{'path': 'invalid-path', 'op': 'remove'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_add_to_root(self):
        patch = [{'path': '/foo', 'op': 'add', 'value': 'bar'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_add_with_no_value(self):
        patch = [{'path': '/extra/foo', 'op': 'add'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])

    def test_cannot_replace_with_no_value(self):
        patch = [{'path': '/foo', 'op': 'replace'}]
        ret = self._patch_json(patch, True)
        self.assertEqual(400, ret.status_int)
        self.assertTrue(ret.json['faultstring'])


class TestMultiType(base.FunctionalTest):

    def test_valid_values(self):
        vt = types.MultiType(wsme.types.text, six.integer_types)
        value = vt.validate("hello")
        self.assertEqual("hello", value)
        value = vt.validate(10)
        self.assertEqual(10, value)

    def test_invalid_values(self):
        vt = types.MultiType(wsme.types.text, six.integer_types)
        self.assertRaises(ValueError, vt.validate, 0.10)
        self.assertRaises(ValueError, vt.validate, object())
