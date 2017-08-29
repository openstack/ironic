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

import imp
import inspect
import os
import sys

import mock
from oslo_utils import uuidutils

from ironic.tests import base as test_base


class TestExposedAPIMethodsCheckPolicy(test_base.TestCase):
    """Ensure that all exposed HTTP endpoints call authorize."""

    def setUp(self):
        super(TestExposedAPIMethodsCheckPolicy, self).setUp()
        self.original_method = sys.modules['ironic.api.expose'].expose
        self.exposed_methods = set()

        def expose_and_track(*args, **kwargs):
            def wrap(f):
                if f not in self.exposed_methods:
                    self.exposed_methods.add(f)
                e = self.original_method(*args, **kwargs)
                return e(f)
            return wrap

        p = mock.patch('ironic.api.expose.expose', expose_and_track)
        p.start()
        self.addCleanup(p.stop)

    def _test(self, module):
        module_path = os.path.abspath(sys.modules[module].__file__)
        # NOTE(vdrok): coverage runs on compiled .pyc files, which breaks
        # load_source. Strip c and o letters from the end of the module path,
        # just in case someone tries to use .pyo or .pyc for whatever reason
        imp.load_source(uuidutils.generate_uuid(), module_path.rstrip('co'))

        for func in self.exposed_methods:
            src = inspect.getsource(func)
            self.assertIn('policy.authorize', src,
                          'policy.authorize call not found in exposed '
                          'method %s' % func)
            self.assertIn('context.to_policy_values', src,
                          'context.to_policy_values call not found in '
                          'exposed method %s' % func)

    def test_chasis_api_policy(self):
        self._test('ironic.api.controllers.v1.chassis')

    def test_driver_api_policy(self):
        self._test('ironic.api.controllers.v1.driver')

    def test_node_api_policy(self):
        self._test('ironic.api.controllers.v1.node')

    def test_port_api_policy(self):
        self._test('ironic.api.controllers.v1.port')

    def test_portgroup_api_policy(self):
        self._test('ironic.api.controllers.v1.portgroup')

    def test_ramdisk_api_policy(self):
        self._test('ironic.api.controllers.v1.ramdisk')
