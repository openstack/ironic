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

    def test_get_service_url_with_interface(self):
        session = mock.Mock()
        session.get_endpoint.return_value = 'spam'
        params = {'interface': 'admin', 'ham': 'eggs'}
        self.assertEqual('spam', keystone.get_service_url(session, **params))
        session.get_endpoint.assert_called_once_with(**params)

    def test_get_service_url_internal(self):
        session = mock.Mock()
        session.get_endpoint.return_value = 'spam'
        params = {'ham': 'eggs'}
        self.assertEqual('spam', keystone.get_service_url(session, **params))
        session.get_endpoint.assert_called_once_with(interface='internal',
                                                     **params)

    def test_get_service_url_internal_fail(self):
        session = mock.Mock()
        session.get_endpoint.side_effect = [ksexception.EndpointNotFound(),
                                            'spam']
        params = {'ham': 'eggs'}
        self.assertEqual('spam', keystone.get_service_url(session, **params))
        session.get_endpoint.assert_has_calls([
            mock.call(interface='internal', **params),
            mock.call(interface='public', **params)])
