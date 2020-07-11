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

Allows overriding of config for use of fakes, and some magic for
inline callbacks.

"""

import copy
import os
import subprocess
import sys
import tempfile
from unittest import mock

import eventlet
eventlet.monkey_patch(os=False)
import fixtures
from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_config import fixture as config_fixture
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from oslotest import base as oslo_test_base

from ironic.common import config as ironic_config
from ironic.common import context as ironic_context
from ironic.common import driver_factory
from ironic.common import hash_ring
from ironic.common import utils as common_utils
from ironic.conf import CONF
from ironic.drivers import base as drivers_base
from ironic.objects import base as objects_base
from ironic.tests.unit import policy_fixture


logging.register_options(CONF)
logging.setup(CONF, 'ironic')


# NOTE(rpittau) this function allows autospec for classmethods and
# staticmethods in Python 3.6, while no issue occurs in Python 3.7
# and later.
# For more info please see: http://bugs.python.org/issue23078
def _patch_mock_callable(obj):
    if isinstance(obj, type):
        return True
    if getattr(obj, '__call__', None) is not None:
        return True
    if (isinstance(obj, (staticmethod, classmethod))
            and mock._callable(obj.__func__)):
        return True
    return False


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


class TestCase(oslo_test_base.BaseTestCase):
    """Test case base class for all unit tests."""

    # By default block execution of utils.execute() and related functions.
    block_execute = True

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()
        self.context = ironic_context.get_admin_context()
        self._set_config()
        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry
        self._base_test_obj_backup = copy.copy(
            objects_base.IronicObjectRegistry.obj_classes())
        self.addCleanup(self._restore_obj_registry)

        self.addCleanup(self._clear_attrs)
        self.addCleanup(hash_ring.HashRingManager().reset)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

        driver_factory.HardwareTypesFactory._extension_manager = None
        for factory in driver_factory._INTERFACE_LOADERS.values():
            factory._extension_manager = None

        # Ban running external processes via 'execute' like functions. If the
        # patched function is called, an exception is raised to warn the
        # tester.
        if self.block_execute:
            # NOTE(jlvillal): Intentionally not using mock as if you mock a
            # mock it causes things to not work correctly. As doing an
            # autospec=True causes strangeness. By using a simple function we
            # can then mock it without issue.
            self.patch(processutils, 'execute', do_not_call)
            self.patch(subprocess, 'call', do_not_call)
            self.patch(subprocess, 'check_call', do_not_call)
            self.patch(subprocess, 'check_output', do_not_call)
            self.patch(utils, 'execute', do_not_call)
            # subprocess.Popen is a class
            self.patch(subprocess, 'Popen', DoNotCallPopen)

        if sys.version_info < (3, 7):
            _patch_mock_callable._old_func = mock._callable
            mock._callable = _patch_mock_callable

    def _set_config(self):
        self.cfg_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config(use_stderr=False,
                    tempdir=tempfile.tempdir)
        self.config(cleaning_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(provisioning_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(rescuing_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(enabled_hardware_types=['fake-hardware',
                                            'manual-management'])
        for iface in drivers_base.ALL_INTERFACES:
            default = None

            # Restore some reasonable defaults
            if iface == 'network':
                values = ['flat', 'noop', 'neutron']
            else:
                values = ['fake']

            if iface == 'deploy':
                values.extend(['iscsi', 'direct'])
            elif iface == 'boot':
                values.append('pxe')
            elif iface == 'storage':
                default = 'noop'
                values.append('noop')
            elif iface not in {'network', 'power', 'management'}:
                values.append('no-%s' % iface)

            self.config(**{'enabled_%s_interfaces' % iface: values,
                           'default_%s_interface' % iface: default})
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

    def config_temp_dir(self, option, group=None):
        """Override a config option with a temporary directory."""
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: common_utils.rmtree_without_raise(temp_dir))
        self.config(**{option: temp_dir, 'group': group})

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


def do_not_call(*args, **kwargs):
    """Helper function to raise an exception if it is called"""
    raise Exception(
        "Don't call ironic_lib.utils.execute() / "
        "processutils.execute() or similar functions in tests!")


class DoNotCallPopen(object):
    """Helper class to mimic subprocess.popen()

    It's job is to raise an exception if it is called. We create stub functions
    so mocks that use autospec=True will work.
    """
    def __init__(self, *args, **kwargs):
        do_not_call(*args, **kwargs)

    def communicate(input=None):
        pass

    def kill():
        pass

    def poll():
        pass

    def terminate():
        pass

    def wait():
        pass
