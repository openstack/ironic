# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
Fake driver interfaces used in testing.
"""

from ironic.common import exception
from ironic.common import states
from ironic.drivers import base


class FakePower(base.PowerInterface):
    """Example implementation of a simple power interface."""

    def validate(self, node):
        return True

    def get_power_state(self, task, node):
        return states.NOSTATE

    def set_power_state(self, task, node, power_state):
        pass

    def reboot(self, task, node):
        pass


class FakeDeploy(base.DeployInterface):
    """Example imlementation of a deploy interface that uses a
       separate power interface.
    """

    def validate(self, node):
        return True

    def deploy(self, task, node):
        pass

    def tear_down(self, task, node):
        pass


class FakeVendor(base.VendorInterface):
    """Example implementation of a vendor passthru interface."""

    def validate(self, node, **kwargs):
        method = kwargs.get('method')
        if not method:
            raise exception.InvalidParameterValue(_(
                "Invalid vendor passthru, no 'method' specified."))

        if method == 'foo':
            bar = kwargs.get('bar')
            if not bar:
                raise exception.InvalidParameterValue(_(
                                "Parameter not passed to Ironic."))

        else:
            raise exception.InvalidParameterValue(_(
                "Unsupported method (%s) passed through to vendor extension.")
                % method)

        return True

    def _foo(self, task, node, bar):
        return True if bar == 'baz' else False

    def vendor_passthru(self, task, node, **kwargs):
        method = kwargs.get('method')
        if method == 'foo':
            bar = kwargs.get('bar')
            return self._foo(task, node, bar)
