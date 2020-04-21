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

from http import client as http_client

import mock
import os_traits
from oslo_config import cfg
from oslo_utils import uuidutils
from webob import static
import wsme

from ironic import api
from ironic.api.controllers.v1 import node as api_node
from ironic.api.controllers.v1 import utils
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common import policy
from ironic.common import states
from ironic import objects
from ironic.tests import base
from ironic.tests.unit.api import utils as test_api_utils

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

    def test_validate_trait(self):
        utils.validate_trait(os_traits.HW_CPU_X86_AVX2)
        utils.validate_trait("CUSTOM_1")
        utils.validate_trait("CUSTOM_TRAIT_GOLD")
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, "A" * 256)
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, "CuSTOM_1")
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, "")
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, "CUSTOM_bob")
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, "CUSTOM_1-BOB")
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, "aCUSTOM_1a")
        large = "CUSTOM_" + ("1" * 248)
        self.assertEqual(255, len(large))
        utils.validate_trait(large)
        self.assertRaises(exception.ClientSideError,
                          utils.validate_trait, large + "1")
        # Check custom error prefix.
        self.assertRaisesRegex(exception.ClientSideError,
                               "spongebob",
                               utils.validate_trait, "invalid", "spongebob")

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
        self.assertRaisesRegex(exception.PatchError,
                               "can't remove non-existent object 'foo'",
                               utils.apply_jsonpatch, doc, patch)

    def test_apply_jsonpatch_replace_non_existent_list_item(self):
        # Raises an IndexError.
        doc = []
        patch = [{"op": "replace", "path": "/0", "value": 42}]
        self.assertRaisesRegex(exception.PatchError,
                               "can't replace outside of list|"
                               "list assignment index out of range",
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

    @mock.patch.object(objects.Port, 'supports_physical_network')
    def test_allow_port_physical_network_no_pin(self, mock_spn, mock_request):
        mock_spn.return_value = True
        mock_request.version.minor = 34
        self.assertTrue(utils.allow_port_physical_network())
        mock_request.version.minor = 33
        self.assertFalse(utils.allow_port_physical_network())

    @mock.patch.object(objects.Port, 'supports_physical_network')
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


@mock.patch.object(api, 'request')
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

    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_expect_uuid(self, mock_gbn, mock_gbu, mock_anln,
                                      mock_pr):
        mock_anln.return_value = True
        self.node['uuid'] = self.valid_uuid
        mock_gbu.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_uuid))
        self.assertEqual(1, mock_gbu.call_count)
        self.assertEqual(0, mock_gbn.call_count)

    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_expect_name(self, mock_gbn, mock_gbu, mock_anln,
                                      mock_pr):
        mock_pr.version.minor = 10
        mock_anln.return_value = True
        self.node['name'] = self.valid_name
        mock_gbn.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_name))
        self.assertEqual(0, mock_gbu.call_count)
        self.assertEqual(1, mock_gbn.call_count)

    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_invalid_name(self, mock_gbn, mock_gbu,
                                       mock_anln, mock_pr):
        mock_pr.version.minor = 10
        mock_anln.return_value = True
        self.assertRaises(exception.InvalidUuidOrName,
                          utils.get_rpc_node,
                          self.invalid_name)

    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_by_uuid_no_logical_name(self, mock_gbn, mock_gbu,
                                                  mock_anln, mock_pr):
        # allow_node_logical_name() should have no effect
        mock_anln.return_value = False
        self.node['uuid'] = self.valid_uuid
        mock_gbu.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_uuid))
        self.assertEqual(1, mock_gbu.call_count)
        self.assertEqual(0, mock_gbn.call_count)

    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_by_name_no_logical_name(self, mock_gbn, mock_gbu,
                                                  mock_anln, mock_pr):
        mock_anln.return_value = False
        self.node['name'] = self.valid_name
        mock_gbn.return_value = self.node
        self.assertRaises(exception.NodeNotFound,
                          utils.get_rpc_node,
                          self.valid_name)


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
        self.assertIsInstance(response, wsme.api.Response)
        self.assertEqual('SpongeBob', response.obj)
        self.assertEqual(response.return_type, atypes.Unset)
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

    @mock.patch.object(api, 'response', spec_set=['app_iter'])
    @mock.patch.object(api, 'request',
                       spec_set=['method', 'context', 'rpcapi'])
    def _test_vendor_passthru_attach(self, return_value, expct_return_value,
                                     mock_request, mock_response):
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
        self.assertIsInstance(mock_response.app_iter, static.FileIter)
        self.assertEqual(expct_return_value,
                         mock_response.app_iter.file.read())
        # Assert response message is none
        self.assertIsInstance(response, wsme.api.Response)
        self.assertIsNone(response.obj)
        self.assertIsNone(response.return_type)
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
        utils.check_policy('fake-policy')
        cdict = api.request.context.to_policy_values()
        mock_authorize.assert_called_once_with('fake-policy', cdict, cdict)

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
    @mock.patch.object(objects.Portgroup, 'get_by_name')
    def test_get_rpc_portgroup_name(self, mock_gbn, mock_pr):
        mock_gbn.return_value = self.portgroup
        self.assertEqual(self.portgroup, utils.get_rpc_portgroup(
            self.valid_name))
        mock_gbn.assert_called_once_with(mock_pr.context, self.valid_name)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(objects.Portgroup, 'get_by_uuid')
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
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}

        utils.check_owner_policy(
            'node', 'fake_policy', self.node['owner'], self.node['lessee']
        )
        mock_authorize.assert_called_once_with(
            'fake_policy',
            {'node.owner': '12345', 'node.lessee': '54321'}, {})

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
    @mock.patch.object(utils, 'get_rpc_node')
    @mock.patch.object(utils, 'get_rpc_node_with_suffix')
    def test_check_node_policy_and_retrieve(
            self, mock_grnws, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_grn.return_value = self.node

        rpc_node = utils.check_node_policy_and_retrieve(
            'fake_policy', self.valid_node_uuid
        )
        mock_grn.assert_called_once_with(self.valid_node_uuid)
        mock_grnws.assert_not_called()
        mock_authorize.assert_called_once_with(
            'fake_policy',
            {'node.owner': '12345', 'node.lessee': '54321'}, {})
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(api, 'request', spec_set=["context", "version"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node')
    @mock.patch.object(utils, 'get_rpc_node_with_suffix')
    def test_check_node_policy_and_retrieve_with_suffix(
            self, mock_grnws, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_grnws.return_value = self.node

        rpc_node = utils.check_node_policy_and_retrieve(
            'fake_policy', self.valid_node_uuid, True
        )
        mock_grn.assert_not_called()
        mock_grnws.assert_called_once_with(self.valid_node_uuid)
        mock_authorize.assert_called_once_with(
            'fake_policy',
            {'node.owner': '12345', 'node.lessee': '54321'}, {})
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node')
    def test_check_node_policy_and_retrieve_no_node_policy_forbidden(
            self, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_grn.side_effect = exception.NodeNotFound(
            node=self.valid_node_uuid)

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_node_policy_and_retrieve,
            'fake-policy',
            self.valid_node_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_node')
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
    @mock.patch.object(utils, 'get_rpc_node')
    def test_check_node_policy_and_retrieve_policy_forbidden(
            self, mock_grn, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_grn.return_value = self.node

        self.assertRaises(
            exception.HTTPForbidden,
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
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix')
    def test_check_node_policy_and_retrieve(
            self, mock_graws, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 60
        mock_pr.context.to_policy_values.return_value = {}
        mock_graws.return_value = self.allocation

        rpc_allocation = utils.check_allocation_policy_and_retrieve(
            'fake_policy', self.valid_allocation_uuid
        )
        mock_graws.assert_called_once_with(self.valid_allocation_uuid)
        mock_authorize.assert_called_once_with(
            'fake_policy', {'allocation.owner': '12345'}, {})
        self.assertEqual(self.allocation, rpc_allocation)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix')
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
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix')
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
    @mock.patch.object(utils, 'get_rpc_allocation_with_suffix')
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

    @mock.patch.object(utils, 'check_node_policy_and_retrieve')
    @mock.patch.object(utils, 'check_owner_policy')
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

    @mock.patch.object(utils, 'check_node_policy_and_retrieve')
    @mock.patch.object(utils, 'check_owner_policy')
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

    @mock.patch.object(utils, 'check_node_policy_and_retrieve')
    @mock.patch.object(utils, 'check_owner_policy')
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
    @mock.patch.object(objects.Port, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_id')
    def test_check_port_policy_and_retrieve(
            self, mock_ngbi, mock_pgbu, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_pgbu.return_value = self.port
        mock_ngbi.return_value = self.node

        rpc_port, rpc_node = utils.check_port_policy_and_retrieve(
            'fake_policy', self.valid_port_uuid
        )
        mock_pgbu.assert_called_once_with(mock_pr.context,
                                          self.valid_port_uuid)
        mock_ngbi.assert_called_once_with(mock_pr.context, 42)
        mock_authorize.assert_called_once_with(
            'fake_policy',
            {'node.owner': '12345', 'node.lessee': '54321'},
            {})
        self.assertEqual(self.port, rpc_port)
        self.assertEqual(self.node, rpc_node)

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(objects.Port, 'get_by_uuid')
    def test_check_port_policy_and_retrieve_no_port_policy_forbidden(
            self, mock_pgbu, mock_authorize, mock_pr
    ):
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_pgbu.side_effect = exception.PortNotFound(
            port=self.valid_port_uuid)

        self.assertRaises(
            exception.HTTPForbidden,
            utils.check_port_policy_and_retrieve,
            'fake-policy',
            self.valid_port_uuid
        )

    @mock.patch.object(api, 'request', spec_set=["context"])
    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(objects.Port, 'get_by_uuid')
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
    @mock.patch.object(objects.Port, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_id')
    def test_check_port_policy_and_retrieve_policy_forbidden(
            self, mock_ngbi, mock_pgbu, mock_authorize, mock_pr
    ):
        mock_pr.version.minor = 50
        mock_pr.context.to_policy_values.return_value = {}
        mock_authorize.side_effect = exception.HTTPForbidden(resource='fake')
        mock_pgbu.return_value = self.port
        mock_ngbi.return_value = self.node

        self.assertRaises(
            exception.HTTPForbidden,
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
