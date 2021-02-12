# -*- encoding: utf-8 -*-
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
Tests for ACL. Checks whether certain kinds of requests
are blocked or allowed to be processed.
"""

import abc
from unittest import mock

import ddt
from keystonemiddleware import auth_token
from oslo_config import cfg

from ironic.api.controllers.v1 import versions as api_versions
from ironic.common import exception
from ironic.conductor import rpcapi
from ironic.tests.unit.api import base
from ironic.tests.unit.db import utils as db_utils


class TestACLBase(base.BaseApiTest):

    def setUp(self):
        super(TestACLBase, self).setUp()

        self.environ = {}
        self.format_data = {}
        self._create_test_data()
        self.fake_token = None
        mock_auth = mock.patch.object(
            auth_token.AuthProtocol, 'process_request',
            autospec=True)
        self.mock_auth = mock_auth.start()
        self.addCleanup(mock_auth.stop)

        topic = mock.patch.object(
            rpcapi.ConductorAPI, 'get_topic_for', autospec=True)
        self.mock_topic = topic.start()
        self.mock_topic.side_effect = exception.TemporaryFailure
        self.addCleanup(topic.stop)
        rtopic = mock.patch.object(rpcapi.ConductorAPI, 'get_random_topic',
                                   autospec=True)
        self.mock_random_topic = rtopic.start()
        self.mock_random_topic.side_effect = exception.TemporaryFailure
        self.addCleanup(rtopic.stop)

    def _make_app(self):
        cfg.CONF.set_override('auth_strategy', 'keystone')
        return super(TestACLBase, self)._make_app()

    @abc.abstractmethod
    def _create_test_data(self):
        pass

    def _check_skip(self, **kwargs):
        if kwargs.get('skip_reason'):
            self.skipTest(kwargs.get('skip_reason'))

    def _fake_process_request(self, request, auth_token_request):
        pass

    def _test_request(self, path, params=None, headers=None, method='get',
                      body=None, assert_status=None,
                      assert_dict_contains=None,
                      assert_list_length=None):
        path = path.format(**self.format_data)
        self.mock_auth.side_effect = self._fake_process_request

        # always request the latest api version
        version = api_versions.max_version_string()
        rheaders = {
            'X-OpenStack-Ironic-API-Version': version
        }
        # NOTE(TheJulia): Logging the test request to aid
        # in troubleshooting ACL testing. This is a pattern
        # followed in API unit testing in ironic, and
        # really does help.
        print('API ACL Testing Path %s %s' % (method, path))
        if headers:
            for k, v in headers.items():
                rheaders[k] = v.format(**self.format_data)

        if method == 'get':
            response = self.get_json(
                path,
                headers=rheaders,
                expect_errors=True,
                extra_environ=self.environ,
                path_prefix=''
            )
        elif method == 'put':
            response = self.put_json(
                path,
                headers=rheaders,
                expect_errors=True,
                extra_environ=self.environ,
                path_prefix='',
                params=body
            )
        elif method == 'post':
            response = self.post_json(
                path,
                headers=rheaders,
                expect_errors=True,
                extra_environ=self.environ,
                path_prefix='',
                params=body
            )
        elif method == 'patch':
            response = self.patch_json(
                path,
                params=body,
                headers=rheaders,
                expect_errors=True,
                extra_environ=self.environ,
                path_prefix=''
            )
        elif method == 'delete':
            response = self.delete(
                path,
                headers=rheaders,
                expect_errors=True,
                extra_environ=self.environ,
                path_prefix=''
            )
        else:
            assert False, 'Unimplemented test method: %s' % method

        if assert_status:
            self.assertEqual(assert_status, response.status_int)
        else:
            self.assertIsNotNone(assert_status,
                                 'Tests must include an assert_status')

        if assert_dict_contains:
            for k, v in assert_dict_contains.items():
                self.assertIn(k, response)
                self.assertEqual(v.format(**self.format_data),
                                 response.json[k])

        if assert_list_length:
            for root, length in assert_list_length.items():
                # root - object to look inside
                # length - number of expected elements which will be
                #          important for owner/lessee testing.
                items = response.json[root]
                self.assertIsInstance(items, list)
                self.assertEqual(length, len(items))

        # NOTE(TheJulia): API tests in Ironic tend to have a pattern
        # to print request and response data to aid in development
        # and troubleshooting. As such the prints should remain,
        # at least until we are through primary development of the
        # this test suite.
        print('ACL Test GOT %s' % response)


@ddt.ddt
class TestRBACBasic(TestACLBase):

    def _create_test_data(self):
        fake_db_node = db_utils.create_test_node(chassis_id=None)
        self.format_data['node_uuid'] = fake_db_node['uuid']

    @ddt.file_data('test_acl_basic.yaml')
    @ddt.unpack
    def test_basic(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)


@ddt.ddt
class TestRBACModelBeforeScopes(TestACLBase):

    def _create_test_data(self):
        allocated_node_id = 31
        fake_db_allocation = db_utils.create_test_allocation(
            node_id=allocated_node_id,
            resource_class="CUSTOM_TEST")
        fake_db_node = db_utils.create_test_node(
            chassis_id=None,
            driver='fake-driverz')
        fake_db_node_alloced = db_utils.create_test_node(
            id=allocated_node_id,
            chassis_id=None,
            allocation_id=fake_db_allocation['id'],
            uuid='22e26c0b-03f2-4d2e-ae87-c02d7f33c000',
            driver='fake-driverz')
        fake_vif_port_id = "ee21d58f-5de2-4956-85ff-33935ea1ca00"
        fake_db_port = db_utils.create_test_port(
            node_id=fake_db_node['id'],
            internal_info={'tenant_vif_port_id': fake_vif_port_id})
        fake_db_portgroup = db_utils.create_test_portgroup(
            node_id=fake_db_node['id'])
        fake_db_chassis = db_utils.create_test_chassis()
        fake_db_deploy_template = db_utils.create_test_deploy_template()
        fake_db_conductor = db_utils.create_test_conductor()
        fake_db_volume_target = db_utils.create_test_volume_target(
            node_id=fake_db_allocation['id'])
        fake_db_volume_connector = db_utils.create_test_volume_connector(
            node_id=fake_db_allocation['id'])
        # Trait name aligns with create_test_node_trait.
        fake_trait = 'trait'
        fake_setting = 'FAKE_SETTING'
        db_utils.create_test_bios_setting(
            node_id=fake_db_node['id'],
            name=fake_setting,
            value=fake_setting)
        db_utils.create_test_node_trait(
            node_id=fake_db_node['id'])

        self.format_data.update({
            'node_ident': fake_db_node['uuid'],
            'allocated_node_ident': fake_db_node_alloced['uuid'],
            'port_ident': fake_db_port['uuid'],
            'portgroup_ident': fake_db_portgroup['uuid'],
            'chassis_ident': fake_db_chassis['uuid'],
            'deploy_template_ident': fake_db_deploy_template['uuid'],
            'allocation_ident': fake_db_allocation['uuid'],
            'conductor_ident': fake_db_conductor['hostname'],
            'vif_ident': fake_vif_port_id,
            # Can't use the same fake-driver as other tests can
            # pollute a global method cache in the API that is in the
            # test runner, resulting in false positives.
            'driver_name': 'fake-driverz',
            'bios_setting': fake_setting,
            'trait': fake_trait,
            'volume_target_ident': fake_db_volume_target['uuid'],
            'volume_connector_ident': fake_db_volume_connector['uuid'],
        })

    @ddt.file_data('test_rbac_legacy.yaml')
    @ddt.unpack
    def test_rbac_legacy(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)


@ddt.ddt
class TestRBACScoped(TestRBACModelBeforeScopes):
    """Test Scoped ACL access using our existing access policy."""

    def setUp(self):
        super(TestRBACScoped, self).setUp()

        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        # NOTE(TheJulia): The purpose of this class is to execute the legacy
        # RBAC tests with the new configuration, which forces us to
        # explicity mark each test as a deprecated test later on. That
        # funcationality will be added in a later patch when needed,
