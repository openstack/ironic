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

from unittest import mock

from oslo_config import cfg

from ironic.command import conductor
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

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_inconsistent_kernel_ramdisk_no_config(self, log_mock):
        # Test when all config dicts are empty (default state)
        conductor.warn_about_inconsistent_kernel_ramdisk(cfg.CONF)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_inconsistent_kernel_ramdisk_consistent(self, log_mock):
        # Test when kernel and ramdisk configs have matching architectures
        cfg.CONF.set_override('deploy_kernel_by_arch',
                              {'x86_64': 'kernel1', 'aarch64': 'kernel2'},
                              'conductor')
        cfg.CONF.set_override('deploy_ramdisk_by_arch',
                              {'x86_64': 'ramdisk1', 'aarch64': 'ramdisk2'},
                              'conductor')
        cfg.CONF.set_override('rescue_kernel_by_arch',
                              {'x86_64': 'rkernel1'},
                              'conductor')
        cfg.CONF.set_override('rescue_ramdisk_by_arch',
                              {'x86_64': 'rramdisk1'},
                              'conductor')
        conductor.warn_about_inconsistent_kernel_ramdisk(cfg.CONF)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_inconsistent_kernel_ramdisk_kernel_only(self,
                                                                log_mock):
        # Test when kernel has architectures that ramdisk doesn't
        cfg.CONF.set_override('deploy_kernel_by_arch',
                              {'x86_64': 'kernel1', 'aarch64': 'kernel2'},
                              'conductor')
        cfg.CONF.set_override('deploy_ramdisk_by_arch',
                              {'x86_64': 'ramdisk1'},
                              'conductor')
        conductor.warn_about_inconsistent_kernel_ramdisk(cfg.CONF)
        self.assertEqual(1, log_mock.warning.call_count)
        warning_call = log_mock.warning.call_args[0]
        # Check the warning message format and arguments
        self.assertIn('[conductor]%s', warning_call[0])
        self.assertEqual('deploy_kernel_by_arch', warning_call[1])
        self.assertEqual('aarch64', warning_call[2])
        self.assertEqual('deploy_ramdisk_by_arch', warning_call[3])
        self.assertEqual('provisioning', warning_call[4])

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_inconsistent_kernel_ramdisk_ramdisk_only(self,
                                                                 log_mock):
        # Test when ramdisk has architectures that kernel doesn't
        cfg.CONF.set_override('rescue_kernel_by_arch',
                              {'x86_64': 'kernel1'},
                              'conductor')
        cfg.CONF.set_override('rescue_ramdisk_by_arch',
                              {'x86_64': 'ramdisk1', 'ppc64le': 'ramdisk2'},
                              'conductor')
        conductor.warn_about_inconsistent_kernel_ramdisk(cfg.CONF)
        self.assertEqual(1, log_mock.warning.call_count)
        warning_call = log_mock.warning.call_args[0]
        # Check the warning message format and arguments
        self.assertIn('[conductor]%s', warning_call[0])
        self.assertEqual('rescue_ramdisk_by_arch', warning_call[1])
        self.assertEqual('ppc64le', warning_call[2])
        self.assertEqual('rescue_kernel_by_arch', warning_call[3])
        self.assertEqual('rescue', warning_call[4])

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_inconsistent_kernel_ramdisk_both_bad(self,
                                                             log_mock):
        # Test when both kernel and ramdisk have mismatched architectures
        cfg.CONF.set_override('deploy_kernel_by_arch',
                              {'x86_64': 'kernel1', 'aarch64': 'kernel2'},
                              'conductor')
        cfg.CONF.set_override('deploy_ramdisk_by_arch',
                              {'x86_64': 'ramdisk1', 'ppc64le': 'ramdisk2'},
                              'conductor')
        conductor.warn_about_inconsistent_kernel_ramdisk(cfg.CONF)
        self.assertEqual(2, log_mock.warning.call_count)
        # Check that both warnings were issued with correct parameters
        warning_args = [call[0] for call in log_mock.warning.call_args_list]
        # First warning about kernel_only (aarch64)
        self.assertEqual('deploy_kernel_by_arch', warning_args[0][1])
        self.assertEqual('aarch64', warning_args[0][2])
        # Second warning about ramdisk_only (ppc64le)
        self.assertEqual('deploy_ramdisk_by_arch', warning_args[1][1])
        self.assertEqual('ppc64le', warning_args[1][2])

    @mock.patch.object(conductor, 'LOG', autospec=True)
    def test_warn_about_inconsistent_kernel_ramdisk_multiple_configs(self,
                                                                     log_mock):
        # Test multiple config pairs with inconsistencies
        cfg.CONF.set_override('deploy_kernel_by_arch',
                              {'x86_64': 'kernel1', 'aarch64': 'kernel2'},
                              'conductor')
        cfg.CONF.set_override('deploy_ramdisk_by_arch',
                              {'x86_64': 'ramdisk1'},
                              'conductor')
        cfg.CONF.set_override('rescue_kernel_by_arch',
                              {'ppc64le': 'rkernel1'},
                              'conductor')
        cfg.CONF.set_override('rescue_ramdisk_by_arch',
                              {'ppc64le': 'rramdisk1', 's390x': 'rramdisk2'},
                              'conductor')
        conductor.warn_about_inconsistent_kernel_ramdisk(cfg.CONF)
        self.assertEqual(2, log_mock.warning.call_count)
        # Verify both deploy and rescue warnings were issued
        warning_args = [call[0] for call in log_mock.warning.call_args_list]
        # Check operation names in warnings
        operations = [args[4] for args in warning_args]
        self.assertIn('provisioning', operations)
        self.assertIn('rescue', operations)
