# Copyright 2014 Rackspace, Inc.
# All Rights Reserved
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

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.dhcp import neutron
from ironic.dhcp import none
from ironic.tests import base


class TestDHCPFactory(base.TestCase):

    def setUp(self):
        super(TestDHCPFactory, self).setUp()
        self.config(enabled_drivers=['fake'])
        self.config(url='test-url',
                    url_timeout=30,
                    group='neutron')
        dhcp_factory.DHCPFactory._dhcp_provider = None

    def test_default_dhcp(self):
        # dhcp provider should default to neutron
        api = dhcp_factory.DHCPFactory()
        self.assertIsInstance(api.provider, neutron.NeutronDHCPApi)

    def test_set_none_dhcp(self):
        self.config(dhcp_provider='none',
                    group='dhcp')

        api = dhcp_factory.DHCPFactory()
        self.assertIsInstance(api.provider, none.NoneDHCPApi)

    def test_set_neutron_dhcp(self):
        self.config(dhcp_provider='neutron',
                    group='dhcp')

        api = dhcp_factory.DHCPFactory()
        self.assertIsInstance(api.provider, neutron.NeutronDHCPApi)

    def test_only_one_dhcp(self):
        self.config(dhcp_provider='none',
                    group='dhcp')
        dhcp_factory.DHCPFactory()

        with mock.patch.object(dhcp_factory.DHCPFactory,
                               '_set_dhcp_provider') as mock_set_dhcp:
            # There is already a dhcp_provider, so this shouldn't call
            # _set_dhcp_provider again.
            dhcp_factory.DHCPFactory()
            self.assertEqual(0, mock_set_dhcp.call_count)

    def test_set_bad_dhcp(self):
        self.config(dhcp_provider='bad_dhcp',
                    group='dhcp')

        self.assertRaises(exception.DHCPNotFound, dhcp_factory.DHCPFactory)
