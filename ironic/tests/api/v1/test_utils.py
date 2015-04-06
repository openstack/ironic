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

import mock
from oslo_config import cfg
from oslo_utils import uuidutils
import pecan
import wsme

from ironic.api.controllers.v1 import utils
from ironic.common import exception
from ironic import objects
from ironic.tests.api import utils as test_api_utils
from ironic.tests import base

CONF = cfg.CONF


class TestApiUtils(base.TestCase):

    def test_validate_limit(self):
        limit = utils.validate_limit(10)
        self.assertEqual(10, 10)

        # max limit
        limit = utils.validate_limit(999999999)
        self.assertEqual(CONF.api.max_limit, limit)

        # negative
        self.assertRaises(wsme.exc.ClientSideError, utils.validate_limit, -1)

        # zero
        self.assertRaises(wsme.exc.ClientSideError, utils.validate_limit, 0)

    def test_validate_sort_dir(self):
        sort_dir = utils.validate_sort_dir('asc')
        self.assertEqual('asc', sort_dir)

        # invalid sort_dir parameter
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_sort_dir,
                          'fake-sort')


class TestNodeIdent(base.TestCase):

    def setUp(self):
        super(TestNodeIdent, self).setUp()
        self.valid_name = 'my-host'
        self.valid_uuid = uuidutils.generate_uuid()
        self.invalid_name = 'Mr Plow'
        self.invalid_uuid = '636-555-3226-'
        self.node = test_api_utils.post_get_test_node()

    @mock.patch.object(pecan, 'request')
    def test_allow_node_logical_names_pre_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 1
        self.assertFalse(utils.allow_node_logical_names())

    @mock.patch.object(pecan, 'request')
    def test_allow_node_logical_names_post_name(self, mock_pecan_req):
        mock_pecan_req.version.minor = 5
        self.assertTrue(utils.allow_node_logical_names())

    def test_is_valid_node_name(self):
        self.assertTrue(utils.is_valid_node_name(self.valid_name))
        self.assertFalse(utils.is_valid_node_name(self.invalid_name))
        self.assertFalse(utils.is_valid_node_name(self.valid_uuid))
        self.assertFalse(utils.is_valid_node_name(self.invalid_uuid))

    @mock.patch.object(pecan, 'request')
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

    @mock.patch.object(pecan, 'request')
    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_expect_name(self, mock_gbn, mock_gbu, mock_anln,
                                      mock_pr):
        mock_anln.return_value = True
        self.node['name'] = self.valid_name
        mock_gbn.return_value = self.node
        self.assertEqual(self.node, utils.get_rpc_node(self.valid_name))
        self.assertEqual(0, mock_gbu.call_count)
        self.assertEqual(1, mock_gbn.call_count)

    @mock.patch.object(pecan, 'request')
    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_invalid_name(self, mock_gbn, mock_gbu,
                                       mock_anln, mock_pr):
        mock_anln.return_value = True
        self.assertRaises(exception.InvalidUuidOrName,
                          utils.get_rpc_node,
                          self.invalid_name)

    @mock.patch.object(pecan, 'request')
    @mock.patch.object(utils, 'allow_node_logical_names')
    @mock.patch.object(objects.Node, 'get_by_uuid')
    @mock.patch.object(objects.Node, 'get_by_name')
    def test_get_rpc_node_invalid_uuid(self, mock_gbn, mock_gbu,
                                       mock_anln, mock_pr):
        mock_anln.return_value = True
        self.assertRaises(exception.InvalidUuidOrName,
                          utils.get_rpc_node,
                          self.invalid_uuid)

    @mock.patch.object(pecan, 'request')
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

    @mock.patch.object(pecan, 'request')
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
