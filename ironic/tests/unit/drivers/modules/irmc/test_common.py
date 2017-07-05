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

import mock

from oslo_config import cfg

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers import third_party_driver_mock_specs \
    as mock_specs
from ironic.tests.unit.objects import utils as obj_utils


class IRMCValidateParametersTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IRMCValidateParametersTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake_irmc',
            driver_info=db_utils.get_test_irmc_info())

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


class IRMCCommonMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IRMCCommonMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_irmc")
        self.info = db_utils.get_test_irmc_info()
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake_irmc',
            driver_info=self.info)

    @mock.patch.object(irmc_common, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    def test_get_irmc_client(self, mock_scci):
        self.info['irmc_port'] = 80
        self.info['irmc_auth_method'] = 'digest'
        self.info['irmc_client_timeout'] = 60
        mock_scci.get_client.return_value = 'get_client'
        returned_mock_scci_get_client = irmc_common.get_irmc_client(self.node)
        mock_scci.get_client.assert_called_with(
            self.info['irmc_address'],
            self.info['irmc_username'],
            self.info['irmc_password'],
            port=self.info['irmc_port'],
            auth_method=self.info['irmc_auth_method'],
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
        mock_scci.get_report.return_value = 'get_report'
        returned_mock_scci_get_report = irmc_common.get_irmc_report(self.node)
        mock_scci.get_report.assert_called_with(
            self.info['irmc_address'],
            self.info['irmc_username'],
            self.info['irmc_password'],
            port=self.info['irmc_port'],
            auth_method=self.info['irmc_auth_method'],
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
