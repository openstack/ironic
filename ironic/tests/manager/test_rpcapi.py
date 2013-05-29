# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
Unit Tests for :py:class:`ironic.manager.rpcapi.ManagerAPI`.
"""

from oslo.config import cfg

from ironic.db import api as dbapi
from ironic.manager import rpcapi as manager_rpcapi
from ironic.openstack.common import context
from ironic.openstack.common import jsonutils as json
from ironic.openstack.common import rpc
from ironic.tests.db import base
from ironic.tests.db import utils as dbutils

CONF = cfg.CONF


class ManagerRpcAPITestCase(base.DbTestCase):

    def setUp(self):
        super(ManagerRpcAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        self.fake_node = json.to_primitive(dbutils.get_test_node(
                                            control_driver='fake',
                                            deploy_driver='fake'))

    def test_serialized_instance_has_uuid(self):
        self.assertTrue('uuid' in self.fake_node)

    def _test_rpcapi(self, method, rpc_method, **kwargs):
        ctxt = context.get_admin_context()
        rpcapi = manager_rpcapi.ManagerAPI(topic='fake-topic')

        expected_retval = 'hello world' if method == 'call' else None
        expected_version = kwargs.pop('version', rpcapi.RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)

        expected_msg['version'] = expected_version

        expected_topic = 'fake-topic'
        if 'host' in kwargs:
            expected_topic += ".%s" % kwargs['host']

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, expected_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_get_node_power_state(self):
        self._test_rpcapi('get_node_power_state',
                          'call',
                           node_id=123)
