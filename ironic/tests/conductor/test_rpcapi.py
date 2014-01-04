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
Unit Tests for :py:class:`ironic.conductor.rpcapi.ConductorAPI`.
"""

import fixtures

from oslo.config import cfg

from ironic.common import states
from ironic.conductor import rpcapi as conductor_rpcapi
from ironic.db import api as dbapi
from ironic import objects
from ironic.openstack.common import context
from ironic.openstack.common import jsonutils as json
from ironic.tests.db import base
from ironic.tests.db import utils as dbutils

CONF = cfg.CONF


class RPCAPITestCase(base.DbTestCase):

    def setUp(self):
        super(RPCAPITestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        self.fake_node = json.to_primitive(dbutils.get_test_node(
                driver='fake-driver'))
        self.fake_node_obj = objects.Node._from_db_object(
                                                    objects.Node(),
                                                    self.fake_node)

    def test_serialized_instance_has_uuid(self):
        self.assertTrue('uuid' in self.fake_node)

    def test_get_topic_for_known_driver(self):
        CONF.set_override('host', 'fake-host')
        self.dbapi.register_conductor({'hostname': 'fake-host',
                                       'drivers': ['fake-driver']})

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        expected_topic = 'fake-topic.fake-host'
        self.assertEqual(expected_topic,
                         rpcapi.get_topic_for(self.fake_node_obj))

    def test_get_topic_for_unknown_driver(self):
        CONF.set_override('host', 'fake-host')
        self.dbapi.register_conductor({'hostname': 'fake-host',
                                       'drivers': ['other-driver']})

        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        expected_topic = 'fake-topic'
        self.assertEqual(expected_topic,
                         rpcapi.get_topic_for(self.fake_node_obj))

    def _test_rpcapi(self, method, rpc_method, **kwargs):
        ctxt = context.get_admin_context()
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')

        expected_retval = 'hello world' if rpc_method == 'call' else None
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

        self.useFixture(fixtures.MonkeyPatch(
                "ironic.openstack.common.rpc.%s" % rpc_method,
                _fake_rpc_method))

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, expected_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_get_node_power_state(self):
        self._test_rpcapi('get_node_power_state',
                          'call',
                           node_id=123)

    def test_update_node(self):
        self._test_rpcapi('update_node',
                          'call',
                          node_obj=self.fake_node)

    def test_change_node_power_state(self):
        self._test_rpcapi('change_node_power_state',
                          'cast',
                          node_id=self.fake_node['uuid'],
                          new_state=states.POWER_ON)

    def test_pass_vendor_info(self):
        ctxt = context.get_admin_context()
        rpcapi = conductor_rpcapi.ConductorAPI(topic='fake-topic')
        expected_retval = 'hello world'

        def _fake_rpc_method(*args, **kwargs):
                return expected_retval

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.openstack.common.rpc.call', _fake_rpc_method))
        retval = rpcapi.vendor_passthru(ctxt, node_id=self.fake_node['uuid'],
                                    driver_method='foo', info={'bar': 'baz'})
        self.assertEqual(retval, expected_retval)

    def test_do_node_deploy(self):
        self._test_rpcapi('do_node_deploy',
                          'cast',
                          node_id=self.fake_node['uuid'])

    def test_do_node_tear_down(self):
        self._test_rpcapi('do_node_tear_down',
                          'cast',
                          node_id=self.fake_node['uuid'])

    def test_validate_driver_interfaces(self):
        self._test_rpcapi('validate_driver_interfaces',
                          'call',
                          node_id=self.fake_node['uuid'])
