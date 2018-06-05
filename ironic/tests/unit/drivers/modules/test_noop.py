# Copyright 2016 Red Hat, Inc.
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

import mock
import stevedore

from ironic.common import exception
from ironic.drivers.modules import noop
from ironic.tests import base


# TODO(dtantsur): move to ironic.common.driver_factory
def hardware_interface_extension_manager(interface):
    """Get a Stevedore extension manager for given hardware interface."""
    return stevedore.extension.ExtensionManager(
        'ironic.hardware.interfaces.%s' % interface,
        invoke_on_load=True)


class NoInterfacesTestCase(base.TestCase):
    iface_types = ['bios', 'console', 'inspect', 'raid', 'rescue', 'vendor']
    task = mock.Mock(node=mock.Mock(driver='pxe_foobar', spec=['driver']),
                     spec=['node'])

    def test_bios(self):
        self.assertRaises(exception.UnsupportedDriverExtension,
                          getattr(noop.NoBIOS(), 'apply_configuration'),
                          self.task, '')
        self.assertRaises(exception.UnsupportedDriverExtension,
                          getattr(noop.NoBIOS(), 'factory_reset'),
                          self.task)

    def test_console(self):
        for method in ('start_console', 'stop_console', 'get_console'):
            self.assertRaises(exception.UnsupportedDriverExtension,
                              getattr(noop.NoConsole(), method),
                              self.task)

    def test_rescue(self):
        for method in ('rescue', 'unrescue'):
            self.assertRaises(exception.UnsupportedDriverExtension,
                              getattr(noop.NoRescue(), method),
                              self.task)

    def test_vendor(self):
        self.assertRaises(exception.UnsupportedDriverExtension,
                          noop.NoVendor().validate,
                          self.task, 'method')
        self.assertRaises(exception.UnsupportedDriverExtension,
                          noop.NoVendor().driver_validate,
                          'method')

    def test_inspect(self):
        self.assertRaises(exception.UnsupportedDriverExtension,
                          noop.NoInspect().inspect_hardware, self.task)

    def test_load_by_name(self):
        for iface_type in self.iface_types:
            mgr = hardware_interface_extension_manager(iface_type)
            inst = mgr['no-%s' % iface_type].obj
            self.assertEqual({}, inst.get_properties())
            self.assertRaises(exception.UnsupportedDriverExtension,
                              inst.validate, self.task)
