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

from unittest import mock

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

from ironic.common import exception
from ironic.common import keystone
from ironic.tests.base import TestCase


class KeystoneTestCase(TestCase):

    def setUp(self):
        super(KeystoneTestCase, self).setUp()
        self.test_group = 'test_group'
        self.cfg_fixture.conf.register_group(cfg.OptGroup(self.test_group))
        keystone.register_auth_opts(self.cfg_fixture.conf, self.test_group,
                                    service_type='vikings')
        self.config(auth_type='password',
                    group=self.test_group)
        # NOTE(pas-ha) this is due to auth_plugin options
        # being dynamically registered on first load,
        # but we need to set the config before
        plugin = ks_loading.get_plugin_loader('password')
        opts = ks_loading.get_auth_plugin_conf_options(plugin)
        self.cfg_fixture.register_opts(opts, group=self.test_group)
        self.config(auth_url='http://127.0.0.1:9898',
                    username='fake_user',
                    password='fake_pass',
                    project_name='fake_tenant',
                    group=self.test_group)

    def test_get_session(self):
        self.config(timeout=10, group=self.test_group)
        session = keystone.get_session(self.test_group, timeout=20)
        self.assertEqual(20, session.timeout)

    def test_get_auth(self):
        auth = keystone.get_auth(self.test_group)
        self.assertEqual('http://127.0.0.1:9898', auth.auth_url)

    def test_get_auth_fail(self):
        # NOTE(pas-ha) 'password' auth_plugin is used,
        # so when we set the required auth_url to None,
        # MissingOption is raised
        self.config(auth_url=None, group=self.test_group)
        self.assertRaises(exception.ConfigInvalid,
                          keystone.get_auth,
                          self.test_group)

    def test_get_adapter_from_config(self):
        self.config(valid_interfaces=['internal', 'public'],
                    group=self.test_group)
        session = keystone.get_session(self.test_group)
        adapter = keystone.get_adapter(self.test_group, session=session,
                                       interface='admin')
        self.assertEqual('admin', adapter.interface)
        self.assertEqual(session, adapter.session)

    @mock.patch('keystoneauth1.service_token.ServiceTokenAuthWrapper',
                autospec=True)
    @mock.patch('keystoneauth1.token_endpoint.Token', autospec=True)
    def test_get_service_auth(self, token_mock, service_auth_mock):
        ctxt = mock.Mock(spec=['auth_token'], auth_token='spam')
        mock_auth = mock.Mock()
        self.assertEqual(service_auth_mock.return_value,
                         keystone.get_service_auth(ctxt, 'ham', mock_auth))
        token_mock.assert_called_once_with('ham', 'spam')
        service_auth_mock.assert_called_once_with(
            user_auth=token_mock.return_value, service_auth=mock_auth)


class AuthConfTestCase(TestCase):

    def setUp(self):
        super(AuthConfTestCase, self).setUp()
        self.test_group = 'test_group'
        self.cfg_fixture.conf.register_group(cfg.OptGroup(self.test_group))
        keystone.register_auth_opts(self.cfg_fixture.conf, self.test_group)
        self.config(auth_type='password',
                    group=self.test_group)
        # NOTE(pas-ha) this is due to auth_plugin options
        # being dynamically registered on first load,
        # but we need to set the config before
        plugin = ks_loading.get_plugin_loader('password')
        opts = ks_loading.get_auth_plugin_conf_options(plugin)
        self.cfg_fixture.register_opts(opts, group=self.test_group)
        self.config(auth_url='http://127.0.0.1:9898',
                    username='fake_user',
                    password='fake_pass',
                    project_name='fake_tenant',
                    group=self.test_group)

    def test_add_auth_opts(self):
        opts = keystone.add_auth_opts([])
        # check that there is no duplicates
        names = {o.dest for o in opts}
        self.assertEqual(len(names), len(opts))
        # NOTE(pas-ha) checking for most standard auth and session ones only
        expected = {'timeout', 'insecure', 'cafile', 'certfile', 'keyfile',
                    'auth_type', 'auth_url', 'username', 'password',
                    'tenant_name', 'project_name', 'trust_id',
                    'domain_id', 'user_domain_id', 'project_domain_id'}
        self.assertTrue(expected.issubset(names))

    def test_os_service_types_alias(self):
        keystone.register_auth_opts(self.cfg_fixture.conf, 'barbican')
        self.assertEqual(self.cfg_fixture.conf.barbican.service_type,
                         'key-manager')
