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
Test class for DRAC client wrapper.
"""

import mock
from xml.etree import ElementTree

from ironic.common import exception
from ironic.drivers.modules.drac import client as drac_client
from ironic.tests import base
from ironic.tests.db import utils as db_utils
from ironic.tests.drivers.drac import utils as test_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_client, 'pywsman')
class DracClientTestCase(base.TestCase):

    def test_wsman_enumerate(self, mock_client_pywsman):
        mock_xml = test_utils.mock_wsman_root('<test></test>')
        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.enumerate.return_value = mock_xml

        resource_uri = 'https://foo/wsman'
        mock_options = mock_client_pywsman.ClientOptions.return_value
        client = drac_client.Client(**INFO_DICT)
        client.wsman_enumerate(resource_uri, mock_options)

        mock_options.set_flags.assert_called_once_with(
            mock_client_pywsman.FLAG_ENUMERATION_OPTIMIZATION)
        mock_options.set_max_elements.assert_called_once_with(100)
        mock_pywsman_client.enumerate.assert_called_once_with(mock_options,
            None, resource_uri)
        mock_xml.context.assert_called_once_with()

    def test_wsman_enumerate_with_additional_pull(self, mock_client_pywsman):
        mock_root = mock.Mock()
        mock_root.string.side_effect = [test_utils.build_soap_xml(
                                           [{'item1': 'test1'}]),
                                        test_utils.build_soap_xml(
                                           [{'item2': 'test2'}])]
        mock_xml = mock.Mock()
        mock_xml.root.return_value = mock_root
        mock_xml.context.side_effect = [42, 42, None]

        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.enumerate.return_value = mock_xml
        mock_pywsman_client.pull.return_value = mock_xml

        resource_uri = 'https://foo/wsman'
        mock_options = mock_client_pywsman.ClientOptions.return_value
        client = drac_client.Client(**INFO_DICT)
        result = client.wsman_enumerate(resource_uri, mock_options)

        # assert the XML was merged
        result_string = ElementTree.tostring(result)
        self.assertIn('<item1>test1</item1>', result_string)
        self.assertIn('<item2>test2</item2>', result_string)

        mock_options.set_flags.assert_called_once_with(
            mock_client_pywsman.FLAG_ENUMERATION_OPTIMIZATION)
        mock_options.set_max_elements.assert_called_once_with(100)
        mock_pywsman_client.enumerate.assert_called_once_with(mock_options,
            None, resource_uri)

    def test_wsman_enumerate_filter_query(self, mock_client_pywsman):
        mock_xml = test_utils.mock_wsman_root('<test></test>')
        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.enumerate.return_value = mock_xml

        resource_uri = 'https://foo/wsman'
        mock_options = mock_client_pywsman.ClientOptions.return_value
        mock_filter = mock_client_pywsman.Filter.return_value
        client = drac_client.Client(**INFO_DICT)
        filter_query = 'SELECT * FROM foo'
        client.wsman_enumerate(resource_uri, mock_options,
                               filter_query=filter_query)

        mock_filter.simple.assert_called_once_with(mock.ANY, filter_query)
        mock_pywsman_client.enumerate.assert_called_once_with(mock_options,
            mock_filter, resource_uri)
        mock_xml.context.assert_called_once_with()

    def test_wsman_enumerate_invalid_filter_dialect(self, mock_client_pywsman):
        client = drac_client.Client(**INFO_DICT)
        self.assertRaises(exception.DracInvalidFilterDialect,
                          client.wsman_enumerate, 'https://foo/wsman',
                          mock.Mock(), filter_query='foo',
                          filter_dialect='invalid')

    def test_wsman_invoke(self, mock_client_pywsman):
        mock_xml = test_utils.mock_wsman_root('<test></test>')
        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.invoke.return_value = mock_xml

        resource_uri = 'https://foo/wsman'
        mock_options = mock_client_pywsman.ClientOptions.return_value
        method_name = 'method'
        client = drac_client.Client(**INFO_DICT)
        client.wsman_invoke(resource_uri, mock_options, method_name)

        mock_pywsman_client.invoke.assert_called_once_with(mock_options,
            resource_uri, method_name)
