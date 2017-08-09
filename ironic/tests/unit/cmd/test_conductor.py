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

from ironic.cmd import conductor
from ironic.tests.unit.db import base as db_base


class ConductorStartTestCase(db_base.DbTestCase):

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_defaults(self, log_mock):
        conductor.warn_about_unsafe_shred_parameters(cfg.CONF)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_zeros(self, log_mock):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 0, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', True,
                              'deploy')
        conductor.warn_about_unsafe_shred_parameters(cfg.CONF)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_random_no_zeros(self,
                                                                log_mock):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 1, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', False,
                              'deploy')
        conductor.warn_about_unsafe_shred_parameters(cfg.CONF)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_produces_a_warning(self,
                                                                   log_mock):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 0, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', False,
                              'deploy')
        conductor.warn_about_unsafe_shred_parameters(cfg.CONF)
        self.assertTrue(log_mock.warning.called)
