# Copyright 2013,2014 Cray Inc
#
# All Rights Reserved.
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

"""Test class for SNMP power driver module."""

import time

import mock
from oslo_config import cfg
from pysnmp.entity.rfc3413.oneliner import cmdgen
from pysnmp import error as snmp_error

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import snmp as snmp
from ironic.tests import base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF
INFO_DICT = db_utils.get_test_snmp_info()


@mock.patch.object(cmdgen, 'CommandGenerator', autospec=True)
class SNMPClientTestCase(base.TestCase):
    def setUp(self):
        super(SNMPClientTestCase, self).setUp()
        self.address = '1.2.3.4'
        self.port = '6700'
        self.oid = 'oid'
        self.value = 'value'

    def test___init__(self, mock_cmdgen):
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V1)
        mock_cmdgen.assert_called_once_with()
        self.assertEqual(self.address, client.address)
        self.assertEqual(self.port, client.port)
        self.assertEqual(snmp.SNMP_V1, client.version)
        self.assertIsNone(client.community)
        self.assertNotIn('security', client.__dict__)
        self.assertEqual(mock_cmdgen.return_value, client.cmd_gen)

    @mock.patch.object(cmdgen, 'CommunityData', autospec=True)
    def test__get_auth_v1(self, mock_community, mock_cmdgen):
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V1)
        client._get_auth()
        mock_cmdgen.assert_called_once_with()
        mock_community.assert_called_once_with(client.community, mpModel=0)

    @mock.patch.object(cmdgen, 'UsmUserData', autospec=True)
    def test__get_auth_v3(self, mock_user, mock_cmdgen):
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        client._get_auth()
        mock_cmdgen.assert_called_once_with()
        mock_user.assert_called_once_with(client.security)

    @mock.patch.object(cmdgen, 'UdpTransportTarget', autospec=True)
    def test__get_transport(self, mock_transport, mock_cmdgen):
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        client._get_transport()
        mock_cmdgen.assert_called_once_with()
        mock_transport.assert_called_once_with(
            (client.address, client.port),
            retries=CONF.snmp.udp_transport_retries,
            timeout=CONF.snmp.udp_transport_timeout)

    @mock.patch.object(cmdgen, 'UdpTransportTarget', autospec=True)
    def test__get_transport_err(self, mock_transport, mock_cmdgen):
        mock_transport.side_effect = snmp_error.PySnmpError
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(snmp_error.PySnmpError, client._get_transport)
        mock_cmdgen.assert_called_once_with()
        mock_transport.assert_called_once_with(
            (client.address, client.port),
            retries=CONF.snmp.udp_transport_retries,
            timeout=CONF.snmp.udp_transport_timeout)

    @mock.patch.object(cmdgen, 'UdpTransportTarget', autospec=True)
    def test__get_transport_custom_timeout(self, mock_transport, mock_cmdgen):
        self.config(udp_transport_timeout=2.0, group='snmp')
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        client._get_transport()
        mock_cmdgen.assert_called_once_with()
        mock_transport.assert_called_once_with((client.address, client.port),
                                               retries=5, timeout=2.0)

    @mock.patch.object(cmdgen, 'UdpTransportTarget', autospec=True)
    def test__get_transport_custom_retries(self, mock_transport, mock_cmdgen):
        self.config(udp_transport_retries=10, group='snmp')
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        client._get_transport()
        mock_cmdgen.assert_called_once_with()
        mock_transport.assert_called_once_with((client.address, client.port),
                                               retries=10, timeout=1.0)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_get(self, mock_auth, mock_transport, mock_cmdgen):
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.getCmd.return_value = ("", None, 0, [var_bind])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        val = client.get(self.oid)
        self.assertEqual(var_bind[1], val)
        mock_cmdgenerator.getCmd.assert_called_once_with(mock.ANY, mock.ANY,
                                                         self.oid)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_get_next(self, mock_auth, mock_transport, mock_cmdgen):
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.nextCmd.return_value = (
            "", None, 0, [[var_bind, var_bind]])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        val = client.get_next(self.oid)
        self.assertEqual([self.value, self.value], val)
        mock_cmdgenerator.nextCmd.assert_called_once_with(mock.ANY, mock.ANY,
                                                          self.oid)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_get_err_transport(self, mock_auth, mock_transport, mock_cmdgen):
        mock_transport.side_effect = snmp_error.PySnmpError
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.getCmd.return_value = ("engine error", None, 0,
                                                 [var_bind])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(exception.SNMPFailure, client.get, self.oid)
        self.assertFalse(mock_cmdgenerator.getCmd.called)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_get_next_err_transport(self, mock_auth, mock_transport,
                                    mock_cmdgen):
        mock_transport.side_effect = snmp_error.PySnmpError
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.nextCmd.return_value = ("engine error", None, 0,
                                                  [[var_bind, var_bind]])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(exception.SNMPFailure, client.get_next, self.oid)
        self.assertFalse(mock_cmdgenerator.nextCmd.called)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_get_err_engine(self, mock_auth, mock_transport, mock_cmdgen):
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.getCmd.return_value = ("engine error", None, 0,
                                                 [var_bind])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(exception.SNMPFailure, client.get, self.oid)
        mock_cmdgenerator.getCmd.assert_called_once_with(mock.ANY, mock.ANY,
                                                         self.oid)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_get_next_err_engine(self, mock_auth, mock_transport, mock_cmdgen):
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.nextCmd.return_value = ("engine error", None, 0,
                                                  [[var_bind, var_bind]])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(exception.SNMPFailure, client.get_next, self.oid)
        mock_cmdgenerator.nextCmd.assert_called_once_with(mock.ANY, mock.ANY,
                                                          self.oid)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_set(self, mock_auth, mock_transport, mock_cmdgen):
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.setCmd.return_value = ("", None, 0, [var_bind])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        client.set(self.oid, self.value)
        mock_cmdgenerator.setCmd.assert_called_once_with(mock.ANY, mock.ANY,
                                                         var_bind)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_set_err_transport(self, mock_auth, mock_transport, mock_cmdgen):
        mock_transport.side_effect = snmp_error.PySnmpError
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.setCmd.return_value = ("engine error", None, 0,
                                                 [var_bind])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(exception.SNMPFailure,
                          client.set, self.oid, self.value)
        self.assertFalse(mock_cmdgenerator.setCmd.called)

    @mock.patch.object(snmp.SNMPClient, '_get_transport', autospec=True)
    @mock.patch.object(snmp.SNMPClient, '_get_auth', autospec=True)
    def test_set_err_engine(self, mock_auth, mock_transport, mock_cmdgen):
        var_bind = (self.oid, self.value)
        mock_cmdgenerator = mock_cmdgen.return_value
        mock_cmdgenerator.setCmd.return_value = ("engine error", None, 0,
                                                 [var_bind])
        client = snmp.SNMPClient(self.address, self.port, snmp.SNMP_V3)
        self.assertRaises(exception.SNMPFailure,
                          client.set, self.oid, self.value)
        mock_cmdgenerator.setCmd.assert_called_once_with(mock.ANY, mock.ANY,
                                                         var_bind)


class SNMPValidateParametersTestCase(db_base.DbTestCase):

    def _get_test_node(self, driver_info):
        return obj_utils.get_test_node(
            self.context,
            driver_info=driver_info)

    def test__parse_driver_info_default(self):
        # Make sure we get back the expected things.
        node = self._get_test_node(INFO_DICT)
        info = snmp._parse_driver_info(node)
        self.assertEqual(INFO_DICT['snmp_driver'], info['driver'])
        self.assertEqual(INFO_DICT['snmp_address'], info['address'])
        self.assertEqual(INFO_DICT['snmp_port'], str(info['port']))
        self.assertEqual(INFO_DICT['snmp_outlet'], str(info['outlet']))
        self.assertEqual(INFO_DICT['snmp_version'], info['version'])
        self.assertEqual(INFO_DICT['snmp_community'], info['community'])
        self.assertNotIn('security', info)

    def test__parse_driver_info_apc(self):
        # Make sure the APC driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='apc')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('apc', info['driver'])

    def test__parse_driver_info_apc_masterswitch(self):
        # Make sure the APC driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='apc_masterswitch')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('apc_masterswitch', info['driver'])

    def test__parse_driver_info_apc_masterswitchplus(self):
        # Make sure the APC driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='apc_masterswitchplus')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('apc_masterswitchplus', info['driver'])

    def test__parse_driver_info_apc_rackpdu(self):
        # Make sure the APC driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='apc_rackpdu')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('apc_rackpdu', info['driver'])

    def test__parse_driver_info_aten(self):
        # Make sure the Aten driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='aten')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('aten', info['driver'])

    def test__parse_driver_info_cyberpower(self):
        # Make sure the CyberPower driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='cyberpower')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('cyberpower', info['driver'])

    def test__parse_driver_info_eatonpower(self):
        # Make sure the Eaton Power driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='eatonpower')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('eatonpower', info['driver'])

    def test__parse_driver_info_teltronix(self):
        # Make sure the Teltronix driver type is parsed.
        info = db_utils.get_test_snmp_info(snmp_driver='teltronix')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('teltronix', info['driver'])

    def test__parse_driver_info_snmp_v1(self):
        # Make sure SNMPv1 is parsed with a community string.
        info = db_utils.get_test_snmp_info(snmp_version='1',
                                           snmp_community='public')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('1', info['version'])
        self.assertEqual('public', info['community'])

    def test__parse_driver_info_snmp_v2c(self):
        # Make sure SNMPv2c is parsed with a community string.
        info = db_utils.get_test_snmp_info(snmp_version='2c',
                                           snmp_community='private')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('2c', info['version'])
        self.assertEqual('private', info['community'])

    def test__parse_driver_info_snmp_v3(self):
        # Make sure SNMPv3 is parsed with a security string.
        info = db_utils.get_test_snmp_info(snmp_version='3',
                                           snmp_security='pass')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('3', info['version'])
        self.assertEqual('pass', info['security'])

    def test__parse_driver_info_snmp_port_default(self):
        # Make sure default SNMP UDP port numbers are correct
        info = dict(INFO_DICT)
        del info['snmp_port']
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual(161, info['port'])

    def test__parse_driver_info_snmp_port(self):
        # Make sure non-default SNMP UDP port numbers can be configured
        info = db_utils.get_test_snmp_info(snmp_port='10161')
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual(10161, info['port'])

    def test__parse_driver_info_missing_driver(self):
        # Make sure exception is raised when the driver type is missing.
        info = dict(INFO_DICT)
        del info['snmp_driver']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_invalid_driver(self):
        # Make sure exception is raised when the driver type is invalid.
        info = db_utils.get_test_snmp_info(snmp_driver='invalidpower')
        node = self._get_test_node(info)
        self.assertRaises(exception.InvalidParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_address(self):
        # Make sure exception is raised when the address is missing.
        info = dict(INFO_DICT)
        del info['snmp_address']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_outlet(self):
        # Make sure exception is raised when the outlet is missing.
        info = dict(INFO_DICT)
        del info['snmp_outlet']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_invalid_outlet(self):
        # Make sure exception is raised when the outlet is not integer.
        info = dict(INFO_DICT)
        info['snmp_outlet'] = 'nn'
        node = self._get_test_node(info)
        self.assertRaises(exception.InvalidParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_default_version(self):
        # Make sure version defaults to 1 when it is missing.
        info = dict(INFO_DICT)
        del info['snmp_version']
        node = self._get_test_node(info)
        info = snmp._parse_driver_info(node)
        self.assertEqual('1', info['version'])
        self.assertEqual(INFO_DICT['snmp_community'], info['community'])

    def test__parse_driver_info_invalid_version(self):
        # Make sure exception is raised when version is invalid.
        info = db_utils.get_test_snmp_info(snmp_version='42',
                                           snmp_community='public',
                                           snmp_security='pass')
        node = self._get_test_node(info)
        self.assertRaises(exception.InvalidParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_default_version_and_missing_community(self):
        # Make sure exception is raised when version and community are missing.
        info = dict(INFO_DICT)
        del info['snmp_version']
        del info['snmp_community']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_community_snmp_v1(self):
        # Make sure exception is raised when community is missing with SNMPv1.
        info = dict(INFO_DICT)
        del info['snmp_community']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_community_snmp_v2c(self):
        # Make sure exception is raised when community is missing with SNMPv2c.
        info = db_utils.get_test_snmp_info(snmp_version='2c')
        del info['snmp_community']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_security(self):
        # Make sure exception is raised when security is missing with SNMPv3.
        info = db_utils.get_test_snmp_info(snmp_version='3')
        del info['snmp_security']
        node = self._get_test_node(info)
        self.assertRaises(exception.MissingParameterValue,
                          snmp._parse_driver_info,
                          node)


@mock.patch.object(snmp, '_get_client', autospec=True)
class SNMPDeviceDriverTestCase(db_base.DbTestCase):
    """Tests for the SNMP device-specific driver classes.

    The SNMP client object is mocked to allow various error cases to be tested.
    """

    def setUp(self):
        super(SNMPDeviceDriverTestCase, self).setUp()
        self.node = obj_utils.get_test_node(
            self.context,
            driver='fake_snmp',
            driver_info=INFO_DICT)

    def _update_driver_info(self, **kwargs):
        self.node["driver_info"].update(**kwargs)

    def _set_snmp_driver(self, snmp_driver):
        self._update_driver_info(snmp_driver=snmp_driver)

    def _get_snmp_failure(self):
        return exception.SNMPFailure(operation='test-operation',
                                     error='test-error')

    def test_power_state_on(self, mock_get_client):
        # Ensure the power on state is queried correctly
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_on
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_ON, pstate)

    def test_power_state_off(self, mock_get_client):
        # Ensure the power off state is queried correctly
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_off
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_OFF, pstate)

    def test_power_state_error(self, mock_get_client):
        # Ensure an unexpected power state returns an error
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = 42
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.ERROR, pstate)

    def test_power_state_snmp_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a query are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_state)
        mock_client.get.assert_called_once_with(driver._snmp_oid())

    def test_power_on(self, mock_get_client):
        # Ensure the device is powered on correctly
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_on
        pstate = driver.power_on()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_ON, pstate)

    def test_power_off(self, mock_get_client):
        # Ensure the device is powered off correctly
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_off
        pstate = driver.power_off()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_on_delay(self, mock_sleep, mock_get_client):
        # Ensure driver waits for the state to change following a power on
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_on()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)
        calls = [mock.call(driver._snmp_oid())] * 2
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_off_delay(self, mock_sleep, mock_get_client):
        # Ensure driver waits for the state to change following a power off
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_on,
                                       driver.value_power_off]
        pstate = driver.power_off()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        calls = [mock.call(driver._snmp_oid())] * 2
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_on_invalid_state(self, mock_sleep, mock_get_client):
        # Ensure driver retries when querying unexpected states following a
        # power on
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = 42
        pstate = driver.power_on()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        calls = [mock.call(driver._snmp_oid())] * attempts
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_off_invalid_state(self, mock_sleep, mock_get_client):
        # Ensure driver retries when querying unexpected states following a
        # power off
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = 42
        pstate = driver.power_off()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        calls = [mock.call(driver._snmp_oid())] * attempts
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    def test_power_on_snmp_set_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a power on set operation
        # are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.set.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_on)
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)

    def test_power_off_snmp_set_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a power off set
        # operation are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.set.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_off)
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)

    def test_power_on_snmp_get_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a power on get operation
        # are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_on)
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)
        mock_client.get.assert_called_once_with(driver._snmp_oid())

    def test_power_off_snmp_get_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a power off get
        # operation are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_off)
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        mock_client.get.assert_called_once_with(driver._snmp_oid())

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_on_timeout(self, mock_sleep, mock_get_client):
        # Ensure that a power on consistency poll timeout causes an error
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_off
        pstate = driver.power_on()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        calls = [mock.call(driver._snmp_oid())] * attempts
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_off_timeout(self, mock_sleep, mock_get_client):
        # Ensure that a power off consistency poll timeout causes an error
        mock_client = mock_get_client.return_value
        CONF.snmp.power_timeout = 5
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_on
        pstate = driver.power_off()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        calls = [mock.call(driver._snmp_oid())] * attempts
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    def test_power_reset(self, mock_get_client):
        # Ensure the device is reset correctly
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * 2
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_off_delay(self, mock_sleep, mock_get_client):
        # Ensure driver waits for the power off state change following a power
        # reset
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_on,
                                       driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * 3
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_on_delay(self, mock_sleep, mock_get_client):
        # Ensure driver waits for the power on state change following a power
        # reset
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_off,
                                       driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * 3
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_off_delay_on_delay(self, mock_sleep, mock_get_client):
        # Ensure driver waits for both state changes following a power reset
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_on,
                                       driver.value_power_off,
                                       driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * 4
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_off_invalid_state(self, mock_sleep, mock_get_client):
        # Ensure driver retries when querying unexpected states following a
        # power off during a reset
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = 42
        pstate = driver.power_reset()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        calls = [mock.call(driver._snmp_oid())] * attempts
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_on_invalid_state(self, mock_sleep, mock_get_client):
        # Ensure driver retries when querying unexpected states following a
        # power on during a reset
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        mock_client.get.side_effect = ([driver.value_power_off] +
                                       [42] * attempts)
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * (1 + attempts)
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_off_timeout(self, mock_sleep, mock_get_client):
        # Ensure that a power off consistency poll timeout during a reset
        # causes an error
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_on
        pstate = driver.power_reset()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        calls = [mock.call(driver._snmp_oid())] * attempts
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch("eventlet.greenthread.sleep", autospec=True)
    def test_power_reset_on_timeout(self, mock_sleep, mock_get_client):
        # Ensure that a power on consistency poll timeout during a reset
        # causes an error
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        attempts = CONF.snmp.power_timeout // driver.retry_interval
        mock_client.get.side_effect = ([driver.value_power_off] *
                                       (1 + attempts))
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * (1 + attempts)
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.ERROR, pstate)

    def test_power_reset_off_snmp_set_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a reset power off set
        # operation are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.set.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_reset)
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        self.assertFalse(mock_client.get.called)

    def test_power_reset_off_snmp_get_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a reset power off get
        # operation are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = self._get_snmp_failure()
        self.assertRaises(exception.SNMPFailure,
                          driver.power_reset)
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        mock_client.get.assert_called_once_with(driver._snmp_oid())

    def test_power_reset_on_snmp_set_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a reset power on set
        # operation are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.set.side_effect = [None, self._get_snmp_failure()]
        mock_client.get.return_value = driver.value_power_off
        self.assertRaises(exception.SNMPFailure,
                          driver.power_reset)
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        mock_client.get.assert_called_once_with(driver._snmp_oid())

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_power_reset_delay_option(self, mock_sleep, mock_get_client):
        # Test for 'reboot_delay' config option
        self.config(reboot_delay=5, group='snmp')
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * 2
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)
        mock_sleep.assert_called_once_with(5)

    def test_power_reset_on_snmp_get_failure(self, mock_get_client):
        # Ensure SNMP failure exceptions raised during a reset power on get
        # operation are propagated
        mock_client = mock_get_client.return_value
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_off,
                                       self._get_snmp_failure()]
        self.assertRaises(exception.SNMPFailure,
                          driver.power_reset)
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid()), mock.call(driver._snmp_oid())]
        mock_client.get.assert_has_calls(calls)

    def _test_simple_device_power_state_on(self, snmp_driver, mock_get_client):
        # Ensure a simple device driver queries power on correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver(snmp_driver)
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_on
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_ON, pstate)

    def _test_simple_device_power_state_off(self, snmp_driver,
                                            mock_get_client):
        # Ensure a simple device driver queries power off correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver(snmp_driver)
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_off
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_OFF, pstate)

    def _test_simple_device_power_on(self, snmp_driver, mock_get_client):
        # Ensure a simple device driver powers on correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver(snmp_driver)
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_on
        pstate = driver.power_on()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_on)
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_ON, pstate)

    def _test_simple_device_power_off(self, snmp_driver, mock_get_client):
        # Ensure a simple device driver powers off correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver(snmp_driver)
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.value_power_off
        pstate = driver.power_off()
        mock_client.set.assert_called_once_with(driver._snmp_oid(),
                                                driver.value_power_off)
        mock_client.get.assert_called_once_with(driver._snmp_oid())
        self.assertEqual(states.POWER_OFF, pstate)

    def _test_simple_device_power_reset(self, snmp_driver, mock_get_client):
        # Ensure a simple device driver resets correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver(snmp_driver)
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.value_power_off,
                                       driver.value_power_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(), driver.value_power_off),
                 mock.call(driver._snmp_oid(), driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid())] * 2
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)

    def test_apc_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the APC
        # driver
        self._update_driver_info(snmp_driver="apc",
                                 snmp_outlet="3")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 318, 1, 1, 4, 4, 2, 1, 3, 3)
        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(1, driver.value_power_on)
        self.assertEqual(2, driver.value_power_off)

    def test_apc_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('apc', mock_get_client)

    def test_apc_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('apc', mock_get_client)

    def test_apc_power_on(self, mock_get_client):
        self._test_simple_device_power_on('apc', mock_get_client)

    def test_apc_power_off(self, mock_get_client):
        self._test_simple_device_power_off('apc', mock_get_client)

    def test_apc_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('apc', mock_get_client)

    def test_apc_masterswitch_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the APC
        # masterswitch driver
        self._update_driver_info(snmp_driver="apc_masterswitch",
                                 snmp_outlet="6")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 318, 1, 1, 4, 4, 2, 1, 3, 6)
        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(1, driver.value_power_on)
        self.assertEqual(2, driver.value_power_off)

    def test_apc_masterswitch_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('apc_masterswitch',
                                                mock_get_client)

    def test_apc_masterswitch_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('apc_masterswitch',
                                                 mock_get_client)

    def test_apc_masterswitch_power_on(self, mock_get_client):
        self._test_simple_device_power_on('apc_masterswitch', mock_get_client)

    def test_apc_masterswitch_power_off(self, mock_get_client):
        self._test_simple_device_power_off('apc_masterswitch', mock_get_client)

    def test_apc_masterswitch_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('apc_masterswitch',
                                             mock_get_client)

    def test_apc_masterswitchplus_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the APC
        # masterswitchplus driver
        self._update_driver_info(snmp_driver="apc_masterswitchplus",
                                 snmp_outlet="6")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 318, 1, 1, 6, 5, 1, 1, 5, 6)
        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(1, driver.value_power_on)
        self.assertEqual(3, driver.value_power_off)

    def test_apc_masterswitchplus_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('apc_masterswitchplus',
                                                mock_get_client)

    def test_apc_masterswitchplus_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('apc_masterswitchplus',
                                                 mock_get_client)

    def test_apc_masterswitchplus_power_on(self, mock_get_client):
        self._test_simple_device_power_on('apc_masterswitchplus',
                                          mock_get_client)

    def test_apc_masterswitchplus_power_off(self, mock_get_client):
        self._test_simple_device_power_off('apc_masterswitchplus',
                                           mock_get_client)

    def test_apc_masterswitchplus_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('apc_masterswitchplus',
                                             mock_get_client)

    def test_apc_rackpdu_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the APC
        # rackpdu driver
        self._update_driver_info(snmp_driver="apc_rackpdu",
                                 snmp_outlet="6")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 318, 1, 1, 12, 3, 3, 1, 1, 4, 6)

        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(1, driver.value_power_on)
        self.assertEqual(2, driver.value_power_off)

    def test_apc_rackpdu_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('apc_rackpdu', mock_get_client)

    def test_apc_rackpdu_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('apc_rackpdu',
                                                 mock_get_client)

    def test_apc_rackpdu_power_on(self, mock_get_client):
        self._test_simple_device_power_on('apc_rackpdu', mock_get_client)

    def test_apc_rackpdu_power_off(self, mock_get_client):
        self._test_simple_device_power_off('apc_rackpdu', mock_get_client)

    def test_apc_rackpdu_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('apc_rackpdu', mock_get_client)

    def test_aten_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the
        # Aten driver
        self._update_driver_info(snmp_driver="aten",
                                 snmp_outlet="3")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 21317, 1, 3, 2, 2, 2, 2, 3, 0)
        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(2, driver.value_power_on)
        self.assertEqual(1, driver.value_power_off)

    def test_aten_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('aten', mock_get_client)

    def test_aten_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('aten', mock_get_client)

    def test_aten_power_on(self, mock_get_client):
        self._test_simple_device_power_on('aten', mock_get_client)

    def test_aten_power_off(self, mock_get_client):
        self._test_simple_device_power_off('aten', mock_get_client)

    def test_aten_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('aten', mock_get_client)

    def test_cyberpower_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the
        # CyberPower driver
        self._update_driver_info(snmp_driver="cyberpower",
                                 snmp_outlet="3")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 3808, 1, 1, 3, 3, 3, 1, 1, 4, 3)
        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(1, driver.value_power_on)
        self.assertEqual(2, driver.value_power_off)

    def test_cyberpower_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('cyberpower', mock_get_client)

    def test_cyberpower_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('cyberpower', mock_get_client)

    def test_cyberpower_power_on(self, mock_get_client):
        self._test_simple_device_power_on('cyberpower', mock_get_client)

    def test_cyberpower_power_off(self, mock_get_client):
        self._test_simple_device_power_off('cyberpower', mock_get_client)

    def test_cyberpower_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('cyberpower', mock_get_client)

    def test_teltronix_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the
        # Teltronix driver
        self._update_driver_info(snmp_driver="teltronix",
                                 snmp_outlet="3")
        driver = snmp._get_driver(self.node)
        oid = (1, 3, 6, 1, 4, 1, 23620, 1, 2, 2, 1, 4, 3)
        self.assertEqual(oid, driver._snmp_oid())
        self.assertEqual(2, driver.value_power_on)
        self.assertEqual(1, driver.value_power_off)

    def test_teltronix_power_state_on(self, mock_get_client):
        self._test_simple_device_power_state_on('teltronix', mock_get_client)

    def test_teltronix_power_state_off(self, mock_get_client):
        self._test_simple_device_power_state_off('teltronix', mock_get_client)

    def test_teltronix_power_on(self, mock_get_client):
        self._test_simple_device_power_on('teltronix', mock_get_client)

    def test_teltronix_power_off(self, mock_get_client):
        self._test_simple_device_power_off('teltronix', mock_get_client)

    def test_teltronix_power_reset(self, mock_get_client):
        self._test_simple_device_power_reset('teltronix', mock_get_client)

    def test_eaton_power_snmp_objects(self, mock_get_client):
        # Ensure the correct SNMP object OIDs and values are used by the Eaton
        # Power driver
        self._update_driver_info(snmp_driver="eatonpower",
                                 snmp_outlet="3")
        driver = snmp._get_driver(self.node)
        status_oid = (1, 3, 6, 1, 4, 1, 534, 6, 6, 7, 6, 6, 1, 2, 3)
        poweron_oid = (1, 3, 6, 1, 4, 1, 534, 6, 6, 7, 6, 6, 1, 3, 3)
        poweroff_oid = (1, 3, 6, 1, 4, 1, 534, 6, 6, 7, 6, 6, 1, 4, 3)
        self.assertEqual(status_oid, driver._snmp_oid(driver.oid_status))
        self.assertEqual(poweron_oid, driver._snmp_oid(driver.oid_poweron))
        self.assertEqual(poweroff_oid, driver._snmp_oid(driver.oid_poweroff))
        self.assertEqual(0, driver.status_off)
        self.assertEqual(1, driver.status_on)
        self.assertEqual(2, driver.status_pending_off)
        self.assertEqual(3, driver.status_pending_on)

    def test_eaton_power_power_state_on(self, mock_get_client):
        # Ensure the Eaton Power driver queries on correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.status_on
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(
            driver._snmp_oid(driver.oid_status))
        self.assertEqual(states.POWER_ON, pstate)

    def test_eaton_power_power_state_off(self, mock_get_client):
        # Ensure the Eaton Power driver queries off correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.status_off
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(
            driver._snmp_oid(driver.oid_status))
        self.assertEqual(states.POWER_OFF, pstate)

    def test_eaton_power_power_state_pending_off(self, mock_get_client):
        # Ensure the Eaton Power driver queries pending off correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.status_pending_off
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(
            driver._snmp_oid(driver.oid_status))
        self.assertEqual(states.POWER_ON, pstate)

    def test_eaton_power_power_state_pending_on(self, mock_get_client):
        # Ensure the Eaton Power driver queries pending on correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.status_pending_on
        pstate = driver.power_state()
        mock_client.get.assert_called_once_with(
            driver._snmp_oid(driver.oid_status))
        self.assertEqual(states.POWER_OFF, pstate)

    def test_eaton_power_power_on(self, mock_get_client):
        # Ensure the Eaton Power driver powers on correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.status_on
        pstate = driver.power_on()
        mock_client.set.assert_called_once_with(
            driver._snmp_oid(driver.oid_poweron), driver.value_power_on)
        mock_client.get.assert_called_once_with(
            driver._snmp_oid(driver.oid_status))
        self.assertEqual(states.POWER_ON, pstate)

    def test_eaton_power_power_off(self, mock_get_client):
        # Ensure the Eaton Power driver powers off correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.return_value = driver.status_off
        pstate = driver.power_off()
        mock_client.set.assert_called_once_with(
            driver._snmp_oid(driver.oid_poweroff), driver.value_power_off)
        mock_client.get.assert_called_once_with(
            driver._snmp_oid(driver.oid_status))
        self.assertEqual(states.POWER_OFF, pstate)

    def test_eaton_power_power_reset(self, mock_get_client):
        # Ensure the Eaton Power driver resets correctly
        mock_client = mock_get_client.return_value
        self._set_snmp_driver("eatonpower")
        driver = snmp._get_driver(self.node)
        mock_client.get.side_effect = [driver.status_off, driver.status_on]
        pstate = driver.power_reset()
        calls = [mock.call(driver._snmp_oid(driver.oid_poweroff),
                           driver.value_power_off),
                 mock.call(driver._snmp_oid(driver.oid_poweron),
                           driver.value_power_on)]
        mock_client.set.assert_has_calls(calls)
        calls = [mock.call(driver._snmp_oid(driver.oid_status))] * 2
        mock_client.get.assert_has_calls(calls)
        self.assertEqual(states.POWER_ON, pstate)


@mock.patch.object(snmp, '_get_driver', autospec=True)
class SNMPDriverTestCase(db_base.DbTestCase):
    """SNMP power driver interface tests.

    In this test case, the SNMP power driver interface is exercised. The
    device-specific SNMP driver is mocked to allow various error cases to be
    tested.
    """

    def setUp(self):
        super(SNMPDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_snmp')

        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_snmp',
                                               driver_info=INFO_DICT)

    def _get_snmp_failure(self):
        return exception.SNMPFailure(operation='test-operation',
                                     error='test-error')

    def test_get_properties(self, mock_get_driver):
        expected = snmp.COMMON_PROPERTIES
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected, task.driver.get_properties())

    def test_get_power_state_on(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_state.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pstate = task.driver.power.get_power_state(task)
        mock_driver.power_state.assert_called_once_with()
        self.assertEqual(states.POWER_ON, pstate)

    def test_get_power_state_off(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_state.return_value = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pstate = task.driver.power.get_power_state(task)
        mock_driver.power_state.assert_called_once_with()
        self.assertEqual(states.POWER_OFF, pstate)

    def test_get_power_state_error(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_state.return_value = states.ERROR
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pstate = task.driver.power.get_power_state(task)
        mock_driver.power_state.assert_called_once_with()
        self.assertEqual(states.ERROR, pstate)

    def test_get_power_state_snmp_failure(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_state.side_effect = self._get_snmp_failure()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.SNMPFailure,
                              task.driver.power.get_power_state, task)
        mock_driver.power_state.assert_called_once_with()

    def test_set_power_state_on(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_on.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
        mock_driver.power_on.assert_called_once_with()

    def test_set_power_state_off(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_off.return_value = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)
        mock_driver.power_off.assert_called_once_with()

    def test_set_power_state_error(self, mock_get_driver):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.set_power_state,
                              task, states.ERROR)

    def test_set_power_state_on_snmp_failure(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_on.side_effect = self._get_snmp_failure()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.SNMPFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_ON)
        mock_driver.power_on.assert_called_once_with()

    def test_set_power_state_off_snmp_failure(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_off.side_effect = self._get_snmp_failure()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.SNMPFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_OFF)
        mock_driver.power_off.assert_called_once_with()

    def test_set_power_state_on_timeout(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_on.return_value = states.ERROR
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_ON)
        mock_driver.power_on.assert_called_once_with()

    def test_set_power_state_off_timeout(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_off.return_value = states.ERROR
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_OFF)
        mock_driver.power_off.assert_called_once_with()

    def test_reboot(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_reset.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.reboot(task)
        mock_driver.power_reset.assert_called_once_with()

    def test_reboot_snmp_failure(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_reset.side_effect = self._get_snmp_failure()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.SNMPFailure,
                              task.driver.power.reboot, task)
        mock_driver.power_reset.assert_called_once_with()

    def test_reboot_timeout(self, mock_get_driver):
        mock_driver = mock_get_driver.return_value
        mock_driver.power_reset.return_value = states.ERROR
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.reboot, task)
        mock_driver.power_reset.assert_called_once_with()
