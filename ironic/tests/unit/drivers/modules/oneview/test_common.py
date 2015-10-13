# -*- encoding: utf-8 -*-
#
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.tests.unit.conductor import utils as mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

oneview_states = importutils.try_import('oneview_client.states')

PROPERTIES_DICT = {"cpu_arch": "x86_64",
                   "cpus": "8",
                   "local_gb": "10",
                   "memory_mb": "4096",
                   "capabilities": "server_hardware_type_uri:fake_sht_uri,"
                                   "enclosure_group_uri:fake_eg_uri"}

DRIVER_INFO_DICT = {'server_hardware_uri': 'fake_sh_uri',
                    'server_profile_template_uri': 'fake_spt_uri'}


class OneViewCommonTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewCommonTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview', properties=PROPERTIES_DICT,
            driver_info=DRIVER_INFO_DICT,
        )
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')
        mgr_utils.mock_the_extension_manager(driver="fake_oneview")

    def test_verify_node_info(self):
        common.verify_node_info(self.node)

    def test_verify_node_info_missing_node_properties(self):
        self.node.properties = {
            "cpu_arch": "x86_64",
            "cpus": "8",
            "local_gb": "10",
            "memory_mb": "4096",
            "capabilities": "enclosure_group_uri:fake_eg_uri"
        }

        exc = self.assertRaises(
            exception.MissingParameterValue,
            common.verify_node_info,
            self.node
        )
        self.assertEqual("Missing the keys for the following OneView data in "
                         "node's properties/capabilities: "
                         "server_hardware_type_uri.",
                         str(exc))

    def test_verify_node_info_missing_node_driver_info(self):
        self.node.driver_info = {
            'server_hardware_uri': 'fake_sh_uri'
        }

        exc = self.assertRaises(
            exception.MissingParameterValue,
            common.verify_node_info,
            self.node
        )
        self.assertEqual("Missing the keys for the following OneView data in "
                         "node's driver_info: server_profile_template_uri.",
                         str(exc))

    def test_get_oneview_info(self):
        complete_node = self.node
        expected_node_info = {
            'server_hardware_uri': 'fake_sh_uri',
            'server_hardware_type_uri': 'fake_sht_uri',
            'enclosure_group_uri': 'fake_eg_uri',
            'server_profile_template_uri': 'fake_spt_uri',
        }

        self.assertEqual(
            expected_node_info,
            common.get_oneview_info(complete_node)
        )

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
        exc_expected_msg = ("Missing parameter value for: 'properties:a'"
                            ", 'properties:b'")

        self.assertRaisesRegexp(
            exception.MissingParameterValue,
            exc_expected_msg,
            common._verify_node_info,
            "properties",
            {"a": '', "b": None, "c": "something"},
            ["a", "b", "c"]
        )

    def _test_translate_oneview_states(self, power_state_to_translate,
                                       expected_translated_power_state):
        translated_power_state = common.translate_oneview_power_state(
            power_state_to_translate)
        self.assertEqual(translated_power_state,
                         expected_translated_power_state)

    def test_all_scenarios_for_translate_oneview_states(self):
        self._test_translate_oneview_states(
            oneview_states.ONEVIEW_POWERING_OFF, states.POWER_ON)
        self._test_translate_oneview_states(
            oneview_states.ONEVIEW_POWER_OFF, states.POWER_OFF)
        self._test_translate_oneview_states(
            oneview_states.ONEVIEW_POWERING_ON, states.POWER_OFF)
        self._test_translate_oneview_states(
            oneview_states.ONEVIEW_RESETTING, states.REBOOT)
        self._test_translate_oneview_states("anything", states.ERROR)

    @mock.patch.object(common, 'get_oneview_client', spec_set=True,
                       autospec=True)
    def test_validate_oneview_resources_compatibility(self,
                                                      mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            common.validate_oneview_resources_compatibility(task)
            self.assertTrue(
                oneview_client.validate_node_server_hardware.called)
            self.assertTrue(
                oneview_client.validate_node_server_hardware_type.called)
            self.assertTrue(
                oneview_client.check_server_profile_is_applied.called)
            self.assertTrue(
                oneview_client.is_node_port_mac_compatible_with_server_profile.
                called)
            self.assertTrue(
                oneview_client.validate_node_enclosure_group.called)
            self.assertTrue(
                oneview_client.validate_node_server_profile_template.called)
