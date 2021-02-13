# -*- encoding: utf-8 -*-
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

import datetime
from http import client as http_client
import io
from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic import api
from ironic.api.controllers.v1 import node as api_node
from ironic.api.controllers.v1 import utils
from ironic.common import context as ironic_context
from ironic.common import exception
from ironic.common import policy
from ironic.common import states
from ironic import objects
from ironic.tests import base
from ironic.tests.unit.api import utils as test_api_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class TestApiUtils(base.TestCase):

    def test_validate_limit(self):
        limit = utils.validate_limit(10)
        self.assertEqual(10, limit)

        # max limit
        limit = utils.validate_limit(999999999)
        self.assertEqual(CONF.api.max_limit, limit)

        # negative
        self.assertRaises(exception.ClientSideError, utils.validate_limit, -1)

        # zero
        self.assertRaises(exception.ClientSideError, utils.validate_limit, 0)

    def test_validate_sort_dir(self):
        sort_dir = utils.validate_sort_dir('asc')
        self.assertEqual('asc', sort_dir)

        # invalid sort_dir parameter
        self.assertRaises(exception.ClientSideError,
                          utils.validate_sort_dir,
                          'fake-sort')

    def test_apply_jsonpatch(self):
        doc = {"foo": {"bar": "baz"}}
        patch = [{"op": "add", "path": "/foo/answer", "value": 42}]
        result = utils.apply_jsonpatch(doc, patch)
        expected = {"foo": {"bar": "baz", "answer": 42}}
        self.assertEqual(expected, result)

    def test_apply_jsonpatch_no_add_root_attr(self):
        doc = {}
        patch = [{"op": "add", "path": "/foo", "value": 42}]
        self.assertRaisesRegex(exception.ClientSideError,
                               "Adding a new attribute",
                               utils.apply_jsonpatch, doc, patch)

    def test_apply_jsonpatch_remove_non_existent(self):
        # Raises a KeyError.
        doc = {}
        patch = [{"op": "remove", "path": "/foo"}]
        self.assertRaises(exception.PatchError,
                          utils.apply_jsonpatch, doc, patch)

    def test_apply_jsonpatch_replace_non_existent_list_item(self):
        # Raises an IndexError.
        doc = []
        patch = [{"op": "replace", "path": "/0", "value": 42}]
        self.assertRaises(exception.PatchError,
                          utils.apply_jsonpatch, doc, patch)

    def test_get_patch_values_no_path(self):
        patch = [{'path': '/name', 'op': 'update', 'value': 'node-0'}]
        path = '/invalid'
        values = utils.get_patch_values(patch, path)
        self.assertEqual([], values)

    def test_get_patch_values_remove(self):
        patch = [{'path': '/name', 'op': 'remove'}]
        path = '/name'
        values = utils.get_patch_values(patch, path)
        self.assertEqual([], values)

    def test_get_patch_values_success(self):
        patch = [{'path': '/name', 'op': 'replace', 'value': 'node-x'}]
        path = '/name'
        values = utils.get_patch_values(patch, path)
        self.assertEqual(['node-x'], values)

    def test_get_patch_values_multiple_success(self):
        patch = [{'path': '/name', 'op': 'replace', 'value': 'node-x'},
                 {'path': '/name', 'op': 'replace', 'value': 'node-y'}]
        path = '/name'
        values = utils.get_patch_values(patch, path)
        self.assertEqual(['node-x', 'node-y'], values)

    def test_is_path_removed_success(self):
        patch = [{'path': '/name', 'op': 'remove'}]
        path = '/name'
        value = utils.is_path_removed(patch, path)
        self.assertTrue(value)

    def test_is_path_removed_subpath_success(self):
        patch = [{'path': '/local_link_connection/switch_id', 'op': 'remove'}]
        path = '/local_link_connection'
        value = utils.is_path_removed(patch, path)
        self.assertTrue(value)

    def test_is_path_removed_similar_subpath(self):
        patch = [{'path': '/local_link_connection_info/switch_id',
                  'op': 'remove'}]
        path = '/local_link_connection'
        value = utils.is_path_removed(patch, path)
        self.assertFalse(value)

    def test_is_path_removed_replace(self):
        patch = [{'path': '/name', 'op': 'replace', 'value': 'node-x'}]
        path = '/name'
        value = utils.is_path_removed(patch, path)
        self.assertFalse(value)

    def test_is_path_updated_success(self):
        patch = [{'path': '/name', 'op': 'remove'}]
        path = '/name'
        value = utils.is_path_updated(patch, path)
        self.assertTrue(value)

    def test_is_path_updated_subpath_success(self):
        patch = [{'path': '/properties/switch_id', 'op': 'add', 'value': 'id'}]
        path = '/properties'
        value = utils.is_path_updated(patch, path)
        self.assertTrue(value)

    def test_is_path_updated_similar_subpath(self):
        patch = [{'path': '/properties2/switch_id',
                  'op': 'replace', 'value': 'spam'}]
        path = '/properties'
        value = utils.is_path_updated(patch, path)
        self.assertFalse(value)

    def test_check_for_invalid_fields(self):
        requested = ['field_1', 'field_3']
        supported = ['field_1', 'field_2', 'field_3']
        utils.check_for_invalid_fields(requested, supported)

    def test_check_for_invalid_fields_fail(self):
        requested = ['field_1', 'field_4']
        supported = ['field_1', 'field_2', 'field_3']
        self.assertRaises(exception.InvalidParameterValue,
                          utils.check_for_invalid_fields,
                          requested, supported)

    def test_patch_update_changed_fields(self):
        schema = {
            'properties': {
                'one': {},
                'two': {},
                'three': {},
                'four': {},
                'five_uuid': {},
            }
        }
        fields = [
            'one',
            'two',
            'three',
            'four',
            'five_id'
        ]

        def rpc_object():
            obj = mock.MagicMock()
            items = {
                'one': 1,
                'two': 'ii',
                'three': None,
                'four': [1, 2, 3, 4],
                'five_id': 123
            }
            obj.__getitem__.side_effect = items.__getitem__
            obj.__contains__.side_effect = items.__contains__
            return obj

        # test no change
        o = rpc_object()
        utils.patch_update_changed_fields({
            'one': 1,
            'two': 'ii',
            'three': None,
            'four': [1, 2, 3, 4],
        }, o, fields, schema, id_map={'five_id': 123})
        o.__setitem__.assert_not_called()

        # test everything changes, and id_map values override from_dict values
        o = rpc_object()
        utils.patch_update_changed_fields({
            'one': 2,
            'two': 'iii',
            'three': '',
            'four': [2, 3],
        }, o, fields, schema, id_map={'four': [4], 'five_id': 456})
        o.__setitem__.assert_has_calls([
            mock.call('one', 2),
            mock.call('two', 'iii'),
            mock.call('three', ''),
            mock.call('four', [4]),
            mock.call('five_id', 456)
        ])

        # test None fields from None values and missing keys
        # also five_id is untouched with no id_map
        o = rpc_object()
        utils.patch_update_changed_fields({
            'two': None,
        }, o, fields, schema)
        o.__setitem__.assert_has_calls([
            mock.call('two', None),
        ])

        # test fields not in the schema are untouched
        fields = [
            'six',
            'seven',
            'eight'
        ]
        o = rpc_object()
        utils.patch_update_changed_fields({
            'six': 2,
            'seven': 'iii',
            'eight': '',
        }, o, fields, schema)
        o.__setitem__.assert_not_called()

    def test_patched_validate_with_schema(self):
        schema = {
            'properties': {
                'one': {'type': 'string'},
                'two': {'type': 'integer'},
                'three': {'type': 'boolean'},
            }
        }

        # test non-schema fields removed
        pd = {
            'one': 'one',
            'two': 2,
            'three': True,
            'four': 4,
            'five': 'five'
        }
        utils.patched_validate_with_schema(pd, schema)
        self.assertEqual({
            'one': 'one',
            'two': 2,
            'three': True,
        }, pd)

        # test fails schema validation
        pd = {
            'one': 1,
            'two': 2,
            'three': False
        }
        e = self.assertRaises(exception.InvalidParameterValue,
                              utils.patched_validate_with_schema, pd, schema)
        self.assertIn("1 is not of type 'string'", str(e))

        # test fails custom validation
        def validate(name, value):
            raise exception.InvalidParameterValue('big ouch')

        pd = {
            'one': 'one',
            'two': 2,
            'three': False
        }
        e = self.assertRaises(exception.InvalidParameterValue,
                              utils.patched_validate_with_schema, pd, schema,
                              validate)
        self.assertIn("big ouch", str(e))

    def test_patch_validate_allowed_fields(self):
        allowed_fields = ['one', 'two', 'three']

        # patch all
        self.assertEqual(
            {'one', 'two', 'three'},
            utils.patch_validate_allowed_fields([
                {'path': '/one'},
                {'path': '/two'},
                {'path': '/three/four'},
            ], allowed_fields))

        # patch one
        self.assertEqual(
            {'one'},
            utils.patch_validate_allowed_fields([
                {'path': '/one'},
            ], allowed_fields))

        # patch invalid field
        e = self.assertRaises(
            exception.Invalid,
            utils.patch_validate_allowed_fields,
            [{'path': '/four'}],
            allowed_fields)
        self.assertIn("Cannot patch /four. "
                      "Only the following can be updated: "
                      "one, two, three", str(e))

    @mock.patch.object(api, 'request', autospec=False)
    def test_sanitize_dict(self, mock_req):
        mock_req.public_url = 'http://192.0.2.1:5050'

        node = obj_utils.get_test_node(
            self.context,
            created_at=datetime.datetime(2000, 1, 1, 0, 0),
            updated_at=datetime.datetime(2001, 1, 1, 0, 0),
            inspection_started_at=datetime.datetime(2002, 1, 1, 0, 0),
            console_enabled=True,
            tags=['one', 'two', 'three'])

        expected_links = [{
            'href': 'http://192.0.2.1:5050/v1/node/'
                    '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'rel': 'self'
        }, {
            'href': 'http://192.0.2.1:5050/node/'
                    '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'rel': 'bookmark'
        }]

        # all fields
        node_dict = utils.object_to_dict(
            node,
            link_resource='node',
        )
        utils.sanitize_dict(node_dict, None)
        self.assertEqual({
            'created_at': '2000-01-01T00:00:00+00:00',
            'links': expected_links,
            'updated_at': '2001-01-01T00:00:00+00:00',
            'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        }, node_dict)

        # some fields
        node_dict = utils.object_to_dict(
            node,
            link_resource='node',
        )
        utils.sanitize_dict(node_dict, ['uuid', 'created_at'])
        self.assertEqual({
            'created_at': '2000-01-01T00:00:00+00:00',
            'links': expected_links,
            'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        }, node_dict)

        # no fields
        node_dict = utils.object_to_dict(
            node,
            link_resource='node',
        )
        utils.sanitize_dict(node_dict, [])
        self.assertEqual({
            'links': expected_links,
        }, node_dict)


@mock.patch.object(api, 'request', spec_set=['version'])
class TestCheckAllowFields(base.TestCase):

    def test_check_allow_specify_fields(self, mock_request):
        mock_request.version.minor = 8
        self.assertIsNone(utils.check_allow_specify_fields(['foo']))

    def test_check_allow_specify_fields_fail(self, mock_request):
        mock_request.version.minor = 7
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_specify_fields, ['foo'])

    def test_check_allowed_fields_network_interface(self, mock_request):
        mock_request.version.minor = 20
        self.assertIsNone(
            utils.check_allowed_fields(['network_interface']))

    def test_check_allowed_fields_network_interface_fail(self, mock_request):
        mock_request.version.minor = 19
        self.assertRaises(
            exception.NotAcceptable,
            utils.check_allowed_fields,
            ['network_interface'])

    def test_check_allowed_fields_resource_class(self, mock_request):
        mock_request.version.minor = 21
        self.assertIsNone(
            utils.check_allowed_fields(['resource_class']))

    def test_check_allowed_fields_resource_class_fail(self, mock_request):
        mock_request.version.minor = 20
        self.assertRaises(
            exception.NotAcceptable,
            utils.check_allowed_fields,
            ['resource_class'])

    def test_check_allowed_fields_rescue_interface_fail(self, mock_request):
        mock_request.version.minor = 31
        self.assertRaises(
            exception.NotAcceptable,
            utils.check_allowed_fields,
            ['rescue_interface'])

    def test_check_allowed_portgroup_fields_mode_properties(self,
                                                            mock_request):
        mock_request.version.minor = 26
        self.assertIsNone(
            utils.check_allowed_portgroup_fields(['mode']))
        self.assertIsNone(
            utils.check_allowed_portgroup_fields(['properties']))

    def test_check_allowed_portgroup_fields_mode_properties_fail(self,
                                                                 mock_request):
        mock_request.version.minor = 25
        self.assertRaises(
            exception.NotAcceptable,
            utils.check_allowed_portgroup_fields,
            ['mode'])
        self.assertRaises(
            exception.NotAcceptable,
            utils.check_allowed_portgroup_fields,
            ['properties'])

    def test_check_allow_specify_driver(self, mock_request):
        mock_request.version.minor = 16
        self.assertIsNone(utils.check_allow_specify_driver(['fake']))

    def test_check_allow_specify_driver_fail(self, mock_request):
        mock_request.version.minor = 15
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_specify_driver, ['fake'])

    def test_check_allow_specify_resource_class(self, mock_request):
        mock_request.version.minor = 21
        self.assertIsNone(utils.check_allow_specify_resource_class(['foo']))

    def test_check_allow_specify_resource_class_fail(self, mock_request):
        mock_request.version.minor = 20
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_specify_resource_class, ['foo'])

    def test_check_allow_filter_driver_type(self, mock_request):
        mock_request.version.minor = 30
        self.assertIsNone(utils.check_allow_filter_driver_type('classic'))

    def test_check_allow_filter_driver_type_none(self, mock_request):
        mock_request.version.minor = 29
        self.assertIsNone(utils.check_allow_filter_driver_type(None))

    def test_check_allow_filter_driver_type_fail(self, mock_request):
        mock_request.version.minor = 29
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_filter_driver_type, 'classic')

    def test_check_allow_filter_by_conductor_group(self, mock_request):
        mock_request.version.minor = 46
        self.assertIsNone(utils.check_allow_filter_by_conductor_group('foo'))

    def test_check_allow_filter_by_conductor_group_none(self, mock_request):
        mock_request.version.minor = 46
        self.assertIsNone(utils.check_allow_filter_by_conductor_group(None))

    def test_check_allow_filter_by_conductor_group_fail(self, mock_request):
        mock_request.version.minor = 45
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_filter_by_conductor_group, 'foo')

    def test_check_allow_driver_detail(self, mock_request):
        mock_request.version.minor = 30
        self.assertIsNone(utils.check_allow_driver_detail(True))

    def test_check_allow_driver_detail_false(self, mock_request):
        mock_request.version.minor = 30
        self.assertIsNone(utils.check_allow_driver_detail(False))

    def test_check_allow_driver_detail_none(self, mock_request):
        mock_request.version.minor = 29
        self.assertIsNone(utils.check_allow_driver_detail(None))

    def test_check_allow_driver_detail_fail(self, mock_request):
        mock_request.version.minor = 29
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_driver_detail, True)

    def test_check_allow_manage_verbs(self, mock_request):
        mock_request.version.minor = 4
        utils.check_allow_management_verbs('manage')

    def test_check_allow_manage_verbs_fail(self, mock_request):
        mock_request.version.minor = 3
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_management_verbs, 'manage')

    def test_check_allow_provide_verbs(self, mock_request):
        mock_request.version.minor = 4
        utils.check_allow_management_verbs('provide')

    def test_check_allow_provide_verbs_fail(self, mock_request):
        mock_request.version.minor = 3
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_management_verbs, 'provide')

    def test_check_allow_inspect_verbs(self, mock_request):
        mock_request.version.minor = 6
        utils.check_allow_management_verbs('inspect')

    def test_check_allow_inspect_verbs_fail(self, mock_request):
        mock_request.version.minor = 5
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_management_verbs, 'inspect')

    def test_check_allow_abort_verbs(self, mock_request):
        mock_request.version.minor = 13
        utils.check_allow_management_verbs('abort')

    def test_check_allow_abort_verbs_fail(self, mock_request):
        mock_request.version.minor = 12
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_management_verbs, 'abort')

    def test_check_allow_clean_verbs(self, mock_request):
        mock_request.version.minor = 15
        utils.check_allow_management_verbs('clean')

    def test_check_allow_clean_verbs_fail(self, mock_request):
        mock_request.version.minor = 14
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_management_verbs, 'clean')

    def test_check_allow_unknown_verbs(self, mock_request):
        utils.check_allow_management_verbs('rebuild')

    def test_allow_inject_nmi(self, mock_request):
        mock_request.version.minor = 29
        self.assertTrue(utils.allow_inject_nmi())
        mock_request.version.minor = 28
        self.assertFalse(utils.allow_inject_nmi())

    def test_allow_links_node_states_and_driver_properties(self, mock_request):
        mock_request.version.minor = 14
        self.assertTrue(utils.allow_links_node_states_and_driver_properties())
        mock_request.version.minor = 10
        self.assertFalse(utils.allow_links_node_states_and_driver_properties())

    def test_check_allow_adopt_verbs_fail(self, mock_request):
        mock_request.version.minor = 16
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_management_verbs, 'adopt')

    def test_check_allow_adopt_verbs(self, mock_request):
        mock_request.version.minor = 17
        utils.check_allow_management_verbs('adopt')

    def test_allow_port_internal_info(self, mock_request):
        mock_request.version.minor = 18
        self.assertTrue(utils.allow_port_internal_info())
        mock_request.version.minor = 17
        self.assertFalse(utils.allow_port_internal_info())

    def test_allow_port_advanced_net_fields(self, mock_request):
        mock_request.version.minor = 19
        self.assertTrue(utils.allow_port_advanced_net_fields())
        mock_request.version.minor = 18
        self.assertFalse(utils.allow_port_advanced_net_fields())

    def test_allow_ramdisk_endpoints(self, mock_request):
        mock_request.version.minor = 22
        self.assertTrue(utils.allow_ramdisk_endpoints())
        mock_request.version.minor = 21
        self.assertFalse(utils.allow_ramdisk_endpoints())

    def test_allow_portgroups(self, mock_request):
        mock_request.version.minor = 23
        self.assertTrue(utils.allow_portgroups())
        mock_request.version.minor = 22
        self.assertFalse(utils.allow_portgroups())

    def test_allow_portgroups_subcontrollers(self, mock_request):
        mock_request.version.minor = 24
        self.assertTrue(utils.allow_portgroups_subcontrollers())
        mock_request.version.minor = 23
        self.assertFalse(utils.allow_portgroups_subcontrollers())

    def test_allow_remove_chassis_uuid(self, mock_request):
        mock_request.version.minor = 25
        self.assertTrue(utils.allow_remove_chassis_uuid())
        mock_request.version.minor = 24
        self.assertFalse(utils.allow_remove_chassis_uuid())

    def test_allow_portgroup_mode_properties(self, mock_request):
        mock_request.version.minor = 26
        self.assertTrue(utils.allow_portgroup_mode_properties())
        mock_request.version.minor = 25
        self.assertFalse(utils.allow_portgroup_mode_properties())

    def test_allow_dynamic_drivers(self, mock_request):
        mock_request.version.minor = 30
        self.assertTrue(utils.allow_dynamic_drivers())
        mock_request.version.minor = 29
        self.assertFalse(utils.allow_dynamic_drivers())

    def test_allow_volume(self, mock_request):
        mock_request.version.minor = 32
        self.assertTrue(utils.allow_volume())
        mock_request.version.minor = 31
        self.assertFalse(utils.allow_volume())

    def test_allow_storage_interface(self, mock_request):
        mock_request.version.minor = 33
        self.assertTrue(utils.allow_storage_interface())
        mock_request.version.minor = 32
        self.assertFalse(utils.allow_storage_interface())

    def test_allow_traits(self, mock_request):
        mock_request.version.minor = 37
        self.assertTrue(utils.allow_traits())
        mock_request.version.minor = 36
        self.assertFalse(utils.allow_traits())

    @mock.patch.object(objects.Port, 'supports_physical_network',
                       autospec=True)
    def test_allow_port_physical_network_no_pin(self, mock_spn, mock_request):
        mock_spn.return_value = True
        mock_request.version.minor = 34
        self.assertTrue(utils.allow_port_physical_network())
        mock_request.version.minor = 33
        self.assertFalse(utils.allow_port_physical_network())

    @mock.patch.object(objects.Port, 'supports_physical_network',
                       autospec=True)
    def test_allow_port_physical_network_pin(self, mock_spn, mock_request):
        mock_spn.return_value = False
        mock_request.version.minor = 34
        self.assertFalse(utils.allow_port_physical_network())
        mock_request.version.minor = 33
        self.assertFalse(utils.allow_port_physical_network())

    def test_allow_node_rebuild_with_configdrive(self, mock_request):
        mock_request.version.minor = 35
        self.assertTrue(utils.allow_node_rebuild_with_configdrive())
        mock_request.version.minor = 34
        self.assertFalse(utils.allow_node_rebuild_with_configdrive())

    def test_allow_configdrive_vendor_data(self, mock_request):
        mock_request.version.minor = 59
        self.assertTrue(utils.allow_configdrive_vendor_data())
        mock_request.version.minor = 58
        self.assertFalse(utils.allow_configdrive_vendor_data())

    def test_check_allow_configdrive_fails(self, mock_request):
        mock_request.version.minor = 35
        self.assertRaises(exception.ClientSideError,
                          utils.check_allow_configdrive, states.DELETED,
                          "abcd")
        self.assertRaises(exception.ClientSideError,
                          utils.check_allow_configdrive, states.ACTIVE,
                          {'meta_data': {}})
        mock_request.version.minor = 34
        self.assertRaises(exception.ClientSideError,
                          utils.check_allow_configdrive, states.REBUILD,
                          "abcd")

    def test_check_allow_configdrive(self, mock_request):
        mock_request.version.minor = 35
        utils.check_allow_configdrive(states.ACTIVE, "abcd")
        utils.check_allow_configdrive(states.REBUILD, "abcd")
        mock_request.version.minor = 34
        utils.check_allow_configdrive(states.ACTIVE, "abcd")

    def test_check_allow_configdrive_as_dict(self, mock_request):
        mock_request.version.minor = 59
        utils.check_allow_configdrive(states.ACTIVE, {'meta_data': {}})
        utils.check_allow_configdrive(states.ACTIVE, {'meta_data': {},
                                                      'network_data': {},
                                                      'user_data': {},
                                                      'vendor_data': {}})
        utils.check_allow_configdrive(states.ACTIVE, {'user_data': 'foo'})
        utils.check_allow_configdrive(states.ACTIVE, {'user_data': ['foo']})

    def test_check_allow_configdrive_vendor_data_failed(self, mock_request):
        mock_request.version.minor = 58
        self.assertRaises(exception.ClientSideError,
                          utils.check_allow_configdrive,
                          states.ACTIVE,
                          {'meta_data': {},
                           'network_data': {},
                           'user_data': {},
                           'vendor_data': {}})

    def test_check_allow_configdrive_as_dict_invalid(self, mock_request):
        mock_request.version.minor = 59
        self.assertRaises(exception.ClientSideError,
                          utils.check_allow_configdrive, states.REBUILD,
                          {'foo': 'bar'})
        for key in ['meta_data', 'network_data']:
            self.assertRaises(exception.ClientSideError,
                              utils.check_allow_configdrive, states.REBUILD,
                              {key: 'a string'})
        for key in ['meta_data', 'network_data', 'user_data']:
            self.assertRaises(exception.ClientSideError,
                              utils.check_allow_configdrive, states.REBUILD,
                              {key: 42})

    def test_allow_rescue_interface(self, mock_request):
        mock_request.version.minor = 38
        self.assertTrue(utils.allow_rescue_interface())
        mock_request.version.minor = 37
        self.assertFalse(utils.allow_rescue_interface())

    def test_allow_inspect_abort(self, mock_request):
        mock_request.version.minor = 41
        self.assertTrue(utils.allow_inspect_abort())
        mock_request.version.minor = 40
        self.assertFalse(utils.allow_inspect_abort())

    def test_allow_port_is_smartnic(self, mock_request):
        mock_request.version.minor = 53
        self.assertTrue(utils.allow_port_is_smartnic())
        mock_request.version.minor = 52
        self.assertFalse(utils.allow_port_is_smartnic())

    def test_allow_deploy_templates(self, mock_request):
        mock_request.version.minor = 55
        self.assertTrue(utils.allow_deploy_templates())
        mock_request.version.minor = 54
        self.assertFalse(utils.allow_deploy_templates())

    def test_allow_agent_token(self, mock_request):
        mock_request.version.minor = 62
        self.assertTrue(utils.allow_agent_token())
        mock_request.version.minor = 61
        self.assertFalse(utils.allow_agent_token())

    def test_allow_deploy_steps(self, mock_request):
        mock_request.version.minor = 69
        self.assertTrue(utils.allow_deploy_steps())
        mock_request.version.minor = 68
        self.assertFalse(utils.allow_deploy_steps())

    def test_check_allow_deploy_steps(self, mock_request):
        mock_request.version.minor = 69
        utils.check_allow_deploy_steps(states.ACTIVE, {'a': 1})
        utils.check_allow_deploy_steps(states.REBUILD, {'a': 1})

    def test_check_allow_deploy_steps_empty(self, mock_request):
        utils.check_allow_deploy_steps(states.ACTIVE, None)

    def test_check_allow_deploy_steps_version_older(self, mock_request):
        mock_request.version.minor = 68
        self.assertRaises(exception.NotAcceptable,
                          utils.check_allow_deploy_steps,
                          states.ACTIVE, {'a': 1})

    def test_check_allow_deploy_steps_target_unsupported(self, mock_request):
        mock_request.version.minor = 69
        self.assertRaises(exception.ClientSideError,
                          utils.check_allow_deploy_steps,
                          states.MANAGEABLE, {'a': 1})


@mock.patch.object(api, 'request', spec_set=['context', 'version'])
class TestNodeIdent(base.TestCase):

    def setUp(self):
        super(TestNodeIdent, self).setUp()
        self.valid_name = 'my-host'
        self.valid_uuid = uuidutils.generate_uuid()
        self.invalid_name = 'Mr Plow'
        self.node = test_api_utils.post_get_test_node()

    def test_allow_node_logical_names_pre_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 1
        self.assertFalse(utils.allow_node_logical_names())

    def test_allow_node_logical_names_post_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 5
        self.assertTrue(utils.allow_node_logical_names())

    def test_is_valid_node_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 10
        self.assertTrue(utils.is_valid_node_name(self.valid_name))
        self.assertFalse(utils.is_valid_node_name(self.invalid_name))
        self.assertFalse(utils.is_valid_node_name(self.valid_uuid))

    @mock.patch.object(utils, 'allow_node_logical_names', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_name', autospec=True)
    def test_get_rpc_node_expect_uuid(self, mock_gbn, mock_gbu, mock_anln,
                                      mock_pr):
        mock_anln.return_value = True
        self.node['uuid'] = self.valid_uuid
        mock_gbu.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_uuid))
        self.assertEqual(1, mock_gbu.call_count)
        self.assertEqual(0, mock_gbn.call_count)

    @mock.patch.object(utils, 'allow_node_logical_names', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_name', autospec=True)
    def test_get_rpc_node_expect_name(self, mock_gbn, mock_gbu, mock_anln,
                                      mock_pr):
        mock_pr.version.minor = 10
        mock_anln.return_value = True
        self.node['name'] = self.valid_name
        mock_gbn.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_name))
        self.assertEqual(0, mock_gbu.call_count)
        self.assertEqual(1, mock_gbn.call_count)

    @mock.patch.object(utils, 'allow_node_logical_names', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_name', autospec=True)
    def test_get_rpc_node_invalid_name(self, mock_gbn, mock_gbu,
                                       mock_anln, mock_pr):
        mock_pr.version.minor = 10
        mock_anln.return_value = True
        self.assertRaises(exception.InvalidUuidOrName,
                          utils.get_rpc_node,
                          self.invalid_name)

    @mock.patch.object(utils, 'allow_node_logical_names', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_name', autospec=True)
    def test_get_rpc_node_by_uuid_no_logical_name(self, mock_gbn, mock_gbu,
                                                  mock_anln, mock_pr):
        # allow_node_logical_name() should have no effect
        mock_anln.return_value = False
        self.node['uuid'] = self.valid_uuid
        mock_gbu.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_uuid))
        self.assertEqual(1, mock_gbu.call_count)
        self.assertEqual(0, mock_gbn.call_count)

    @mock.patch.object(utils, 'allow_node_logical_names', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_name', autospec=True)
    def test_get_rpc_node_by_name_no_logical_name(self, mock_gbn, mock_gbu,
                                                  mock_anln, mock_pr):
        mock_anln.return_value = False
        self.node['name'] = self.valid_name
        mock_gbn.return_value = self.node
        self.assertRaises(exception.NodeNotFound,
                          utils.get_rpc_node,
                          self.valid_name)

    @mock.patch.object(objects.Node, 'get_by_id', autospec=True)
    def test_populate_node_uuid(self, mock_gbi, mock_pr):
        port = obj_utils.get_test_port(self.context)
        node = obj_utils.get_test_node(self.context, id=port.node_id)
        mock_gbi.return_value = node

        # successful lookup
        d = {}
        utils.populate_node_uuid(port, d)
        self.assertEqual({
            'node_uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        }, d)

        # not found, raise exception
        mock_gbi.side_effect = exception.NodeNotFound(node=port.node_id)
        d = {}
        self.assertRaises(exception.NodeNotFound,
                          utils.populate_node_uuid, port, d)

    @mock.patch.object(utils, 'check_owner_policy', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    def test_replace_node_uuid_with_id(self, mock_gbu, mock_check, mock_pr):
        node = obj_utils.get_test_node(self.context, id=1)
        mock_gbu.return_value = node
        to_dict = {'node_uuid': self.valid_uuid}

        self.assertEqual(node, utils.replace_node_uuid_with_id(to_dict))
        self.assertEqual({'node_id': 1}, to_dict)
        mock_check.assert_called_once_with('node', 'baremetal:node:get',
                                           None, None,
                                           conceal_node=mock.ANY)

    @mock.patch.object(objects.Node, 'get_by_uuid', autospec=True)
    def test_replace_node_uuid_with_id_not_found(self, mock_gbu, mock_pr):
        to_dict = {'node_uuid': self.valid_uuid}
        mock_gbu.side_effect = exception.NodeNotFound(node=self.valid_uuid)

        e = self.assertRaises(exception.NodeNotFound,
                              utils.replace_node_uuid_with_id, to_dict)
        self.assertEqual(400, e.code)

    @mock.patch.object(objects.Node, 'get_by_id', autospec=True)
    def test_replace_node_id_with_uuid(self, mock_gbi, mock_pr):
        node = obj_utils.get_test_node(self.context, uuid=self.valid_uuid)
        mock_gbi.return_value = node
        to_dict = {'node_id': 1}

        self.assertEqual(node, utils.replace_node_id_with_uuid(to_dict))
        self.assertEqual({'node_uuid': self.valid_uuid}, to_dict)

    @mock.patch.object(objects.Node, 'get_by_id', autospec=True)
    def test_replace_node_id_with_uuid_not_found(self, mock_gbi, mock_pr):
        to_dict = {'node_id': 1}
        mock_gbi.side_effect = exception.NodeNotFound(node=1)

        e = self.assertRaises(exception.NodeNotFound,
                              utils.replace_node_id_with_uuid, to_dict)
        self.assertEqual(400, e.code)


class TestVendorPassthru(base.TestCase):

    def test_method_not_specified(self):
        self.assertRaises(exception.ClientSideError,
                          utils.vendor_passthru, 'fake-ident',
                          None, 'fake-topic', data='fake-data')

    @mock.patch.object(api, 'request',
                       spec_set=['method', 'context', 'rpcapi'])
    def _vendor_passthru(self, mock_request, async_call=True,
                         driver_passthru=False):
        return_value = {
            'return': 'SpongeBob',
            'async': async_call,
            'attach': False
        }
        mock_request.method = 'post'
        mock_request.context = 'fake-context'

        passthru_mock = None
        if driver_passthru:
            passthru_mock = mock_request.rpcapi.driver_vendor_passthru
        else:
            passthru_mock = mock_request.rpcapi.vendor_passthru
        passthru_mock.return_value = return_value

        response = utils.vendor_passthru('fake-ident', 'squarepants',
                                         'fake-topic', data='fake-data',
                                         driver_passthru=driver_passthru)

        passthru_mock.assert_called_once_with(
            'fake-context', 'fake-ident', 'squarepants', 'POST',
            'fake-data', 'fake-topic')
        self.assertIsInstance(response, utils.PassthruResponse)
        self.assertEqual('SpongeBob', response.obj)
        sc = http_client.ACCEPTED if async_call else http_client.OK
        self.assertEqual(sc, response.status_code)

    def test_vendor_passthru_async(self):
        self._vendor_passthru()

    def test_vendor_passthru_sync(self):
        self._vendor_passthru(async_call=False)

    def test_driver_vendor_passthru_async(self):
        self._vendor_passthru(driver_passthru=True)

    def test_driver_vendor_passthru_sync(self):
        self._vendor_passthru(async_call=False, driver_passthru=True)

    @mock.patch.object(api, 'request',
                       spec_set=['method', 'context', 'rpcapi'])
    def _test_vendor_passthru_attach(self, return_value, expct_return_value,
                                     mock_request):
        return_ = {'return': return_value, 'async': False, 'attach': True}
        mock_request.method = 'get'
        mock_request.context = 'fake-context'
        mock_request.rpcapi.driver_vendor_passthru.return_value = return_
        response = utils.vendor_passthru('fake-ident', 'bar',
                                         'fake-topic', data='fake-data',
                                         driver_passthru=True)
        mock_request.rpcapi.driver_vendor_passthru.assert_called_once_with(
            'fake-context', 'fake-ident', 'bar', 'GET',
            'fake-data', 'fake-topic')

        # Assert file was attached to the response object
        self.assertIsInstance(response.obj, io.BytesIO)
        self.assertEqual(expct_return_value, response.obj.read())
        # Assert response message is none
        self.assertIsInstance(response, utils.PassthruResponse)
        self.assertEqual(http_client.OK, response.status_code)

    def test_vendor_passthru_attach(self):
        self._test_vendor_passthru_attach('foo', b'foo')

    def test_vendor_passthru_attach_unicode_to_byte(self):
        self._test_vendor_passthru_attach(u'não', b'n\xc3\xa3o')

    def test_vendor_passthru_attach_byte_to_byte(self):
        self._test_vendor_passthru_attach(b'\x00\x01', b'\x00\x01')

    def test_get_controller_reserved_names(self):
        expected = ['maintenance', 'management', 'states',
                    'vendor_passthru', 'validate', 'detail']
        self.assertEqual(sorted(expected),
                         sorted(utils.get_controller_reserved_names(
                                api_node.NodesController)))

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_policy(self, mock_authorize, mock_pr):
        fake_context = ironic_context.RequestContext()
        mock_pr.context = fake_context
        expected_target = dict(fake_context.to_policy_values())
        utils.check_policy('fake-policy')
        mock_authorize.assert_called_once_with('fake-policy', expected_target,
                                               fake_context)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_policy_forbidden(self, mock_authorize, mock_pr):
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        self.assertRaises(exception.HTTPForbidden,
                          utils.check_policy, 'fake-policy')


class TestPortgroupIdent(base.TestCase):
    def setUp(self):
        super(TestPortgroupIdent, self).setUp()
        self.valid_name = 'my-portgroup'
        self.valid_uuid = uuidutils.generate_uuid()
        self.invalid_name = 'My Portgroup'
        self.portgroup = test_api_utils.post_get_test_portgroup()

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(objects.Portgroup, 'get_by_name', autospec=True)
    def test_get_rpc_portgroup_name(self, mock_gbn, mock_pr):
        mock_gbn.return_value = self.portgroup
        self.assertEqual(self.portgroup, utils.get_rpc_portgroup(
            self.valid_name))
        mock_gbn.assert_called_once_with(mock_pr.context, self.valid_name)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(objects.Portgroup, 'get_by_uuid', autospec=True)
    def test_get_rpc_portgroup_uuid(self, mock_gbu, mock_pr):
        self.portgroup['uuid'] = self.valid_uuid
        mock_gbu.return_value = self.portgroup
        self.assertEqual(self.portgroup, utils.get_rpc_portgroup(
            self.valid_uuid))
        mock_gbu.assert_called_once_with(mock_pr.context, self.valid_uuid)

    def test_get_rpc_portgroup_invalid_name(self):
        self.assertRaises(exception.InvalidUuidOrName,
                          utils.get_rpc_portgroup,
                          self.invalid_name)


class TestCheckOwnerPolicy(base.TestCase):
    def setUp(self):
        super(TestCheckOwnerPolicy, self).setUp()
        self.valid_node_uuid = uuidutils.generate_uuid()
        self.node = test_api_utils.post_get_test_node()
        self.node['owner'] = '12345'
        self.node['lessee'] = '54321'

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_owner_policy(
            self, mock_authorize, mock_pr
    ):
        fake_context = ironic_context.RequestContext()
        mock_pr.version.minor = 50
        mock_pr.context = fake_context
        expected_target = dict(fake_context.to_policy_values())
        expected_target['node.owner'] = '12345'
        expected_target['node.lessee'] = '54321'

        utils.check_owner_policy(
            'node', 'fake_policy', self.node['owner'], self.node['lessee']
        )
        mock_authorize.assert_called_once_with(
            'fake_policy', expected_target, fake_context)

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_owner_policy_forbidden(
            self, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_owner_policy,
            'node',
            'fake-policy',
            self.node
        )


class TestCheckNodePolicyAndRetrieve(base.TestCase):
    def setUp(self):
        super(TestCheckNodePolicyAndRetrieve, self).setUp()
        self.valid_node_uuid = uuidutils.generate_uuid()
        self.node = test_api_utils.post_get_test_node()
        self.node['owner'] = '12345'
        self.node['lessee'] = '54321'

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node', autospec=True)
    @mock.patch.object(utils, 'get_rpc_node_with_suffix', autospec=True)
    def test_check_node_policy_and_retrieve(
            self, mock_grnws, mock_grn, mock_authorize, mock_pr
    ):
        fake_context = ironic_context.RequestContext()
        expected_target = dict(fake_context.to_policy_values())
        expected_target['node.owner'] = '12345'
        expected_target['node.lessee'] = '54321'
        mock_pr.context = fake_context

        mock_pr.version.minor = 50
        mock_grn.return_value = self.node

        rpc_node = utils.check_node_policy_and_retrieve(
            'fake_policy', self.valid_node_uuid
        )
        authorize_calls = [
            mock.call('baremetal:node:get', expected_target, fake_context),
            mock.call('fake_policy', expected_target, fake_context)]

        mock_grn.assert_called_once_with(self.valid_node_uuid)
        mock_grnws.assert_not_called()
        mock_authorize.assert_has_calls(authorize_calls)
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node', autospec=True)
    @mock.patch.object(utils, 'get_rpc_node_with_suffix', autospec=True)
    def test_check_node_policy_and_retrieve_with_suffix(
            self, mock_grnws, mock_grn, mock_authorize, mock_pr
    ):
        fake_context = ironic_context.RequestContext()
        expected_target = fake_context.to_policy_values()
        expected_target['node.owner'] = '12345'
        expected_target['node.lessee'] = '54321'
        mock_pr.context = fake_context
        mock_pr.version.minor = 50
        mock_grnws.return_value = self.node

        rpc_node = utils.check_node_policy_and_retrieve(
            'fake_policy', self.valid_node_uuid, True
        )
        mock_grn.assert_not_called()
        mock_grnws.assert_called_once_with(self.valid_node_uuid)
        authorize_calls = [
            mock.call('baremetal:node:get', expected_target, fake_context),
            mock.call('fake_policy', expected_target, fake_context)]
        mock_authorize.assert_has_calls(authorize_calls)
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node', autospec=True)
    def test_check_node_policy_and_retrieve_no_node_policy_notfound(
            self, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_grn.side_effect = exception.NodeNotFound(
            node=self.valid_node_uuid)

        self.assertRaises(
            exception.NodeNotFound,
            utils.check_node_policy_and_retrieve,
            'fake-policy',
            self.valid_node_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node', autospec=True)
    def test_check_node_policy_and_retrieve_no_node(
            self, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_grn.side_effect = exception.NodeNotFound(
            node=self.valid_node_uuid)

        self.assertRaises(
            exception.NodeNotFound,
            utils.check_node_policy_and_retrieve,
            'fake-policy',
            self.valid_node_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node', autospec=True)
    def test_check_node_policy_and_retrieve_policy_forbidden(
            self, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_grn.return_value = self.node

        self.assertRaises(
            exception.NodeNotFound,
            utils.check_node_policy_and_retrieve,
            'fake-policy',
            self.valid_node_uuid
        )


class TestCheckAllocationPolicyAndRetrieve(base.TestCase):
    def setUp(self):
        super(TestCheckAllocationPolicyAndRetrieve, self).setUp()
        self.valid_allocation_uuid = uuidutils.generate_uuid()
        self.allocation = test_api_utils.allocation_post_data()
        self.allocation['owner'] = '12345'

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix', autospec=True)
    def test_check_node_policy_and_retrieve(
            self, mock_graws, mock_authorize, mock_pr
    ):
        fake_context = ironic_context.RequestContext()
        expected_target = dict(fake_context.to_policy_values())
        expected_target['allocation.owner'] = '12345'
        mock_pr.version.minor = 60
        mock_pr.context = fake_context
        mock_graws.return_value = self.allocation

        rpc_allocation = utils.check_allocation_policy_and_retrieve(
            'fake_policy', self.valid_allocation_uuid
        )
        mock_graws.assert_called_once_with(self.valid_allocation_uuid)
        mock_authorize.assert_called_once_with(
            'fake_policy', expected_target, fake_context)
        self.assertEqual(self.allocation, rpc_allocation)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix', autospec=True)
    def test_check_alloc_policy_and_retrieve_no_alloc_policy_forbidden(
            self, mock_graws, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_graws.side_effect = exception.AllocationNotFound(
            allocation=self.valid_allocation_uuid)

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_allocation_policy_and_retrieve,
            'fake-policy',
            self.valid_allocation_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix', autospec=True)
    def test_check_allocation_policy_and_retrieve_no_allocation(
            self, mock_graws, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_graws.side_effect = exception.AllocationNotFound(
            allocation=self.valid_allocation_uuid)

        self.assertRaises(
            exception.AllocationNotFound,
            utils.check_allocation_policy_and_retrieve,
            'fake-policy',
            self.valid_allocation_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix', autospec=True)
    def test_check_allocation_policy_and_retrieve_policy_forbidden(
            self, mock_graws, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_graws.return_value = self.allocation

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_allocation_policy_and_retrieve,
            'fake-policy',
            self.valid_allocation_uuid
        )


class TestCheckMultipleNodePoliciesAndRetrieve(base.TestCase):
    def setUp(self):
        super(TestCheckMultipleNodePoliciesAndRetrieve, self).setUp()
        self.valid_node_uuid = uuidutils.generate_uuid()
        self.node = test_api_utils.post_get_test_node()
        self.node['owner'] = '12345'
        self.node['lessee'] = '54321'

    @mock.patch.object(utils, 'check_node_policy_and_retrieve', autospec=True)
    @mock.patch.object(utils, 'check_owner_policy', autospec=True)
    def test_check_multiple_node_policies_and_retrieve(
            self, mock_cop, mock_cnpar
    ):
        mock_cnpar.return_value = self.node
        mock_cop.return_value = True

        rpc_node = utils.check_multiple_node_policies_and_retrieve(
            ['fake_policy_1', 'fake_policy_2'], self.valid_node_uuid
        )
        mock_cnpar.assert_called_once_with('fake_policy_1',
                                           self.valid_node_uuid, False)
        mock_cop.assert_called_once_with(
            'node', 'fake_policy_2', '12345', '54321')
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(utils, 'check_node_policy_and_retrieve', autospec=True)
    @mock.patch.object(utils, 'check_owner_policy', autospec=True)
    def test_check_multiple_node_policies_and_retrieve_first_fail(
            self, mock_cop, mock_cnpar
    ):
        mock_cnpar.side_effect = exception.HTTPForbidden(resource='fake')
        mock_cop.return_value = True

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_multiple_node_policies_and_retrieve,
            ['fake_policy_1', 'fake_policy_2'],
            self.valid_node_uuid
        )
        mock_cnpar.assert_called_once_with('fake_policy_1',
                                           self.valid_node_uuid, False)
        mock_cop.assert_not_called()

    @mock.patch.object(utils, 'check_node_policy_and_retrieve', autospec=True)
    @mock.patch.object(utils, 'check_owner_policy', autospec=True)
    def test_check_node_policy_and_retrieve_no_node(
            self, mock_cop, mock_cnpar
    ):
        mock_cnpar.return_value = self.node
        mock_cop.side_effect = exception.HTTPForbidden(resource='fake')

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_multiple_node_policies_and_retrieve,
            ['fake_policy_1', 'fake_policy_2'],
            self.valid_node_uuid
        )
        mock_cnpar.assert_called_once_with('fake_policy_1',
                                           self.valid_node_uuid, False)
        mock_cop.assert_called_once_with(
            'node', 'fake_policy_2', '12345', '54321')


class TestCheckListPolicy(base.TestCase):
    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_list_policy(
            self, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        owner = utils.check_list_policy('node')
        self.assertIsNone(owner)

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_list_policy_with_owner(
            self, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        owner = utils.check_list_policy('node', '12345')
        self.assertEqual(owner, '12345')

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_list_policy_forbidden(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            raise exception.HTTPForbidden(resource='fake')
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_list_policy,
            'node'
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_list_policy_forbidden_no_project(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:node:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {}
        mock_pr.version.minor = 50

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_list_policy,
            'node'
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_list_policy_non_admin(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:node:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        owner = utils.check_list_policy('node')
        self.assertEqual(owner, '12345')

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_list_policy_non_admin_owner_proj_mismatch(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:node:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_list_policy,
            'node',
            '54321'
        )


class TestCheckPortPolicyAndRetrieve(base.TestCase):
    def setUp(self):
        super(TestCheckPortPolicyAndRetrieve, self).setUp()
        self.valid_port_uuid = uuidutils.generate_uuid()
        self.node = test_api_utils.post_get_test_node()
        self.node['owner'] = '12345'
        self.node['lessee'] = '54321'
        self.port = objects.Port(self.context, node_id=42)

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(objects.Port, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_id', autospec=True)
    def test_check_port_policy_and_retrieve(
            self, mock_ngbi, mock_pgbu, mock_authorize, mock_pr
    ):
        fake_context = ironic_context.RequestContext()
        expected_target = fake_context.to_policy_values()
        expected_target['node.owner'] = '12345'
        expected_target['node.lessee'] = '54321'
        mock_pr.context = fake_context
        mock_pr.version.minor = 50
        mock_pgbu.return_value = self.port
        mock_ngbi.return_value = self.node

        rpc_port, rpc_node = utils.check_port_policy_and_retrieve(
            'fake_policy', self.valid_port_uuid
        )
        mock_pgbu.assert_called_once_with(mock_pr.context,
                                          self.valid_port_uuid)
        mock_ngbi.assert_called_once_with(mock_pr.context, 42)
        expected = [
            mock.call('baremetal:node:get', expected_target, fake_context),
            mock.call('fake_policy', expected_target, fake_context)]

        mock_authorize.assert_has_calls(expected)

        self.assertEqual(self.port, rpc_port)
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(objects.Port, 'get_by_uuid', autospec=True)
    def test_check_port_policy_and_retrieve_no_port_policy_forbidden(
            self, mock_pgbu, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_pgbu.side_effect = exception.PortNotFound(
            port=self.valid_port_uuid)

        self.assertRaises(
            exception.PortNotFound,
            utils.check_port_policy_and_retrieve,
            'fake-policy',
            self.valid_port_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(objects.Port, 'get_by_uuid', autospec=True)
    def test_check_port_policy_and_retrieve_no_port(
            self, mock_pgbu, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_pgbu.side_effect = exception.PortNotFound(
            port=self.valid_port_uuid)

        self.assertRaises(
            exception.PortNotFound,
            utils.check_port_policy_and_retrieve,
            'fake-policy',
            self.valid_port_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(objects.Port, 'get_by_uuid', autospec=True)
    @mock.patch.object(objects.Node, 'get_by_id', autospec=True)
    def test_check_port_policy_and_retrieve_policy_notfound(
            self, mock_ngbi, mock_pgbu, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_pgbu.return_value = self.port
        mock_ngbi.return_value = self.node

        self.assertRaises(
            exception.PortNotFound,
            utils.check_port_policy_and_retrieve,
            'fake-policy',
            self.valid_port_uuid
        )


class TestCheckPortListPolicy(base.TestCase):
    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_port_list_policy(
            self, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        owner = utils.check_port_list_policy()
        self.assertIsNone(owner)

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_port_list_policy_forbidden(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            raise exception.HTTPForbidden(resource='fake')
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_port_list_policy,
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_port_list_policy_forbidden_no_project(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {}
        mock_pr.version.minor = 50

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_port_list_policy,
        )

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    def test_check_port_list_policy_non_admin(
            self, mock_authorize, mock_pr
    ):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_pr.context.to_policy_values.return_value = {
            'project_id': '12345'
        }
        mock_pr.version.minor = 50

        owner = utils.check_port_list_policy()
        self.assertEqual(owner, '12345')


class TestObjectToDict(base.TestCase):

    def setUp(self):
        super(TestObjectToDict, self).setUp()
        self.node = obj_utils.get_test_node(
            self.context,
            created_at=datetime.datetime(2000, 1, 1, 0, 0),
            updated_at=datetime.datetime(2001, 1, 1, 0, 0),
            inspection_started_at=datetime.datetime(2002, 1, 1, 0, 0),
            console_enabled=True)

        p = mock.patch.object(api, 'request', autospec=False)
        mock_req = p.start()
        mock_req.public_url = 'http://192.0.2.1:5050'
        self.addCleanup(p.stop)

    def test_no_args(self):
        self.assertEqual({
            'created_at': '2000-01-01T00:00:00+00:00',
            'updated_at': '2001-01-01T00:00:00+00:00',
            'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        }, utils.object_to_dict(self.node))

    def test_no_base_attributes(self):
        self.assertEqual({}, utils.object_to_dict(
            self.node,
            include_created_at=False,
            include_updated_at=False,
            include_uuid=False)
        )

    def test_fields(self):
        self.assertEqual({
            'conductor_group': '',
            'console_enabled': True,
            'created_at': '2000-01-01T00:00:00+00:00',
            'driver': 'fake-hardware',
            'inspection_finished_at': None,
            'inspection_started_at': '2002-01-01T00:00:00+00:00',
            'maintenance': False,
            'updated_at': '2001-01-01T00:00:00+00:00',
            'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        }, utils.object_to_dict(
            self.node,
            fields=[
                'conductor_group',
                'console_enabled',
                'driver',
                'inspection_finished_at',
                'inspection_started_at',
                'maintenance',
            ])
        )

    def test_links(self):
        self.assertEqual({
            'created_at': '2000-01-01T00:00:00+00:00',
            'links': [{
                'href': 'http://192.0.2.1:5050/v1/node/'
                        '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                'rel': 'self'
            }, {
                'href': 'http://192.0.2.1:5050/node/'
                        '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                'rel': 'bookmark'
            }],
            'updated_at': '2001-01-01T00:00:00+00:00',
            'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
        }, utils.object_to_dict(self.node, link_resource='node'))

        self.assertEqual({
            'created_at': '2000-01-01T00:00:00+00:00',
            'links': [{
                'href': 'http://192.0.2.1:5050/v1/node/foo',
                'rel': 'self'
            }, {
                'href': 'http://192.0.2.1:5050/node/foo',
                'rel': 'bookmark'
            }],
            'updated_at': '2001-01-01T00:00:00+00:00',
            'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
        }, utils.object_to_dict(
            self.node,
            link_resource='node',
            link_resource_args='foo'))


class TestLocalLinkValidation(base.TestCase):

    def test_local_link_connection_type(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'value2',
                 'switch_info': 'value3'}
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_type_datapath_id(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'switch_id': '0000000000000000',
                 'port_id': 'value2',
                 'switch_info': 'value3'}
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_type_not_mac_or_datapath_id(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'switch_id': 'badid',
                 'port_id': 'value2',
                 'switch_info': 'value3'}
        self.assertRaises(exception.InvalidSwitchID, v, 'l', value)

    def test_local_link_connection_type_invalid_key(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'value2',
                 'switch_info': 'value3',
                 'invalid_key': 'value'}
        self.assertRaisesRegex(
            exception.Invalid,
            'Additional properties are not allowed',
            v, 'l', value)

    def test_local_link_connection_type_missing_local_link_mandatory_key(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'switch_info': 'value3'}
        self.assertRaisesRegex(exception.Invalid, 'is a required property',
                               v, 'l', value)

    def test_local_link_connection_type_local_link_keys_mandatory(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'value2'}
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_type_empty_value(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {}
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_type_smart_nic_keys_mandatory(self):
        v = utils.LOCAL_LINK_VALIDATOR
        vs = utils.LOCAL_LINK_SMART_NIC_VALIDATOR
        value = {'port_id': 'rep0-0',
                 'hostname': 'hostname'}
        self.assertEqual(value, vs('l', value))
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_type_smart_nic_keys_with_optional(self):
        v = utils.LOCAL_LINK_VALIDATOR
        vs = utils.LOCAL_LINK_SMART_NIC_VALIDATOR
        value = {'port_id': 'rep0-0',
                 'hostname': 'hostname',
                 'switch_id': '0a:1b:2c:3d:4e:5f',
                 'switch_info': 'sw_info'}
        self.assertEqual(value, vs('l', value))
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_type_smart_nic_keys_hostname_missing(self):
        v = utils.LOCAL_LINK_VALIDATOR
        vs = utils.LOCAL_LINK_SMART_NIC_VALIDATOR
        value = {'port_id': 'rep0-0'}
        self.assertRaises(exception.Invalid, vs, 'l', value)
        self.assertRaises(exception.Invalid, v, 'l', value)

    def test_local_link_connection_type_smart_nic_keys_port_id_missing(self):
        v = utils.LOCAL_LINK_VALIDATOR
        vs = utils.LOCAL_LINK_SMART_NIC_VALIDATOR
        value = {'hostname': 'hostname'}
        self.assertRaises(exception.Invalid, vs, 'l', value)
        self.assertRaises(exception.Invalid, v, 'l', value)

    def test_local_link_connection_net_type_unmanaged(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'network_type': 'unmanaged'}
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_net_type_unmanaged_combine_ok(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'network_type': 'unmanaged',
                 'switch_id': '0a:1b:2c:3d:4e:5f',
                 'port_id': 'rep0-0'}
        self.assertEqual(value, v('l', value))

    def test_local_link_connection_net_type_invalid(self):
        v = utils.LOCAL_LINK_VALIDATOR
        value = {'network_type': 'invalid'}
        self.assertRaises(exception.Invalid, v, 'l', value)
