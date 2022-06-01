# Copyright 2015 FUJITSU LIMITED
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Test class for common methods used by iRMC modules.
"""

import os
from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers import third_party_driver_mock_specs \
    as mock_specs
from ironic.tests.unit.objects import utils as obj_utils


class BaseIRMCTest(db_base.DbTestCase):

    boot_interface = 'irmc-pxe'

    def setUp(self):
        super(BaseIRMCTest, self).setUp()
        self.config(enabled_hardware_types=['irmc', 'fake-hardware'],
                    enabled_power_interfaces=['irmc', 'fake'],
                    enabled_management_interfaces=['irmc', 'fake'],
                    enabled_bios_interfaces=['irmc', 'no-bios', 'fake'],
                    enabled_boot_interfaces=[self.boot_interface, 'fake'],
                    enabled_inspect_interfaces=['irmc', 'no-inspect', 'fake'])
        self.info = db_utils.get_test_irmc_info()
        self.node = obj_utils.create_test_node(
            self.context,
            driver='irmc',
            boot_interface=self.boot_interface,
            driver_info=self.info,
            uuid=uuidutils.generate_uuid())


class IRMCValidateParametersTestCase(BaseIRMCTest):

    def test_parse_driver_info(self):
        info = irmc_common.parse_driver_info(self.node)

        self.assertEqual('1.2.3.4', info['irmc_address'])
        self.assertEqual('admin0', info['irmc_username'])
        self.assertEqual('fake0', info['irmc_password'])
        self.assertEqual(60, info['irmc_client_timeout'])
        self.assertEqual(80, info['irmc_port'])
        self.assertEqual('digest', info['irmc_auth_method'])
        self.assertEqual('ipmitool', info['irmc_sensor_method'])
        self.assertEqual('v2c', info['irmc_snmp_version'])
        self.assertEqual(161, info['irmc_snmp_port'])
        self.assertEqual('public', info['irmc_snmp_community'])
        self.assertFalse(info['irmc_snmp_security'])
        self.assertTrue(info['irmc_verify_ca'])

    def test_parse_driver_option_default(self):
        self.node.driver_info = {
            "irmc_address": "1.2.3.4",
            "irmc_username": "admin0",
            "irmc_password": "fake0",
        }
        info = irmc_common.parse_driver_info(self.node)

        self.assertEqual('basic', info['irmc_auth_method'])
        self.assertEqual(443, info['irmc_port'])
        self.assertEqual(60, info['irmc_client_timeout'])
        self.assertEqual('ipmitool', info['irmc_sensor_method'])
        self.assertEqual(True, info['irmc_verify_ca'])

    def test_parse_driver_info_missing_address(self):
        del self.node.driver_info['irmc_address']
        self.assertRaises(exception.MissingParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_username(self):
        del self.node.driver_info['irmc_username']
        self.assertRaises(exception.MissingParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_password(self):
        del self.node.driver_info['irmc_password']
        self.assertRaises(exception.MissingParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_timeout(self):
        self.node.driver_info['irmc_client_timeout'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_port(self):
        self.node.driver_info['irmc_port'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_auth_method(self):
        self.node.driver_info['irmc_auth_method'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_sensor_method(self):
        self.node.driver_info['irmc_sensor_method'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_multiple_params(self):
        del self.node.driver_info['irmc_password']
        del self.node.driver_info['irmc_address']
        e = self.assertRaises(exception.MissingParameterValue,
                              irmc_common.parse_driver_info, self.node)
        self.assertIn('irmc_password', str(e))
        self.assertIn('irmc_address', str(e))

    def test_parse_driver_info_invalid_snmp_version(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3x'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_port(self):
        self.node.driver_info['irmc_snmp_port'] = '161'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_community(self):
        self.node.driver_info['irmc_snmp_version'] = 'v2c'
        self.node.driver_info['irmc_snmp_community'] = 100
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_security(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_security'] = 100
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_empty_snmp_security(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_security'] = ''
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    @mock.patch.object(os.path, 'isabs', return_value=True, autospec=True)
    @mock.patch.object(os.path, 'isdir', return_value=True, autospec=True)
    def test_parse_driver_info_dir_path_verify_ca(self, mock_isdir,
                                                  mock_isabs):
        fake_path = 'absolute/path/to/a/valid/CA'
        self.node.driver_info['irmc_verify_ca'] = fake_path
        info = irmc_common.parse_driver_info(self.node)
        self.assertEqual(fake_path, info['irmc_verify_ca'])
        mock_isdir.assert_called_once_with(fake_path)
        mock_isabs.assert_called_once_with(fake_path)

    @mock.patch.object(os.path, 'isabs', return_value=True, autospec=True)
    @mock.patch.object(os.path, 'isfile', return_value=True, autospec=True)
    def test_parse_driver_info_file_path_verify_ca(self, mock_isfile,
                                                   mock_isabs):
        fake_path = 'absolute/path/to/a/valid/ca.pem'
        self.node.driver_info['irmc_verify_ca'] = fake_path
        info = irmc_common.parse_driver_info(self.node)
        self.assertEqual(fake_path, info['irmc_verify_ca'])
        mock_isfile.assert_called_once_with(fake_path)
        mock_isabs.assert_called_once_with(fake_path)

    def test_parse_driver_info_string_bool_verify_ca(self):
        self.node.driver_info['irmc_verify_ca'] = "False"
        info = irmc_common.parse_driver_info(self.node)
        self.assertFalse(info['irmc_verify_ca'])

    def test_parse_driver_info_invalid_verify_ca(self):
        self.node.driver_info['irmc_verify_ca'] = "1234"
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)
        self.node.driver_info['irmc_verify_ca'] = 1234
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)


class IRMCCommonMethodsTestCase(BaseIRMCTest):

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_client_cert_support_http(self, mock_scci,
                                               mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.2', '0.8.3.1', '0.9.4', '0.10.1', '0.10.2',
                             '0.11.3', '0.11.4', '0.12.0', '0.12.1']
        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 80
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                self.info['irmc_verify_ca'] = True
                mock_scci.get_client.return_value = 'get_client'
                returned_mock_scci_get_client = irmc_common.get_irmc_client(
                    self.node)
                mock_scci.get_client.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    verify=self.info['irmc_verify_ca'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_client', returned_mock_scci_get_client)
                mock_LOG.warning.assert_not_called()
                mock_LOG.warning.reset_mock()

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_client_cert_support_https(self, mock_scci,
                                                mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.2', '0.8.3.1', '0.9.4', '0.10.1', '0.10.2',
                             '0.11.3', '0.11.4', '0.12.0', '0.12.1']
        self.node.driver_info = {
            "irmc_address": "1.2.3.4",
            "irmc_username": "admin0",
            "irmc_password": "fake0",
            "irmc_port": "443",
            "irmc_auth_method": "digest",
        }

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 443
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                self.info['irmc_verify_ca'] = True
                mock_scci.get_client.return_value = 'get_client'
                returned_mock_scci_get_client = irmc_common.get_irmc_client(
                    self.node)
                mock_scci.get_client.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    verify=self.info['irmc_verify_ca'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_client', returned_mock_scci_get_client)
                mock_LOG.warning.assert_not_called()
                mock_LOG.warning.reset_mock()

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_client_no_cert_support_http(self, mock_scci,
                                                  mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.0', '0.8.1', '0.9.0', '0.9.3', '0.10.0',
                             '0.11.2']

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 80
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                mock_scci.get_client.return_value = 'get_client'
                returned_mock_scci_get_client = irmc_common.get_irmc_client(
                    self.node)
                mock_scci.get_client.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_client', returned_mock_scci_get_client)
                mock_LOG.warning.assert_not_called()
                mock_LOG.warning.reset_mock()

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_client_no_cert_support_https(self, mock_scci,
                                                   mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.0', '0.8.1', '0.9.0', '0.9.3', '0.10.0',
                             '0.11.2']
        self.node.driver_info = {
            "irmc_address": "1.2.3.4",
            "irmc_username": "admin0",
            "irmc_password": "fake0",
            "irmc_port": "443",
            "irmc_auth_method": "digest",
        }

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 443
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                mock_scci.get_client.return_value = 'get_client'
                returned_mock_scci_get_client = irmc_common.get_irmc_client(
                    self.node)
                mock_scci.get_client.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_client', returned_mock_scci_get_client)
                mock_LOG.warning.assert_called_once()
                mock_LOG.warning.reset_mock()

    def test_update_ipmi_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ipmi_info = {
                "ipmi_address": "1.2.3.4",
                "ipmi_username": "admin0",
                "ipmi_password": "fake0",
            }
            task.node.driver_info = self.info
            irmc_common.update_ipmi_properties(task)
            actual_info = task.node.driver_info
            expected_info = dict(self.info, **ipmi_info)
            self.assertEqual(expected_info, actual_info)

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_report_cert_support_http(self, mock_scci,
                                               mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.2', '0.8.3.1', '0.9.4', '0.10.1', '0.10.2',
                             '0.11.3', '0.11.4', '0.12.0', '0.12.1']

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 80
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                self.info['irmc_verify_ca'] = True
                mock_scci.get_report.return_value = 'get_report'
                returned_mock_scci_get_report = irmc_common.get_irmc_report(
                    self.node)
                mock_scci.get_report.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    verify=self.info['irmc_verify_ca'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_report', returned_mock_scci_get_report)
                mock_LOG.warning.assert_not_called()
                mock_LOG.warning.reset_mock()

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_report_cert_support_https(self, mock_scci,
                                                mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.2', '0.8.3.1', '0.9.4', '0.10.1', '0.10.2',
                             '0.11.3', '0.11.4', '0.12.0', '0.12.1']
        self.node.driver_info = {
            "irmc_address": "1.2.3.4",
            "irmc_username": "admin0",
            "irmc_password": "fake0",
            "irmc_port": "443",
            "irmc_auth_method": "digest",
        }

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 443
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                self.info['irmc_verify_ca'] = True
                mock_scci.get_report.return_value = 'get_report'
                returned_mock_scci_get_report = irmc_common.get_irmc_report(
                    self.node)
                mock_scci.get_report.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    verify=self.info['irmc_verify_ca'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_report', returned_mock_scci_get_report)
                mock_LOG.warning.assert_not_called()
                mock_LOG.warning.reset_mock()

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_report_no_cert_support_http(self, mock_scci,
                                                  mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.0', '0.8.1', '0.9.0', '0.9.3', '0.10.0',
                             '0.11.2']

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 80
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                mock_scci.get_report.return_value = 'get_report'
                returned_mock_scci_get_report = irmc_common.get_irmc_report(
                    self.node)
                mock_scci.get_report.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_report', returned_mock_scci_get_report)
                mock_LOG.warning.assert_not_called()
                mock_LOG.warning.reset_mock()

    @mock.patch.object(irmc_common, 'LOG', autospec=True)
    @mock.patch.object(irmc_common, 'scci_mod', spec_set=['__version__'])
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_report_no_cert_support_https(self, mock_scci,
                                                   mock_scciclient, mock_LOG):
        scci_version_list = ['0.8.0', '0.8.1', '0.9.0', '0.9.3', '0.10.0',
                             '0.11.2']
        self.node.driver_info = {
            "irmc_address": "1.2.3.4",
            "irmc_username": "admin0",
            "irmc_password": "fake0",
            "irmc_port": "443",
            "irmc_auth_method": "digest",
        }

        for ver in scci_version_list:
            with self.subTest(ver=ver):
                mock_scciclient.__version__ = ver
                self.info['irmc_port'] = 443
                self.info['irmc_auth_method'] = 'digest'
                self.info['irmc_client_timeout'] = 60
                mock_scci.get_report.return_value = 'get_report'
                returned_mock_scci_get_report = irmc_common.get_irmc_report(
                    self.node)
                mock_scci.get_report.assert_called_with(
                    self.info['irmc_address'],
                    self.info['irmc_username'],
                    self.info['irmc_password'],
                    port=self.info['irmc_port'],
                    auth_method=self.info['irmc_auth_method'],
                    client_timeout=self.info['irmc_client_timeout'])
                self.assertEqual('get_report', returned_mock_scci_get_report)
                mock_LOG.warning.assert_called_once()
                mock_LOG.warning.reset_mock()

    def test_out_range_port(self):
        self.assertRaises(ValueError, cfg.CONF.set_override,
                          'port', 60, 'irmc')

    def test_out_range_auth_method(self):
        self.assertRaises(ValueError, cfg.CONF.set_override,
                          'auth_method', 'fake', 'irmc')

    def test_out_range_sensor_method(self):
        self.assertRaises(ValueError, cfg.CONF.set_override,
                          'sensor_method', 'fake', 'irmc')

    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    def test_set_secure_boot_mode_enable(self, mock_elcm):
        mock_elcm.set_secure_boot_mode.return_value = 'set_secure_boot_mode'
        info = irmc_common.parse_driver_info(self.node)
        irmc_common.set_secure_boot_mode(self.node, True)
        mock_elcm.set_secure_boot_mode.assert_called_once_with(
            info, True)

    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    def test_set_secure_boot_mode_disable(self, mock_elcm):
        mock_elcm.set_secure_boot_mode.return_value = 'set_secure_boot_mode'
        info = irmc_common.parse_driver_info(self.node)
        irmc_common.set_secure_boot_mode(self.node, False)
        mock_elcm.set_secure_boot_mode.assert_called_once_with(
            info, False)

    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_set_secure_boot_mode_fail(self, mock_scci, mock_elcm):
        irmc_common.scci.SCCIError = Exception
        mock_elcm.set_secure_boot_mode.side_effect = Exception
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_common.set_secure_boot_mode,
                              task.node, True)
            info = irmc_common.parse_driver_info(task.node)
            mock_elcm.set_secure_boot_mode.assert_called_once_with(
                info, True)
