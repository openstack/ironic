# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Base classes for our unit tests.

Allows overriding of config for use of fakes, and some black magic for
inline callbacks.

"""

import copy
import os
import subprocess
import sys
import tempfile

import eventlet
eventlet.monkey_patch(os=False)
import fixtures
from ironic_lib import utils
import mock
from oslo_concurrency import processutils
from oslo_config import fixture as config_fixture
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
import testtools

from ironic.common import config as ironic_config
from ironic.common import context as ironic_context
from ironic.common import driver_factory
from ironic.common import hash_ring
from ironic.conf import CONF
from ironic.drivers import base as drivers_base
from ironic.objects import base as objects_base
from ironic.tests.unit import policy_fixture


logging.register_options(CONF)
logging.setup(CONF, 'ironic')


class ReplaceModule(fixtures.Fixture):
    """Replace a module with a fake module."""

    def __init__(self, name, new_value):
        self.name = name
        self.new_value = new_value

    def _restore(self, old_value):
        sys.modules[self.name] = old_value

    def setUp(self):
        super(ReplaceModule, self).setUp()
        old_value = sys.modules.get(self.name)
        sys.modules[self.name] = self.new_value
        self.addCleanup(self._restore, old_value)


class TestingException(Exception):
    pass


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    # By default block execution of utils.execute() and related functions.
    block_execute = True

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()
        self.context = ironic_context.get_admin_context()
        test_timeout = os.environ.get('OS_TEST_TIMEOUT', 0)
        try:
            test_timeout = int(test_timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            test_timeout = 0
        if test_timeout > 0:
            self.useFixture(fixtures.Timeout(test_timeout, gentle=True))
        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())

        if (os.environ.get('OS_STDOUT_CAPTURE') == 'True' or
                os.environ.get('OS_STDOUT_CAPTURE') == '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_CAPTURE') == 'True' or
                os.environ.get('OS_STDERR_CAPTURE') == '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))

        self.log_fixture = self.useFixture(fixtures.FakeLogger())
        self._set_config()
        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry
        objects_base.IronicObject.indirection_api = None
        self._base_test_obj_backup = copy.copy(
            objects_base.IronicObjectRegistry.obj_classes())
        self.addCleanup(self._restore_obj_registry)

        self.addCleanup(self._clear_attrs)
        self.addCleanup(hash_ring.HashRingManager().reset)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

        driver_factory.DriverFactory._extension_manager = None
        driver_factory.HardwareTypesFactory._extension_manager = None
        for factory in driver_factory._INTERFACE_LOADERS.values():
            factory._extension_manager = None

        # Block access to utils.execute() and related functions.
        # NOTE(bigjools): Not using a decorator on tests because I don't
        # want to force every test method to accept a new arg. Instead, they
        # can override or examine this self._exec_patch Mock as needed.
        if self.block_execute:
            self._exec_patch = mock.Mock()
            self._exec_patch.side_effect = Exception(
                "Don't call ironic_lib.utils.execute() / "
                "processutils.execute() or similar functions in tests!")

            self.patch(processutils, 'execute', self._exec_patch)
            self.patch(subprocess, 'Popen', self._exec_patch)
            self.patch(subprocess, 'call', self._exec_patch)
            self.patch(subprocess, 'check_call', self._exec_patch)
            self.patch(subprocess, 'check_output', self._exec_patch)
            self.patch(utils, 'execute', self._exec_patch)

    def _set_config(self):
        self.cfg_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config(use_stderr=False,
                    fatal_exception_format_errors=True,
                    tempdir=tempfile.tempdir)
        self.config(cleaning_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(provisioning_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(enabled_drivers=['fake'])
        self.config(enabled_hardware_types=['fake-hardware'])
        self.config(enabled_network_interfaces=['flat', 'noop', 'neutron'])
        for iface in drivers_base.ALL_INTERFACES:
            self.config(**{'default_%s_interface' % iface: None})
        self.set_defaults(host='fake-mini',
                          debug=True)
        self.set_defaults(connection="sqlite://",
                          sqlite_synchronous=False,
                          group='database')
        ironic_config.parse_args([], default_config_files=[])

    def _restore_obj_registry(self):
        objects_base.IronicObjectRegistry._registry._obj_classes = (
            self._base_test_obj_backup)

    def _clear_attrs(self):
        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__ if k[0] != '_']:
            del self.__dict__[key]

    def config(self, **kw):
        """Override config options for a test."""
        self.cfg_fixture.config(**kw)

    def set_defaults(self, **kw):
        """Set default values of config options."""
        group = kw.pop('group', None)
        for o, v in kw.items():
            self.cfg_fixture.set_default(o, v, group=group)

    def path_get(self, project_file=None):
        """Get the absolute path to a file. Used for testing the API.

        :param project_file: File whose path to return. Default: None.
        :returns: path to the specified file, or path to project root.
        """
        root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            '..',
                                            '..',
                                            )
                               )
        if project_file:
            return os.path.join(root, project_file)
        else:
            return root

    def assertJsonEqual(self, expected, observed):
        """Asserts that 2 complex data structures are json equivalent."""
        self.assertEqual(jsonutils.dumps(expected, sort_keys=True),
                         jsonutils.dumps(observed, sort_keys=True))

    def assertNotificationEqual(self, notif_args, service, host, event_type,
                                level):
        """Asserts properties of arguments passed when creating a notification.

           :param notif_args: dict of arguments notification instantiated with
           :param service: expected service that emits the notification
           :param host: expected host that emits the notification
           :param event_type: expected value of EventType field of notification
                              as a string
           :param level: expected NotificationLevel
       """
        self.assertEqual(service, notif_args['publisher'].service)
        self.assertEqual(host, notif_args['publisher'].host)
        self.assertEqual(event_type, notif_args['event_type'].
                         to_event_type_field())
        self.assertEqual(level, notif_args['level'])
