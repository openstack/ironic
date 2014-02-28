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

    def get_power_state(self, task, node):
        return node.get('power_state', states.NOSTATE)

    def set_power_state(self, task, node, power_state):
        if power_state not in [states.POWER_ON, states.POWER_OFF]:
            raise exception.InvalidParameterValue(_("set_power_state called "
                    "with an invalid power state: %s.") % power_state)
        node['power_state'] = power_state

    def reboot(self, task, node):
        pass


class FakeDeploy(base.DeployInterface):
    """Example imlementation of a deploy interface that uses a
       separate power interface.
    """

    def validate(self, task, node):
        pass

    def deploy(self, task, node):
        pass

    def tear_down(self, task, node):
        pass

    def prepare(self, task, node):
        pass

    def clean_up(self, task, node):
        pass

    def take_over(self, task, node):
        pass


class FakeVendorA(base.VendorInterface):
    """Example implementation of a vendor passthru interface."""

    def validate(self, task, node, **kwargs):
        method = kwargs.get('method')
        if method == 'first_method':
            bar = kwargs.get('bar')
            if not bar:
                raise exception.InvalidParameterValue(_(
                    "Parameter 'bar' not passed to method 'first_method'."))
            return
        _raise_unsupported_error(method)

    def _private_method(self, task, node, bar):
        return True if bar == 'baz' else False

    def vendor_passthru(self, task, node, **kwargs):
        method = kwargs.get('method')
        if method == 'first_method':
            bar = kwargs.get('bar')
            return self._private_method(task, node, bar)
        _raise_unsupported_error(method)


class FakeVendorB(base.VendorInterface):
    """Example implementation of a secondary vendor passthru."""

    def validate(self, task, node, **kwargs):
        method = kwargs.get('method')
        if method == 'second_method':
            bar = kwargs.get('bar')
            if not bar:
                raise exception.InvalidParameterValue(_(
                    "Parameter 'bar' not passed to method 'second_method'."))
            return
        _raise_unsupported_error(method)

    def _private_method(self, task, node, bar):
        return True if bar == 'kazoo' else False

    def vendor_passthru(self, task, node, **kwargs):
        method = kwargs.get('method')
        if method == 'second_method':
            bar = kwargs.get('bar')
            return self._private_method(task, node, bar)
        _raise_unsupported_error(method)


class MultipleVendorInterface(base.VendorInterface):
    """Example of a wrapper around two VendorInterfaces."""

    def __init__(self, first, second):
        self.interface_one = first
        self.interface_two = second
        self.mapping = {'first_method': self.interface_one,
                        'second_method': self.interface_two}

    def _map(self, **kwargs):
        """Map methods to interfaces.

        :returns: an instance of a VendorInterface
        :raises: InvalidParameterValue if **kwargs does not contain 'method'
                 or if the method can not be mapped to an interface.

        """
        method = kwargs.get('method')
        return self.mapping.get(method) or _raise_unsupported_error(method)

    def validate(self, *args, **kwargs):
        """Call validate on the appropriate interface only."""
        route = self._map(**kwargs)
        route.validate(*args, **kwargs)

    def vendor_passthru(self, task, node, **kwargs):
        """Call vendor_passthru on the appropriate interface only."""
        route = self._map(**kwargs)
        return route.vendor_passthru(task, node, **kwargs)


class FakeConsole(base.ConsoleInterface):
    """Example implementation of a simple console interface."""

    def validate(self, task, node):
        return True

    def start_console(self, task, node):
        pass

    def stop_console(self, task, node):
        pass

    def get_console(self, task, node):
        return {}
