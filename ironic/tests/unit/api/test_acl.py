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
from ironic.db import api as db_api
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
        self._set_test_config()

    def _make_app(self):
        cfg.CONF.set_override('auth_strategy', 'keystone')
        return super(TestACLBase, self)._make_app()

    @abc.abstractmethod
    def _create_test_data(self):
        pass

    @abc.abstractmethod
    def _set_test_config(self):
        pass

    def _check_skip(self, **kwargs):
        if kwargs.get('skip_reason'):
            self.skipTest(kwargs.get('skip_reason'))

    def _fake_process_request(self, request, auth_token_request):
        pass

    def _test_request(self, path, params=None, headers=None, method='get',  # noqa: C901, E501
                      body=None, assert_status=None,
                      assert_dict_contains=None,
                      assert_list_length=None,
                      deprecated=None,
                      self_manage_nodes=True,
                      enable_service_project=False,
                      service_project='service'):
        path = path.format(**self.format_data)
        self.mock_auth.side_effect = self._fake_process_request

        # Set self management override
        if not self_manage_nodes:
            cfg.CONF.set_override(
                'project_admin_can_manage_own_nodes',
                False,
                'api')
        if enable_service_project:
            cfg.CONF.set_override('rbac_service_role_elevated_access', True)
        if service_project != 'service':
            # Enable us to sort of gracefully test a name variation
            # with existing ddt test modeling.
            cfg.CONF.set_override('rbac_service_project_name',
                                  service_project)

        # always request the latest api version
        version = api_versions.max_version_string()
        rheaders = {
            'X-OpenStack-Ironic-API-Version': version
        }
        # NOTE(TheJulia): Logging the test request to aid
        # in troubleshooting ACL testing. This is a pattern
        # followed in API unit testing in ironic, and
        # really does help.
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
        # Once miggrated:
        # Items will return:
        # 403 - Trying to access something that is generally denied.
        #       Example: PATCH /v1/nodes/<uuid> as a reader.
        # 404 - Trying to access something where we don't have permissions
        #       in a project scope. This is particularly true where implied
        #       permissions or association exists. Ports are attempted to be
        #       accessed when the underlying node is inaccessible as owner
        #       nor node matches.
        #       Example: GET /v1/portgroups or /v1/nodes/<uuid>/ports
        # 500 - Attempting to access something such an system scoped endpoint
        #       with a project scoped request. Example: /v1/conductors.
        if not (bool(deprecated)
                and ('404' in response.status
                     or '500' in response.status
                     or '403' in response.status)
                and cfg.CONF.oslo_policy.enforce_scope
                and cfg.CONF.oslo_policy.enforce_new_defaults):
            self.assertEqual(assert_status, response.status_int)
        else:
            self.assertTrue(
                ('404' in response.status
                 or '500' in response.status
                 or '403' in response.status))
            # We can't check the contents of the response if there is no
            # response.
            return
        if not bool(deprecated):
            self.assertIsNotNone(assert_status,
                                 'Tests must include an assert_status')

        if assert_dict_contains:
            for k, v in assert_dict_contains.items():
                self.assertIn(k, response)
                if str(v) == "None":
                    # Compare since the variable loaded from the
                    # json ends up being null in json or None.
                    self.assertIsNone(response.json[k])
                elif str(v) == "{}":
                    # Special match for signifying a dictionary.
                    self.assertEqual({}, response.json[k])
                elif isinstance(v, dict):
                    # The value from the YAML can be a dictionary,
                    # which cannot be formatted, so we're likely doing
                    # direct matching.
                    self.assertEqual(str(v), str(response.json[k]))
                else:
                    self.assertEqual(v.format(**self.format_data),
                                     response.json[k])

        if assert_list_length:
            for root, length in assert_list_length.items():
                # root - object to look inside
                # length - number of expected elements which will be
                #          important for owner/lessee testing.
                items = response.json[root]
                self.assertIsInstance(items, list)
                if not (bool(deprecated)
                        and cfg.CONF.oslo_policy.enforce_scope):
                    self.assertEqual(length, len(items))
                else:
                    # If we have scope enforcement, we likely have different
                    # views, such as "other" admins being subjected to
                    # a filtered view in these cases.
                    self.assertEqual(0, len(items))


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
class TestRBACModelBeforeScopesBase(TestACLBase):

    def _create_test_data(self):
        allocated_node_id = 31
        fake_db_allocation = db_utils.create_test_allocation(
            resource_class="CUSTOM_TEST")
        fake_db_node = db_utils.create_test_node(
            chassis_id=None,
            driver='fake-driverz',
            owner='z')
        fake_db_node_alloced = db_utils.create_test_node(
            id=allocated_node_id,
            chassis_id=None,
            uuid='22e26c0b-03f2-4d2e-ae87-c02d7f33c000',
            driver='fake-driverz',
            owner='z')
        dbapi = db_api.get_instance()
        dbapi.update_allocation(fake_db_allocation['id'],
                                dict(node_id=allocated_node_id))
        fake_vif_port_id = "ee21d58f-5de2-4956-85ff-33935ea1ca00"
        fake_db_port = db_utils.create_test_port(
            node_id=fake_db_node['id'],
            internal_info={'tenant_vif_port_id': fake_vif_port_id})
        fake_db_portgroup = db_utils.create_test_portgroup(
            uuid="6eb02b44-18a3-4659-8c0b-8d2802581ae4",
            node_id=fake_db_node['id'])
        fake_db_chassis = db_utils.create_test_chassis(
            drivers=['fake-hardware', 'fake-driverz', 'fake-driver'])
        fake_db_deploy_template = db_utils.create_test_deploy_template()
        fake_db_conductor = db_utils.create_test_conductor()
        fake_db_volume_target = db_utils.create_test_volume_target(
            node_id=fake_db_node['id'])
        fake_db_volume_connector = db_utils.create_test_volume_connector(
            node_id=fake_db_node['id'])
        # Trait name aligns with create_test_node_trait.
        fake_trait = 'trait'
        fake_setting = 'FAKE_SETTING'
        db_utils.create_test_bios_setting(
            node_id=fake_db_node['id'],
            name=fake_setting,
            value=fake_setting)
        db_utils.create_test_node_trait(
            node_id=fake_db_node['id'])
        # Create a Fake Firmware Component BMC
        db_utils.create_test_firmware_component(
            node_id=fake_db_node['id'],
        )
        fake_history = db_utils.create_test_history(node_id=fake_db_node.id)
        fake_inventory = db_utils.create_test_inventory(
            node_id=fake_db_node.id)
        # dedicated node for portgroup addition test to avoid
        # false positives with test runners.
        db_utils.create_test_node(
            uuid='18a552fb-dcd2-43bf-9302-e4c93287be11')
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
            'history_ident': fake_history['uuid'],
            'node_inventory': fake_inventory,
        })


@ddt.ddt
class TestRBACModelBeforeScopes(TestRBACModelBeforeScopesBase):

    def _set_test_config(self):
        # NOTE(TheJulia): Sets default test conditions, in the event
        # oslo_policy defaults change.
        cfg.CONF.set_override('enforce_scope', False, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', False,
                              group='oslo_policy')

    @ddt.file_data('test_rbac_legacy.yaml')
    @ddt.unpack
    def test_rbac_legacy(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)


@ddt.ddt
class TestRBACScoped(TestRBACModelBeforeScopes):
    """Test Scoped RBAC access using our existing access policy."""

    def _set_test_config(self):
        # NOTE(TheJulia): This test class is as like a canary.
        # The operational intent is for it to kind of provide
        # a safety net as we're changing policy rules so we can
        # incremently disable the ones we *know* will no longer work
        # while we also enable the new ones in another test class with
        # the appropriate scope friendly chagnges. In other words, two
        # test changes will be needed for each which should also reduce
        # risk of accidental policy changes. It may just be Julia being
        # super risk-adverse, just let her roll with it and we will delete
        # this class later.
        # NOTE(TheJulia): This test class runs with test_rbac_legacy.yaml!
        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')

    @ddt.file_data('test_rbac_legacy.yaml')
    def test_scoped_canary(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)


@ddt.ddt
class TestRBACScopedRequests(TestRBACModelBeforeScopesBase):

    @ddt.file_data('test_rbac_system_scoped.yaml')
    @ddt.unpack
    def test_system_scoped(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)


@ddt.ddt
class TestRBACProjectScoped(TestACLBase):

    def setUp(self):
        super(TestRBACProjectScoped, self).setUp()

        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')

    def _create_test_data(self):
        owner_node_ident = '1ab63b9e-66d7-4cd7-8618-dddd0f9f7881'
        lessee_node_ident = '38d5abed-c585-4fce-a57e-a2ffc2a2ec6f'
        owner_project_id = '70e5e25a-2ca2-4cb1-8ae8-7d8739cee205'
        lessee_project_id = 'f11853c7-fa9c-4db3-a477-c9d8e0dbbf13'
        unowned_node = db_utils.create_test_node(chassis_id=None)

        # owned node - since the tests use the same node for
        # owner/lesse checks
        owned_node = db_utils.create_test_node(
            uuid=owner_node_ident,
            owner=owner_project_id,
            last_error='meow',
            reservation='lolcats')
        # invisible child node, rbac + project query enforcement
        # prevents it from being visible.
        db_utils.create_test_node(
            uuid='2b3b8adb-add7-4fd0-8e82-dcb714d848e7',
            parent_node=owned_node.uuid)
        # Child node which will appear in child node endpoint
        # queries.
        db_utils.create_test_node(
            uuid='3c3b8adb-edd7-3ed0-8e82-aab714d8411a',
            parent_node=owned_node.uuid,
            owner=owner_project_id)
        owned_node_port = db_utils.create_test_port(
            uuid='ebe30f19-358d-41e1-8d28-fd7357a0164c',
            node_id=owned_node['id'],
            address='00:00:00:00:00:01')
        db_utils.create_test_port(
            uuid='21a3c5a7-1e14-44dc-a9dd-0c84d5477a57',
            node_id=owned_node['id'],
            address='00:00:00:00:00:02')
        owner_pgroup = db_utils.create_test_portgroup(
            uuid='b16efcf3-2990-41a1-bc1d-5e2c16f3d5fc',
            node_id=owned_node['id'],
            name='magicfoo',
            address='01:03:09:ff:01:01')
        db_utils.create_test_volume_target(
            uuid='a265e2f0-e97f-4177-b1c0-8298add53086',
            node_id=owned_node['id'])
        db_utils.create_test_volume_connector(
            uuid='65ea0296-219b-4635-b0c8-a6e055da878d',
            node_id=owned_node['id'],
            connector_id='iqn.2012-06.org.openstack.magic')
        fake_owner_allocation = db_utils.create_test_allocation(
            node_id=owned_node['id'],
            owner=owner_project_id,
            resource_class="CUSTOM_TEST")
        owned_node_history = db_utils.create_test_history(
            node_id=owned_node.id)
        owned_node_inventory = db_utils.create_test_inventory(
            node_id=owned_node.id)

        # Leased nodes
        leased_node = db_utils.create_test_node(
            uuid=lessee_node_ident,
            owner=owner_project_id,
            lessee=lessee_project_id,
            last_error='meow',
            reservation='lolcats')
        fake_db_volume_target = db_utils.create_test_volume_target(
            node_id=leased_node['id'])
        fake_db_volume_connector = db_utils.create_test_volume_connector(
            node_id=leased_node['id'])
        fake_db_port = db_utils.create_test_port(
            node_id=leased_node['id'])
        fake_db_portgroup = db_utils.create_test_portgroup(
            node_id=leased_node['id'])
        fake_trait = 'CUSTOM_MEOW'
        fake_vif_port_id = "0e21d58f-5de2-4956-85ff-33935ea1ca01"
        fake_allocation_id = 61
        fake_leased_allocation = db_utils.create_test_allocation(
            id=fake_allocation_id,
            owner=lessee_project_id,
            resource_class="CUSTOM_LEASED")

        dbapi = db_api.get_instance()
        dbapi.update_allocation(fake_allocation_id,
                                dict(node_id=leased_node['id']))

        leased_node_history = db_utils.create_test_history(
            node_id=leased_node.id)
        leased_node_inventory = db_utils.create_test_inventory(
            node_id=leased_node.id)

        # Random objects that shouldn't be project visible
        other_node = db_utils.create_test_node(
            uuid='573208e5-cd41-4e26-8f06-ef44022b3793')
        other_port = db_utils.create_test_port(
            node_id=other_node['id'],
            uuid='abfd8dbb-1732-449a-b760-2224035c6b99',
            address='00:00:00:00:00:ff')
        other_pgroup = db_utils.create_test_portgroup(
            uuid='5810f41c-6585-41fc-b9c9-a94f50d421b5',
            node_id=other_node['id'],
            name='corgis_rule_the_world',
            address='ff:ff:ff:ff:ff:0f')

        self.format_data.update({
            'node_ident': unowned_node['uuid'],
            'owner_node_ident': owner_node_ident,
            'lessee_node_ident': lessee_node_ident,
            'allocated_node_ident': lessee_node_ident,
            'volume_target_ident': fake_db_volume_target['uuid'],
            'volume_connector_ident': fake_db_volume_connector['uuid'],
            'lessee_port_ident': fake_db_port['uuid'],
            'lessee_portgroup_ident': fake_db_portgroup['uuid'],
            'trait': fake_trait,
            'vif_ident': fake_vif_port_id,
            'ind_component': 'component',
            'ind_ident': 'magic_light',
            'owner_port_ident': owned_node_port['uuid'],
            'other_port_ident': other_port['uuid'],
            'owner_portgroup_ident': owner_pgroup['uuid'],
            'other_portgroup_ident': other_pgroup['uuid'],
            'driver_name': 'fake-driverz',
            'owner_allocation': fake_owner_allocation['uuid'],
            'lessee_allocation': fake_leased_allocation['uuid'],
            'owned_history_ident': owned_node_history['uuid'],
            'lessee_history_ident': leased_node_history['uuid'],
            'owned_inventory': owned_node_inventory,
            'leased_inventory': leased_node_inventory})

    @ddt.file_data('test_rbac_project_scoped.yaml')
    @ddt.unpack
    def test_project_scoped(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)
