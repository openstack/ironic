# Copyright 2014 Red Hat, Inc.
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

import mock

from ironic.nova.tests.virt.ironic import utils as ironic_utils
from ironic.nova.virt.ironic import client_wrapper

from nova import test

FAKE_CLIENT = ironic_utils.FakeClient()


@mock.patch.object(client_wrapper.IronicClientWrapper, '_multi_getattr')
@mock.patch.object(client_wrapper.IronicClientWrapper, '_get_client')
class IronicClientWrapperTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IronicClientWrapperTestCase, self).setUp()
        self.icli = client_wrapper.IronicClientWrapper()

    def test_call_good_no_args(self, mock_get_client, mock_multi_getattr):
        mock_get_client.return_value = FAKE_CLIENT
        self.icli.call("node.list")
        mock_get_client.assert_called_once_with()
        mock_multi_getattr.assert_called_once_with(FAKE_CLIENT, "node.list")
        mock_multi_getattr.return_value.assert_called_once_with()

    def test_call_good_with_args(self, mock_get_client, mock_multi_getattr):
        mock_get_client.return_value = FAKE_CLIENT
        self.icli.call("node.list", 'test', associated=True)
        mock_get_client.assert_called_once_with()
        mock_multi_getattr.assert_called_once_with(FAKE_CLIENT, "node.list")
        mock_multi_getattr.return_value.assert_called_once_with('test',
                                                               associated=True)
