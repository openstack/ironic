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

from keystoneauth1 import exceptions as ksexception
from keystoneauth1 import identity as kaidentity
from keystoneauth1 import loading as kaloading
import mock
from oslo_config import cfg
from oslo_config import fixture

from ironic.common import exception
from ironic.common import keystone
from ironic.conf import auth as ironic_auth
from ironic.tests import base


class KeystoneTestCase(base.TestCase):

    def setUp(self):
        super(KeystoneTestCase, self).setUp()
        self.config(region_name='fake_region',
                    group='keystone')
        self.test_group = 'test_group'
        self.cfg_fixture.conf.register_group(cfg.OptGroup(self.test_group))
        ironic_auth.register_auth_opts(self.cfg_fixture.conf, self.test_group)
        self.config(auth_type='password',
                    group=self.test_group)
        # NOTE(pas-ha) this is due to auth_plugin options
        # being dynamically registered on first load,
        # but we need to set the config before
        plugin = kaloading.get_plugin_loader('password')
        opts = kaloading.get_auth_plugin_conf_options(plugin)
        self.cfg_fixture.register_opts(opts, group=self.test_group)
        self.config(auth_url='http://127.0.0.1:9898',
                    username='fake_user',
                    password='fake_pass',
                    project_name='fake_tenant',
                    group=self.test_group)

    def _set_config(self):
        self.cfg_fixture = self.useFixture(fixture.Config())
        self.addCleanup(cfg.CONF.reset)

    def test_get_url(self):
        fake_url = 'http://127.0.0.1:6385'
        mock_sess = mock.Mock()
        mock_sess.get_endpoint.return_value = fake_url
        res = keystone.get_service_url(mock_sess)
        mock_sess.get_endpoint.assert_called_with(
            interface='internal', region_name='fake_region',
            service_type='baremetal')
        self.assertEqual(fake_url, res)

    def test_get_url_failure(self):
        exc_map = (
            (ksexception.Unauthorized, exception.KeystoneUnauthorized),
            (ksexception.EndpointNotFound, exception.CatalogNotFound),
            (ksexception.EmptyCatalog, exception.CatalogNotFound),
            (ksexception.Unauthorized, exception.KeystoneUnauthorized),
        )
        for kexc, irexc in exc_map:
            mock_sess = mock.Mock()
            mock_sess.get_endpoint.side_effect = kexc
            self.assertRaises(irexc, keystone.get_service_url, mock_sess)

    def test_get_admin_auth_token(self):
        mock_sess = mock.Mock()
        mock_sess.get_token.return_value = 'fake_token'
        self.assertEqual('fake_token',
                         keystone.get_admin_auth_token(mock_sess))

    def test_get_admin_auth_token_failure(self):
        mock_sess = mock.Mock()
        mock_sess.get_token.side_effect = ksexception.Unauthorized
        self.assertRaises(exception.KeystoneUnauthorized,
                          keystone.get_admin_auth_token, mock_sess)

    def test_get_session(self):
        session = keystone.get_session(self.test_group)
        # NOTE(pas-ha) 'password' auth_plugin is used
        self.assertIsInstance(session.auth,
                              kaidentity.generic.password.Password)
        self.assertEqual('http://127.0.0.1:9898', session.auth.auth_url)

    def test_get_session_fail(self):
        # NOTE(pas-ha) 'password' auth_plugin is used,
        # so when we set the required auth_url to None,
        # MissingOption is raised
        self.config(auth_url=None, group=self.test_group)
        self.assertRaises(exception.ConfigInvalid,
                          keystone.get_session,
                          self.test_group)
