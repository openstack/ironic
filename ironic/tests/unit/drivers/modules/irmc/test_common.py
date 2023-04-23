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
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules import snmp
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers import third_party_driver_mock_specs \
    as mock_specs
from ironic.tests.unit.objects import utils as obj_utils


class BaseIRMCTest(db_base.DbTestCase):

    boot_interface = 'irmc-pxe'
    inspect_interface = 'irmc'
    power_interface = 'irmc'

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
            inspect_interface=self.inspect_interface,
            power_interface=self.power_interface,
            driver_info=self.info,
            uuid=uuidutils.generate_uuid())


class IRMCValidateParametersTestCase(BaseIRMCTest):

    @mock.patch.object(utils, 'is_fips_enabled',
                       return_value=False, autospec=True)
    def test_parse_driver_info(self, mock_check_fips):
        info = irmc_common.parse_driver_info(self.node)

        self.assertEqual('1.2.3.4', info['irmc_address'])
        self.assertEqual('admin0', info['irmc_username'])
        self.assertEqual('fake0', info['irmc_password'])
        self.assertEqual(60, info['irmc_client_timeout'])
        self.assertEqual(80, info['irmc_port'])
        self.assertEqual('digest', info['irmc_auth_method'])
        self.assertEqual('ipmitool', info['irmc_sensor_method'])
        self.assertEqual(snmp.SNMP_V2C, info['irmc_snmp_version'])
        self.assertEqual(161, info['irmc_snmp_port'])
        self.assertEqual('public', info['irmc_snmp_community'])
        self.assertTrue(info['irmc_verify_ca'])

    @mock.patch.object(utils, 'is_fips_enabled',
                       return_value=False, autospec=True)
    def test_parse_snmp_driver_info_with_snmp(self, mock_check_fips):
        test_list = [{'interfaces': [{'interface': 'inspect_interface',
                                      'impl': 'irmc'},
                                     {'interface': 'power_interface',
                                      'impl': 'irmc'}],
                      'snmp': True},
                     {'interfaces': [{'interface': 'inspect_interface',
                                      'impl': 'inspector'},
                                     {'interface': 'power_interface',
                                      'impl': 'irmc'}],
                      'snmp': True},
                     {'interfaces': [{'interface': 'inspect_interface',
                                      'impl': 'irmc'},
                                     {'interface': 'power_interface',
                                      'impl': 'ipmitool'}],
                      'snmp': True},
                     {'interfaces': [{'interface': 'inspect_interface',
                                      'impl': 'inspector'},
                                     {'interface': 'power_interface',
                                      'impl': 'ipmitool'}],
                      'snmp': False}
                     ]

        for t_conf in test_list:
            with self.subTest(t_conf=t_conf):
                for int_conf in t_conf['interfaces']:
                    setattr(self.node, int_conf['interface'], int_conf['impl'])
                irmc_common.parse_driver_info(self.node)

                if t_conf['snmp']:
                    mock_check_fips.assert_called()
                else:
                    mock_check_fips.assert_not_called()

                mock_check_fips.reset_mock()

    def test_parse_driver_info_snmpv3(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        info = irmc_common.parse_driver_info(self.node)

        self.assertEqual('1.2.3.4', info['irmc_address'])
        self.assertEqual('admin0', info['irmc_username'])
        self.assertEqual('fake0', info['irmc_password'])
        self.assertEqual(60, info['irmc_client_timeout'])
        self.assertEqual(80, info['irmc_port'])
        self.assertEqual('digest', info['irmc_auth_method'])
        self.assertEqual('ipmitool', info['irmc_sensor_method'])
        self.assertEqual(snmp.SNMP_V3, info['irmc_snmp_version'])
        self.assertEqual(161, info['irmc_snmp_port'])
        self.assertEqual('public', info['irmc_snmp_community'])
        self.assertEqual('admin0', info['irmc_snmp_user'])
        self.assertEqual(snmp.snmp_auth_protocols['sha'],
                         info['irmc_snmp_auth_proto'])
        self.assertEqual('valid_key', info['irmc_snmp_auth_password'])
        self.assertEqual(snmp.snmp_priv_protocols['aes'],
                         info['irmc_snmp_priv_proto'])
        self.assertEqual('valid_key', info['irmc_snmp_priv_password'])

    @mock.patch.object(utils, 'is_fips_enabled',
                       return_value=False, autospec=True)
    def test_parse_driver_option_default(self, mock_check_fips):
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

    @mock.patch.object(utils, 'is_fips_enabled',
                       return_value=True, autospec=True)
    def test_parse_driver_info_invalid_snmp_version_fips(self,
                                                         mock_check_fips):
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)
        self.assertEqual(1, mock_check_fips.call_count)

    def test_parse_driver_info_invalid_snmp_port(self):
        self.node.driver_info['irmc_snmp_port'] = '161p'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_community(self):
        self.node.driver_info['irmc_snmp_version'] = 'v2c'
        self.node.driver_info['irmc_snmp_community'] = 100
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_snmp_user(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.assertRaises(exception.MissingParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_snmp_auth_password(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.assertRaises(exception.MissingParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_snmp_priv_password(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.assertRaises(exception.MissingParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_using_snmp_security(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_security'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        info = irmc_common.parse_driver_info(self.node)
        self.assertEqual('admin0', info['irmc_snmp_user'])

    def test_parse_driver_info_invalid_snmp_security(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_security'] = 100
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_user(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 100
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_auth_password(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 100
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_short_snmp_auth_password(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'short'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_priv_password(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 100
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_short_snmp_priv_password(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'short'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_auth_proto(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_auth_proto'] = 'invalid'
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_common.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_snmp_priv_proto(self):
        self.node.driver_info['irmc_snmp_version'] = 'v3'
        self.node.driver_info['irmc_snmp_user'] = 'admin0'
        self.node.driver_info['irmc_snmp_auth_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_password'] = 'valid_key'
        self.node.driver_info['irmc_snmp_priv_proto'] = 'invalid'
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

    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_client(self, mock_scci):
        self.info['irmc_port'] = 80
        self.info['irmc_auth_method'] = 'digest'
        self.info['irmc_client_timeout'] = 60
        self.info['irmc_verify_ca'] = True
        mock_scci.get_client.return_value = 'get_client'
        returned_mock_scci_get_client = irmc_common.get_irmc_client(self.node)
        mock_scci.get_client.assert_called_with(
            self.info['irmc_address'],
            self.info['irmc_username'],
            self.info['irmc_password'],
            port=self.info['irmc_port'],
            auth_method=self.info['irmc_auth_method'],
            verify=self.info['irmc_verify_ca'],
            client_timeout=self.info['irmc_client_timeout'])
        self.assertEqual('get_client', returned_mock_scci_get_client)

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

    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_report(self, mock_scci):
        self.info['irmc_port'] = 80
        self.info['irmc_auth_method'] = 'digest'
        self.info['irmc_client_timeout'] = 60
        self.info['irmc_verify_ca'] = True
        mock_scci.get_report.return_value = 'get_report'
        returned_mock_scci_get_report = irmc_common.get_irmc_report(self.node)
        mock_scci.get_report.assert_called_with(
            self.info['irmc_address'],
            self.info['irmc_username'],
            self.info['irmc_password'],
            port=self.info['irmc_port'],
            auth_method=self.info['irmc_auth_method'],
            verify=self.info['irmc_verify_ca'],
            client_timeout=self.info['irmc_client_timeout'])
        self.assertEqual('get_report', returned_mock_scci_get_report)

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

    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    def test_check_elcm_license_success_with_200(self, elcm_mock):
        elcm_req_mock = elcm_mock.elcm_request
        json_data = ('{ "eLCMStatus" : { "EnabledAndLicenced" : "true" , '
                     '"SDCardMounted" : "false" } }')
        func_return_value = {'active': True, 'status_code': 200}
        response_mock = elcm_req_mock.return_value
        response_mock.status_code = 200
        response_mock.text = json_data
        self.assertEqual(irmc_common.check_elcm_license(self.node),
                         func_return_value)

    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    def test_check_elcm_license_success_with_500(self, elcm_mock):
        elcm_req_mock = elcm_mock.elcm_request
        json_data = ''
        func_return_value = {'active': False, 'status_code': 500}
        response_mock = elcm_req_mock.return_value
        response_mock.status_code = 500
        response_mock.text = json_data
        self.assertEqual(irmc_common.check_elcm_license(self.node),
                         func_return_value)

    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    def test_check_elcm_license_fail_invalid_json(self, elcm_mock, scci_mock):
        scci_mock.SCCIError = Exception
        elcm_req_mock = elcm_mock.elcm_request
        json_data = ''
        response_mock = elcm_req_mock.return_value
        response_mock.status_code = 200
        response_mock.text = json_data
        self.assertRaises(exception.IRMCOperationError,
                          irmc_common.check_elcm_license, self.node)

    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'elcm',
                       spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
    def test_check_elcm_license_fail_elcm_error(self, elcm_mock, scci_mock):
        scci_mock.SCCIError = Exception
        elcm_req_mock = elcm_mock.elcm_request
        elcm_req_mock.side_effect = scci_mock.SCCIError
        self.assertRaises(exception.IRMCOperationError,
                          irmc_common.check_elcm_license, self.node)

    @mock.patch.object(irmc_common, 'get_irmc_report', autospec=True)
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_set_irmc_version_success(self, scci_mock, get_report_mock):
        version_str = 'iRMC S6/2.00'
        scci_mock.get_irmc_version_str.return_value = version_str.split('/')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            irmc_common.set_irmc_version(task)
            self.assertEqual(version_str,
                             task.node.driver_internal_info['irmc_fw_version'])

    @mock.patch.object(irmc_common, 'get_irmc_report', autospec=True)
    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_set_irmc_version_fail(self, scci_mock, get_report_mock):
        scci_mock.SCCIError = Exception
        get_report_mock.side_effect = scci_mock.SCCIError
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_common.set_irmc_version, task)

    def test_within_version_ranges_success(self):
        self.node.set_driver_internal_info('irmc_fw_version', 'iRMC S6/2.00')
        ver_range_list = [
            {'4': {'upper': '1.05'},
             '6': {'min': '1.95', 'upper': '2.01'}
             },
            {'4': {'upper': '1.05'},
             '6': {'min': '1.95', 'upper': None}
             },
            {'4': {'upper': '1.05'},
             '6': {'min': '1.95'}
             },
            {'4': {'upper': '1.05'},
             '6': {}
             },
            {'4': {'upper': '1.05'},
             '6': None
             }]
        for range_dict in ver_range_list:
            with self.subTest():
                self.assertTrue(irmc_common.within_version_ranges(self.node,
                                                                  range_dict))

    def test_within_version_ranges_success_out_range(self):
        self.node.set_driver_internal_info('irmc_fw_version', 'iRMC S6/2.00')
        ver_range_list = [
            {'4': {'upper': '1.05'},
             '6': {'min': '1.95', 'upper': '2.00'}
             },
            {'4': {'upper': '1.05'},
             '6': {'min': '1.95', 'upper': '1.99'}
             },
            {'4': {'upper': '1.05'},
             }]
        for range_dict in ver_range_list:
            with self.subTest():
                self.assertFalse(irmc_common.within_version_ranges(self.node,
                                                                   range_dict))

    def test_within_version_ranges_fail_no_match(self):
        self.node.set_driver_internal_info('irmc_fw_version', 'ver/2.00')
        ver_range = {
            '4': {'upper': '1.05'},
            '6': {'min': '1.95', 'upper': '2.01'}
        }
        self.assertFalse(irmc_common.within_version_ranges(self.node,
                                                           ver_range))

    def test_within_version_ranges_fail_no_version_set(self):
        ver_range = {
            '4': {'upper': '1.05'},
            '6': {'min': '1.95', 'upper': '2.01'}
        }
        self.assertFalse(irmc_common.within_version_ranges(self.node,
                                                           ver_range))
