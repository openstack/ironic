# -*- coding: utf-8 -*-
#
# Copyright 2015 Dell, Inc.
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
Test class for DRAC BIOS interface
"""

import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import bios
from ironic.drivers.modules.drac import client as drac_client
from ironic.drivers.modules.drac import management as drac_mgmt
from ironic.drivers.modules.drac import resource_uris
from ironic.tests.unit.conductor import utils as mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import bios_wsman_mock
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils
from six.moves.urllib.parse import unquote

FAKE_DRAC = db_utils.get_test_drac_info()


def _base_config(responses=[]):
    for resource in [resource_uris.DCIM_BIOSEnumeration,
                     resource_uris.DCIM_BIOSString,
                     resource_uris.DCIM_BIOSInteger]:
        xml_root = test_utils.mock_wsman_root(
            bios_wsman_mock.Enumerations[resource]['XML'])
        responses.append(xml_root)
    return responses


def _set_config(responses=[]):
    ccj_xml = test_utils.build_soap_xml([{'DCIM_LifecycleJob':
                                          {'Name': 'fake'}}],
                                        resource_uris.DCIM_LifecycleJob)
    responses.append(test_utils.mock_wsman_root(ccj_xml))
    return _base_config(responses)


def _mock_pywsman_responses(client, responses):
    mpw = client.Client.return_value
    mpw.enumerate.side_effect = responses
    return mpw


@mock.patch.object(drac_client, 'pywsman')
class DracBiosTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracBiosTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=FAKE_DRAC)

    def test_get_config(self, client):
        _mock_pywsman_responses(client, _base_config())
        expected = {}
        for resource in [resource_uris.DCIM_BIOSEnumeration,
                         resource_uris.DCIM_BIOSString,
                         resource_uris.DCIM_BIOSInteger]:
            expected.update(bios_wsman_mock.Enumerations[resource]['Dict'])
        result = bios.get_config(self.node)
        self.assertEqual(expected, result)

    def test_set_config_empty(self, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            res = bios.set_config(task)
        self.assertFalse(res)

    def test_set_config_nochange(self, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            res = bios.set_config(task,
                                  MemTest='Disabled',
                                  ProcCStates='Disabled',
                                  SystemModelName='PowerEdge R630',
                                  AssetTag=None,
                                  Proc1NumCores=8,
                                  AcPwrRcvryUserDelay=60)
        self.assertFalse(res)

    def test_set_config_ro(self, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationFailed,
                              bios.set_config, task,
                              ProcCStates="Enabled")

    def test_set_config_enum_invalid(self, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationFailed,
                              bios.set_config, task,
                              MemTest="Never")

    def test_set_config_string_toolong(self, client):
        _mock_pywsman_responses(client, _set_config())
        tag = ('Never have I seen such a silly long asset tag!  '
               'It is really rather ridiculous, don\'t you think?')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationFailed,
                              bios.set_config, task,
                              AssetTag=tag)

    def test_set_config_string_nomatch(self, client):
        _mock_pywsman_responses(client, _set_config())
        tag = unquote('%80')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationFailed,
                              bios.set_config, task,
                              AssetTag=tag)

    def test_set_config_integer_toosmall(self, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationFailed,
                              bios.set_config, task,
                              AcPwrRcvryUserDelay=0)

    def test_set_config_integer_toobig(self, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationFailed,
                              bios.set_config, task,
                              AcPwrRcvryUserDelay=600)

    def test_set_config_needreboot(self, client):
        mock_pywsman = _mock_pywsman_responses(client, _set_config())
        invoke_xml = test_utils.mock_wsman_root(
            bios_wsman_mock.Invoke_Commit)
        # TODO(victor-lowther) This needs more work.
        # Specifically, we will need to verify that
        # invoke was handed the XML blob we expected.
        mock_pywsman.invoke.return_value = invoke_xml
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            res = bios.set_config(task,
                                  AssetTag="An Asset Tag",
                                  MemTest="Enabled")
        self.assertTrue(res)

    @mock.patch.object(drac_mgmt, 'check_for_config_job',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, 'create_config_job', spec_set=True,
                       autospec=True)
    def test_commit_config(self, mock_ccj, mock_cfcj, client):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            bios.commit_config(task)
        self.assertTrue(mock_cfcj.called)
        self.assertTrue(mock_ccj.called)

    @mock.patch.object(drac_client.Client, 'wsman_invoke', spec_set=True,
                       autospec=True)
    def test_abandon_config(self, mock_wi, client):
        _mock_pywsman_responses(client, _set_config())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            bios.abandon_config(task)
        self.assertTrue(mock_wi.called)
