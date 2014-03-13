# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

from ironic.common import driver_factory
from ironic.common import exception
from ironic.db import api as db_api
from ironic.drivers.modules import fake
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import utils as db_utils


class UtilsTestCase(base.TestCase):

    def setUp(self):
        super(UtilsTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")
        self.node = db_utils.get_test_node()
        self.dbapi.create_node(self.node)

    @mock.patch.object(fake.FakeVendorA, 'validate')
    def test_vendor_interface_validate_valid_methods(self,
                                                     mock_fakea_validate):
        self.driver.vendor.validate(method='first_method')
        mock_fakea_validate.assert_called_once_with(method='first_method')

    def test_vendor_interface_validate_bad_method(self):
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.driver.vendor.validate, method='fake_method')

    def test_vendor_interface_validate_none_method(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.vendor.validate)

    @mock.patch.object(fake.FakeVendorA, 'vendor_passthru')
    @mock.patch.object(fake.FakeVendorB, 'vendor_passthru')
    def test_vendor_interface_route_valid_method(self, mock_fakeb_vendor,
                                                 mock_fakea_vendor):
        self.driver.vendor.vendor_passthru('task', 'node',
                                           method='first_method',
                                           param1='fake1', param2='fake2')
        mock_fakea_vendor.assert_called_once_with('task',
                                            'node',
                                            method='first_method',
                                            param1='fake1', param2='fake2')
        self.driver.vendor.vendor_passthru('task', 'node',
                                           method='second_method',
                                           param1='fake1', param2='fake2')
        mock_fakeb_vendor.assert_called_once_with('task',
                                            'node',
                                            method='second_method',
                                            param1='fake1', param2='fake2')
