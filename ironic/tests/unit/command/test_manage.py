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

import contextlib
import io
from unittest import mock

from ironic.command import manage
from ironic.drivers import base as driver_base
from ironic.tests import base


class FakePlugin(object):
    supported = True


class FakeUnsupportedPlugin(FakePlugin):
    supported = False


def _fake_entry_point(name, value, dist_name='ironic', plugin=FakePlugin,
                      load_error=None):
    ep = mock.Mock(spec=['name', 'value', 'dist', 'load'])
    ep.name = name
    ep.value = value
    ep.dist = mock.Mock(spec=['name'])
    ep.dist.name = dist_name
    if load_error is not None:
        ep.load.side_effect = load_error
    else:
        ep.load.return_value = plugin
    return ep


def _capture_stdout(func, *args, **kwargs):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        func(*args, **kwargs)
    return output.getvalue()


class PrintEntryPointGroupTestCase(base.TestCase):

    @mock.patch.object(manage.metadata, 'entry_points', autospec=True)
    def test_statuses_and_sorting(self, mock_eps):
        mock_eps.return_value = [
            _fake_entry_point('working', 'some.module:Working'),
            _fake_entry_point('broken', 'other.module:Broken',
                              load_error=ImportError(
                                  "No module named 'somelib'")),
            _fake_entry_point('ancient', 'old.module:Ancient',
                              plugin=FakeUnsupportedPlugin),
        ]

        output = _capture_stdout(manage._print_entry_point_group,
                                 'test.group', 'enabled_test', 'Test things')

        mock_eps.assert_called_once_with(group='test.group')
        lines = output.splitlines()
        self.assertEqual('Test things (for [DEFAULT]enabled_test):',
                         lines[0])
        # Entries are sorted by name and aligned to the longest name
        self.assertEqual(
            '  ancient  old.module:Ancient (ironic) '
            '(deprecated/unsupported)',
            lines[1])
        self.assertEqual(
            "  broken   (failed to load: No module named 'somelib')",
            lines[2])
        self.assertEqual('  working  some.module:Working (ironic)',
                         lines[3])

    @mock.patch.object(manage.metadata, 'entry_points', autospec=True)
    def test_no_dist(self, mock_eps):
        ep = _fake_entry_point('working', 'some.module:Working')
        ep.dist = None
        mock_eps.return_value = [ep]

        output = _capture_stdout(manage._print_entry_point_group,
                                 'test.group', 'enabled_test', 'Test things')

        self.assertIn('  working  some.module:Working\n', output)

    @mock.patch.object(manage.metadata, 'entry_points', autospec=True)
    def test_empty_group(self, mock_eps):
        mock_eps.return_value = []

        output = _capture_stdout(manage._print_entry_point_group,
                                 'test.group', 'enabled_test', 'Test things')

        self.assertIn('(no entry points found)', output)


class DriverCommandsTestCase(base.TestCase):

    def setUp(self):
        super(DriverCommandsTestCase, self).setUp()
        self.commands = manage.DriverCommands()

    @mock.patch.object(manage, '_print_entry_point_group', autospec=True)
    def test_hardware_types(self, mock_print):
        self.commands.hardware_types()
        mock_print.assert_called_once_with('ironic.hardware.types',
                                           'enabled_hardware_types',
                                           'Hardware types')

    def test_select_interface_types_all(self):
        self.assertEqual(sorted(driver_base.ALL_INTERFACES),
                         manage._select_interface_types([]))

    def test_select_interface_types_filtered(self):
        self.assertEqual(
            ['network', 'deploy'],
            manage._select_interface_types(['network', 'deploy', 'network']))

    def test_select_interface_types_unknown(self):
        exc = self.assertRaises(SystemExit, manage._select_interface_types,
                                ['deploy', 'magic'])
        self.assertEqual(2, exc.code)


class InterfacesOutputTestCase(base.TestCase):

    @mock.patch.object(manage, '_print_entry_point_group', autospec=True)
    def test_print_interfaces(self, mock_print):
        manage._print_interfaces(['deploy', 'power'])
        mock_print.assert_has_calls([
            mock.call('ironic.hardware.interfaces.deploy',
                      'enabled_deploy_interfaces', 'Deploy interfaces'),
            mock.call('ironic.hardware.interfaces.power',
                      'enabled_power_interfaces', 'Power interfaces'),
        ])


class RealEntryPointsTestCase(base.TestCase):
    """Smoke tests against the entry points of the installed ironic."""

    def test_hardware_types(self):
        output = _capture_stdout(manage.DriverCommands().hardware_types)
        self.assertIn('[DEFAULT]enabled_hardware_types', output)
        self.assertIn('ipmi', output)
        self.assertIn('redfish', output)
        self.assertNotIn('failed to load', output)

    def test_interfaces(self):
        output = _capture_stdout(manage._print_interfaces, ['deploy'])
        self.assertIn('[DEFAULT]enabled_deploy_interfaces', output)
        self.assertIn('direct', output)
