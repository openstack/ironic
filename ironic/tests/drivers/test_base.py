# Copyright 2014 Cisco Systems, Inc.
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

from ironic.common import exception
from ironic.drivers import base as driver_base
from ironic.tests import base


class FakeVendorInterface(driver_base.VendorInterface):
    def get_properties(self):
        pass

    @driver_base.passthru('noexception')
    def _noexception(self):
        return "Fake"

    @driver_base.passthru('ironicexception')
    def _ironicexception(self):
        raise exception.IronicException("Fake!")

    @driver_base.passthru('normalexception')
    def _normalexception(self):
        raise Exception("Fake!")

    def validate(self, task, **kwargs):
        pass

    def vendor_passthru(self, task, **kwargs):
        method = kwargs['method']
        if method == "noexception":
            self._noexception()
        elif method == "ironicexception":
            self._ironicexception()
        elif method == "normalexception":
            self._normalexception()


class PassthruDecoratorTestCase(base.TestCase):

    def setUp(self):
        super(PassthruDecoratorTestCase, self).setUp()
        self.fvi = FakeVendorInterface()
        driver_base.LOG = mock.Mock()

    def test_passthru_noexception(self):
        result = self.fvi._noexception()
        self.assertEqual("Fake", result)

    def test_passthru_ironicexception(self):
        self.assertRaises(exception.IronicException,
            self.fvi.vendor_passthru, mock.ANY, method="ironicexception")
        driver_base.LOG.exception.assert_called_with(
            mock.ANY, 'ironicexception')

    def test_passthru_nonironicexception(self):
        self.assertRaises(exception.VendorPassthruException,
            self.fvi.vendor_passthru, mock.ANY, method="normalexception")
        driver_base.LOG.exception.assert_called_with(
            mock.ANY, 'normalexception')
