# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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
from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

hponeview_client = importutils.try_import('hpOneView.oneview_client')


class OneViewCommonTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewCommonTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')
        self.config(tls_cacert_file='ca_file', group='oneview')
        self.config(allow_insecure_connections=False, group='oneview')
        mgr_utils.mock_the_extension_manager(driver="fake_oneview")

    def test_prepare_manager_url(self):
        self.assertEqual(
            common.prepare_manager_url("https://1.2.3.4/"), "1.2.3.4")
        self.assertEqual(
            common.prepare_manager_url("http://oneview"), "oneview")
        self.assertEqual(
            common.prepare_manager_url("http://oneview:8080"), "oneview:8080")
        self.assertEqual(
            common.prepare_manager_url("http://oneview/something"), "oneview")
        self.assertEqual(
            common.prepare_manager_url("oneview/something"), "oneview")
        self.assertEqual(
            common.prepare_manager_url("oneview"), "oneview")

    @mock.patch.object(hponeview_client, 'OneViewClient', autospec=True)
    def test_get_hponeview_client(self, mock_hponeview_client):
        common.get_hponeview_client()
        mock_hponeview_client.assert_called_once_with(self.config)

    def test_get_hponeview_client_insecure_false(self):
        self.config(tls_cacert_file=None, group='oneview')
        self.assertRaises(exception.OneViewError, common.get_hponeview_client)

    @mock.patch.object(hponeview_client, 'OneViewClient', autospec=True)
    def test_get_hponeview_client_insecure_cafile(self, mock_oneview):
        self.config(allow_insecure_connections=True, group='oneview')
        credentials = {
            "ip": 'https://1.2.3.4',
            "credentials": {
                "userName": 'user',
                "password": 'password'
            },
            "ssl_certificate": None
        }
        mock_oneview.assert_called_once_with(credentials)

    def test_get_ilo_access(self):
        url = ("hplocons://addr=1.2.3.4&sessionkey" +
               "=a79659e3b3b7c8209c901ac3509a6719")
        remote_console = {'remoteConsoleUrl': url}
        host_ip, token = common._get_ilo_access(remote_console)
        self.assertEqual(host_ip, "1.2.3.4")
        self.assertEqual(token, "a79659e3b3b7c8209c901ac3509a6719")

    def test_verify_node_info(self):
        common.verify_node_info(self.node)

    def test_verify_node_info_missing_node_properties(self):
        self.node.properties = {
            "cpu_arch": "x86_64",
            "cpus": "8",
            "local_gb": "10",
            "memory_mb": "4096",
            "capabilities": ("enclosure_group_uri:fake_eg_uri,"
                             "server_profile_template_uri:fake_spt_uri")
        }
        with self.assertRaisesRegex(exception.MissingParameterValue,
                                    "server_hardware_type_uri"):
            common.verify_node_info(self.node)

    def test_verify_node_info_missing_node_driver_info(self):
        self.node.driver_info = {}

        with self.assertRaisesRegex(exception.MissingParameterValue,
                                    "server_hardware_uri"):
            common.verify_node_info(self.node)

    def test_verify_node_info_missing_spt(self):
        properties = db_utils.get_test_oneview_properties()
        properties["capabilities"] = ("server_hardware_type_uri:fake_sht_uri,"
                                      "enclosure_group_uri:fake_eg_uri")

        self.node.properties = properties
        with self.assertRaisesRegex(exception.MissingParameterValue,
                                    "server_profile_template_uri"):
            common.verify_node_info(self.node)

    def test_verify_node_info_missing_sh(self):
        driver_info = db_utils.get_test_oneview_driver_info()

        del driver_info["server_hardware_uri"]
        properties = db_utils.get_test_oneview_properties()
        properties["capabilities"] = (
            "server_hardware_type_uri:fake_sht_uri,"
            "enclosure_group_uri:fake_eg_uri,"
            "server_profile_template_uri:fake_spt_uri"
        )

        self.node.properties = properties
        self.node.driver_info = driver_info
        with self.assertRaisesRegex(exception.MissingParameterValue,
                                    "server_hardware_uri"):
            common.verify_node_info(self.node)

    def test_verify_node_info_missing_sht(self):
        driver_info = db_utils.get_test_oneview_driver_info()
        properties = db_utils.get_test_oneview_properties()
        properties["capabilities"] = (
            "enclosure_group_uri:fake_eg_uri,"
            "server_profile_template_uri:fake_spt_uri"
        )

        self.node.properties = properties
        self.node.driver_info = driver_info
        with self.assertRaisesRegex(exception.MissingParameterValue,
                                    "server_hardware_type_uri"):
            common.verify_node_info(self.node)

    def test_get_oneview_info(self):
        complete_node = self.node
        expected_node_info = {
            'server_hardware_uri': 'fake_sh_uri',
            'server_hardware_type_uri': 'fake_sht_uri',
            'enclosure_group_uri': 'fake_eg_uri',
            'server_profile_template_uri': 'fake_spt_uri',
            'applied_server_profile_uri': None,
        }

        self.assertEqual(
            expected_node_info,
            common.get_oneview_info(complete_node)
        )

    def test_get_oneview_info_missing_spt(self):
        driver_info = db_utils.get_test_oneview_driver_info()
        properties = db_utils.get_test_oneview_properties()
        properties["capabilities"] = ("server_hardware_type_uri:fake_sht_uri,"
                                      "enclosure_group_uri:fake_eg_uri")

        self.node.driver_info = driver_info
        self.node.properties = properties

        incomplete_node = self.node
        expected_node_info = {
            'server_hardware_uri': 'fake_sh_uri',
            'server_hardware_type_uri': 'fake_sht_uri',
            'enclosure_group_uri': 'fake_eg_uri',
            'server_profile_template_uri': None,
            'applied_server_profile_uri': None,
        }

        self.assertEqual(
            expected_node_info,
            common.get_oneview_info(incomplete_node)
        )

    def test_get_oneview_info_missing_sh(self):
        driver_info = db_utils.get_test_oneview_driver_info()

        del driver_info["server_hardware_uri"]
        properties = db_utils.get_test_oneview_properties()
        properties["capabilities"] = (
            "server_hardware_type_uri:fake_sht_uri,"
            "enclosure_group_uri:fake_eg_uri,"
            "server_profile_template_uri:fake_spt_uri"
        )

        self.node.driver_info = driver_info
        self.node.properties = properties

        incomplete_node = self.node
        expected_node_info = {
            'server_hardware_uri': None,
            'server_hardware_type_uri': 'fake_sht_uri',
            'enclosure_group_uri': 'fake_eg_uri',
            'server_profile_template_uri': 'fake_spt_uri',
            'applied_server_profile_uri': None,
        }

        self.assertEqual(
            expected_node_info,
            common.get_oneview_info(incomplete_node)
        )

    def test_get_oneview_info_malformed_capabilities(self):
        driver_info = db_utils.get_test_oneview_driver_info()

        del driver_info["server_hardware_uri"]
        properties = db_utils.get_test_oneview_properties()
        properties["capabilities"] = "anything,000"

        self.node.driver_info = driver_info
        self.node.properties = properties

        self.assertRaises(exception.OneViewInvalidNodeParameter,
                          common.get_oneview_info,
                          self.node)

    def test__verify_node_info(self):
        common._verify_node_info("properties",
                                 {"a": True,
                                  "b": False,
                                  "c": 0,
                                  "d": "something",
                                  "e": "somethingelse"},
                                 ["a", "b", "c", "e"])

    def test__verify_node_info_fails(self):
        self.assertRaises(
            exception.MissingParameterValue,
            common._verify_node_info,
            "properties",
            {"a": 1, "b": 2, "c": 3},
            ["x"]
        )

    def test__verify_node_info_missing_values_empty_string(self):
        with self.assertRaisesRegex(exception.MissingParameterValue,
                                    "'properties:a', 'properties:b'"):
            common._verify_node_info("properties",
                                     {"a": '', "b": None, "c": "something"},
                                     ["a", "b", "c"])

    @mock.patch.object(common, 'get_hponeview_client', autospec=True)
    @mock.patch.object(common, '_validate_node_server_profile_template')
    @mock.patch.object(common, '_validate_node_server_hardware_type')
    @mock.patch.object(common, '_validate_node_enclosure_group')
    @mock.patch.object(common, '_validate_node_port_mac_server_hardware')
    @mock.patch.object(common, '_validate_server_profile_template_mac_type')
    def test_validate_oneview_resources_compatibility(
            self, mock_spt_mac_type, mock_port_mac_sh, mock_enclosure,
            mock_sh_type, mock_sp_template, mock_hponeview):
        """Validate compatibility of resources.

        1) Check _validate_node_server_profile_template method is called
        2) Check _validate_node_server_hardware_type method is called
        3) Check _validate_node_enclosure_group method is called
        4) Check _validate_node_port_mac_server_hardware method is called
        5) Check _validate_server_profile_template_mac_type method is called
        """
        oneview_client = mock_hponeview()
        fake_port = db_utils.create_test_port()
        fake_port.address = 'AA:BB:CC:DD:EE'
        fake_device = {'physicalPorts': [
            {'type': 'Ethernet',
             'virtualPorts': [
                 {'portFunction': 'a',
                  'mac': 'AA:BB:CC:DD:EE'}
             ]}
        ]}
        fake_spt = {
            'serverHardwareTypeUri': 'fake_sht_uri',
            'enclosureGroupUri': 'fake_eg_uri',
            'macType': 'Physical',
            'boot': {'manageBoot': True}
        }
        fake_sh = {
            'serverHardwareTypeUri': 'fake_sht_uri',
            'serverGroupUri': 'fake_eg_uri',
            'processorCoreCount': 4,
            'processorCount': 2,
            'memoryMb': 4096,
            'portMap': {'deviceSlots': [fake_device]}
        }
        oneview_client.server_profile_templates.get.return_value = fake_spt
        oneview_client.server_hardware.get.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [fake_port]
            common.validate_oneview_resources_compatibility(task)
            self.assertTrue(mock_sp_template.called)
            self.assertTrue(mock_sh_type.called)
            self.assertTrue(mock_enclosure.called)
            self.assertTrue(mock_port_mac_sh.called)
            self.assertTrue(mock_spt_mac_type.called)

    @mock.patch.object(common, 'get_hponeview_client', autospec=True)
    def test__validate_server_profile_template_mac_type_virtual(
            self, mock_hponeview):
        oneview_client = mock_hponeview()
        fake_spt = {'macType': 'Virtual'}
        oneview_client.server_hardware.get.return_value = fake_spt
        oneview_info = {'server_profile_template_uri': 'fake_uri'}

        self.assertRaises(exception.OneViewError,
                          common._validate_server_profile_template_mac_type,
                          oneview_client, oneview_info)

    @mock.patch.object(common, 'get_hponeview_client', autospec=True)
    def test__validate_node_port_mac_server_hardware_invalid(
            self, mock_hponeview):
        oneview_client = mock_hponeview()
        fake_device = {
            'physicalPorts': [
                {'type': 'notEthernet',
                 'mac': '00:11:22:33:44',
                 'virtualPorts': [{
                     'portFunction': 'a',
                     'mac': 'AA:BB:CC:DD:EE'}]},
                {'type': 'Ethernet',
                 'mac': '11:22:33:44:55',
                 'virtualPorts': [{
                     'portFunction': 'a',
                     'mac': 'BB:CC:DD:EE:FF'}]}]}
        fake_sh = {'portMap': {'deviceSlots': [fake_device]}}
        fake_port = db_utils.create_test_port(address='AA:BB:CC:DD:EE')
        oneview_client.server_hardware.get.return_value = fake_sh
        oneview_info = db_utils.get_test_oneview_driver_info()

        self.assertRaises(exception.OneViewError,
                          common._validate_node_port_mac_server_hardware,
                          oneview_client, oneview_info, [fake_port])

    @mock.patch.object(common, 'get_hponeview_client', autospec=True)
    def test__validate_node_enclosure_group_invalid(self, mock_hponeview):
        oneview_client = mock_hponeview()
        fake_sh = {'serverGroupUri': 'invalid_fake_eg_uri'}
        oneview_client.server_hardware.get.return_value = fake_sh
        oneview_info = {'server_hardware_uri': 'fake_sh_uri',
                        'enclosure_group_uri': 'fake_eg_uri'}

        self.assertRaises(exception.OneViewError,
                          common._validate_node_enclosure_group,
                          oneview_client, oneview_info)

    @mock.patch.object(common, 'get_hponeview_client', autospec=True)
    def test__validate_node_server_hardware_type(self, mock_hponeview):
        oneview_client = mock_hponeview()
        fake_sh = {'serverHardwareTypeUri': 'invalid_fake_sh_uri'}
        oneview_client.server_hardware.get.return_value = fake_sh
        oneview_info = {'server_hardware_uri': 'fake_sh_uri',
                        'server_hardware_type_uri': 'fake_sht_uri'}

        self.assertRaises(exception.OneViewError,
                          common._validate_node_server_hardware_type,
                          oneview_client, oneview_info)

    def test__validate_server_profile_template_manage_boot_false(self):
        fake_spt = {'boot': {'manageBoot': False}}
        self.assertRaises(exception.OneViewError,
                          common._validate_server_profile_template_manage_boot,
                          fake_spt)

    def test__validate_spt_enclosure_group_invalid(self):
        fake_spt = {'enclosureGroupUri': 'fake_eg_uri'}
        fake_sh = {'serverGroupUri': 'invalid_fake_eg_uri'}
        self.assertRaises(exception.OneViewError,
                          common._validate_spt_enclosure_group,
                          fake_spt, fake_sh)

    def test__validate_server_profile_template_server_hardware_type(self):
        fake_spt = {'serverHardwareTypeUri': 'fake_sht_uri'}
        fake_sh = {'serverHardwareTypeUri': 'invalid_fake_sht_uri'}
        self.assertRaises(
            exception.OneViewError,
            common._validate_server_profile_template_server_hardware_type,
            fake_spt, fake_sh)
