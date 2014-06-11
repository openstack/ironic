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

This is also an example of some kinds of things which can be done within
drivers.  For instance, the MultipleVendorInterface class demonstrates how to
load more than one interface and wrap them in some logic to route incoming
vendor_passthru requests appropriately. This can be useful eg. when mixing
functionality between a power interface and a deploy interface, when both rely
on seprate vendor_passthru methods.
"""

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.drivers import base


def _raise_unsupported_error(method=None):
    if method:
        raise exception.InvalidParameterValue(_(
            "Unsupported method (%s) passed through to vendor extension.")
            % method)
    raise exception.InvalidParameterValue(_(
        "Method not specified when calling vendor extension."))


class FakePower(base.PowerInterface):
    """Example implementation of a simple power interface."""

    def validate(self, task, node):
        pass

    def get_power_state(self, task):
        return task.node.power_state

    def set_power_state(self, task, power_state):
        if power_state not in [states.POWER_ON, states.POWER_OFF]:
            raise exception.InvalidParameterValue(_("set_power_state called "
                    "with an invalid power state: %s.") % power_state)
        task.node.power_state = power_state

    def reboot(self, task):
        pass


class FakeDeploy(base.DeployInterface):
    """Example imlementation of a deploy interface that uses a
       separate power interface.
    """

    def validate(self, task, node):
        pass

    def deploy(self, task):
        pass

    def tear_down(self, task):
        pass

    def prepare(self, task):
        pass

    def clean_up(self, task):
        pass

    def take_over(self, task):
        pass


class FakeVendorA(base.VendorInterface):
    """Example implementation of a vendor passthru interface."""

    def validate(self, task, **kwargs):
        method = kwargs.get('method')
        if method == 'first_method':
            bar = kwargs.get('bar')
            if not bar:
                raise exception.InvalidParameterValue(_(
                    "Parameter 'bar' not passed to method 'first_method'."))
            return
        _raise_unsupported_error(method)

    def _private_method(self, task, bar):
        return True if bar == 'baz' else False

    def vendor_passthru(self, task, **kwargs):
        method = kwargs.get('method')
        if method == 'first_method':
            bar = kwargs.get('bar')
            return self._private_method(task, bar)
        _raise_unsupported_error(method)


class FakeVendorB(base.VendorInterface):
    """Example implementation of a secondary vendor passthru."""

    def validate(self, task, **kwargs):
        method = kwargs.get('method')
        if method == 'second_method':
            bar = kwargs.get('bar')
            if not bar:
                raise exception.InvalidParameterValue(_(
                    "Parameter 'bar' not passed to method 'second_method'."))
            return
        _raise_unsupported_error(method)

    def _private_method(self, task, bar):
        return True if bar == 'kazoo' else False

    def vendor_passthru(self, task, **kwargs):
        method = kwargs.get('method')
        if method == 'second_method':
            bar = kwargs.get('bar')
            return self._private_method(task, bar)
        _raise_unsupported_error(method)


class FakeConsole(base.ConsoleInterface):
    """Example implementation of a simple console interface."""

    def validate(self, task, node):
        return True

    def start_console(self, task):
        pass

    def stop_console(self, task):
        pass

    def get_console(self, task):
        return {}


class FakeManagement(base.ManagementInterface):
    """Example implementation of a simple management interface."""

    def validate(self, task, node):
        return True

    def get_supported_boot_devices(self):
        return [boot_devices.PXE]

    def set_boot_device(self, task, device, **kwargs):
        if device not in self.get_supported_boot_devices():
            raise exception.InvalidParameterValue(_(
                "Invalid boot device %s specified.") % device)

    def get_boot_device(self, task):
        return boot_devices.PXE
