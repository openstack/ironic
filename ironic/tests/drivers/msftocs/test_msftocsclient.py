# Copyright 2015 Cloudbase Solutions Srl
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

"""
Test class for MSFT OCS REST API client
"""

import mock
import requests
from requests import exceptions as requests_exceptions

from ironic.common import exception
from ironic.drivers.modules.msftocs import msftocsclient
from ironic.tests import base


FAKE_BOOT_RESPONSE = (
    '<BootResponse xmlns="%s" '
    'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
    '<completionCode>Success</completionCode>'
    '<apiVersion>1</apiVersion>'
    '<statusDescription>Success</statusDescription>'
    '<bladeNumber>1</bladeNumber>'
    '<nextBoot>ForcePxe</nextBoot>'
    '</BootResponse>') % msftocsclient.WCSNS

FAKE_BLADE_RESPONSE = (
    '<BladeResponse xmlns="%s" '
    'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
    '<completionCode>Success</completionCode>'
    '<apiVersion>1</apiVersion>'
    '<statusDescription/>'
    '<bladeNumber>1</bladeNumber>'
    '</BladeResponse>') % msftocsclient.WCSNS

FAKE_POWER_STATE_RESPONSE = (
    '<PowerStateResponse xmlns="%s" '
    'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
    '<completionCode>Success</completionCode>'
    '<apiVersion>1</apiVersion>'
    '<statusDescription>Blade Power is On, firmware decompressed'
    '</statusDescription>'
    '<bladeNumber>1</bladeNumber>'
    '<Decompression>0</Decompression>'
    '<powerState>ON</powerState>'
    '</PowerStateResponse>') % msftocsclient.WCSNS

FAKE_BLADE_STATE_RESPONSE = (
    '<BladeStateResponse xmlns="%s" '
    'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
    '<completionCode>Success</completionCode>'
    '<apiVersion>1</apiVersion>'
    '<statusDescription/>'
    '<bladeNumber>1</bladeNumber>'
    '<bladeState>ON</bladeState>'
    '</BladeStateResponse>') % msftocsclient.WCSNS


class MSFTOCSClientApiTestCase(base.TestCase):
    def setUp(self):
        super(MSFTOCSClientApiTestCase, self).setUp()
        self._fake_base_url = "http://fakehost:8000"
        self._fake_username = "admin"
        self._fake_password = 'fake'
        self._fake_blade_id = 1
        self._client = msftocsclient.MSFTOCSClientApi(
            self._fake_base_url, self._fake_username, self._fake_password)

    @mock.patch.object(requests, 'get', autospec=True)
    def test__exec_cmd(self, mock_get):
        fake_response_text = 'fake_response_text'
        fake_rel_url = 'fake_rel_url'
        mock_get.return_value.text = 'fake_response_text'

        self.assertEqual(fake_response_text,
                         self._client._exec_cmd(fake_rel_url))
        mock_get.assert_called_once_with(
            self._fake_base_url + "/" + fake_rel_url, auth=mock.ANY)

    @mock.patch.object(requests, 'get', autospec=True)
    def test__exec_cmd_http_get_fail(self, mock_get):
        fake_rel_url = 'fake_rel_url'
        mock_get.side_effect = requests_exceptions.ConnectionError('x')

        self.assertRaises(exception.MSFTOCSClientApiException,
                          self._client._exec_cmd,
                          fake_rel_url)
        mock_get.assert_called_once_with(
            self._fake_base_url + "/" + fake_rel_url, auth=mock.ANY)

    def test__check_completion_code(self):
        et = self._client._check_completion_code(FAKE_BOOT_RESPONSE)
        self.assertEqual('{%s}BootResponse' % msftocsclient.WCSNS, et.tag)

    def test__check_completion_code_fail(self):
        self.assertRaises(exception.MSFTOCSClientApiException,
                          self._client._check_completion_code,
                          '<fake xmlns="%s"></fake>' % msftocsclient.WCSNS)

    def test__check_completion_with_bad_completion_code_fail(self):
        self.assertRaises(exception.MSFTOCSClientApiException,
                          self._client._check_completion_code,
                          '<fake xmlns="%s">'
                          '<completionCode>Fail</completionCode>'
                          '</fake>' % msftocsclient.WCSNS)

    def test__check_completion_code_xml_parsing_fail(self):
        self.assertRaises(exception.MSFTOCSClientApiException,
                          self._client._check_completion_code,
                          'bad_xml')

    @mock.patch.object(
        msftocsclient.MSFTOCSClientApi, '_exec_cmd', autospec=True)
    def test_get_blade_state(self, mock_exec_cmd):
        mock_exec_cmd.return_value = FAKE_BLADE_STATE_RESPONSE
        self.assertEqual(
            msftocsclient.POWER_STATUS_ON,
            self._client.get_blade_state(self._fake_blade_id))
        mock_exec_cmd.assert_called_once_with(
            self._client, "GetBladeState?bladeId=%d" % self._fake_blade_id)

    @mock.patch.object(
        msftocsclient.MSFTOCSClientApi, '_exec_cmd', autospec=True)
    def test_set_blade_on(self, mock_exec_cmd):
        mock_exec_cmd.return_value = FAKE_BLADE_RESPONSE
        self._client.set_blade_on(self._fake_blade_id)
        mock_exec_cmd.assert_called_once_with(
            self._client, "SetBladeOn?bladeId=%d" % self._fake_blade_id)

    @mock.patch.object(
        msftocsclient.MSFTOCSClientApi, '_exec_cmd', autospec=True)
    def test_set_blade_off(self, mock_exec_cmd):
        mock_exec_cmd.return_value = FAKE_BLADE_RESPONSE
        self._client.set_blade_off(self._fake_blade_id)
        mock_exec_cmd.assert_called_once_with(
            self._client, "SetBladeOff?bladeId=%d" % self._fake_blade_id)

    @mock.patch.object(
        msftocsclient.MSFTOCSClientApi, '_exec_cmd', autospec=True)
    def test_set_blade_power_cycle(self, mock_exec_cmd):
        mock_exec_cmd.return_value = FAKE_BLADE_RESPONSE
        self._client.set_blade_power_cycle(self._fake_blade_id)
        mock_exec_cmd.assert_called_once_with(
            self._client,
            "SetBladeActivePowerCycle?bladeId=%d&offTime=0" %
            self._fake_blade_id)

    @mock.patch.object(
        msftocsclient.MSFTOCSClientApi, '_exec_cmd', autospec=True)
    def test_get_next_boot(self, mock_exec_cmd):
        mock_exec_cmd.return_value = FAKE_BOOT_RESPONSE
        self.assertEqual(
            msftocsclient.BOOT_TYPE_FORCE_PXE,
            self._client.get_next_boot(self._fake_blade_id))
        mock_exec_cmd.assert_called_once_with(
            self._client, "GetNextBoot?bladeId=%d" % self._fake_blade_id)

    @mock.patch.object(
        msftocsclient.MSFTOCSClientApi, '_exec_cmd', autospec=True)
    def test_set_next_boot(self, mock_exec_cmd):
        mock_exec_cmd.return_value = FAKE_BOOT_RESPONSE
        self._client.set_next_boot(self._fake_blade_id,
                                   msftocsclient.BOOT_TYPE_FORCE_PXE)
        mock_exec_cmd.assert_called_once_with(
            self._client,
            "SetNextBoot?bladeId=%(blade_id)d&bootType=%(boot_type)d&"
            "uefi=%(uefi)s&persistent=%(persistent)s" %
            {"blade_id": self._fake_blade_id,
             "boot_type": msftocsclient.BOOT_TYPE_FORCE_PXE,
             "uefi": "true", "persistent": "true"})
