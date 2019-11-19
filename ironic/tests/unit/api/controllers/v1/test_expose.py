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

from importlib import machinery
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
        machinery.SourceFileLoader(uuidutils.generate_uuid(),
                                   module_path).load_module()

        for func in self.exposed_methods:
            src = inspect.getsource(func)
            self.assertTrue(
                ('api_utils.check_node_policy_and_retrieve' in src) or
                ('api_utils.check_node_list_policy' in src) or
                ('self._get_node_and_topic' in src) or
                ('api_utils.check_port_policy_and_retrieve' in src) or
                ('api_utils.check_port_list_policy' in src) or
                ('policy.authorize' in src and
                 'context.to_policy_values' in src),
                'no policy check found in in exposed '
                'method %s' % func)

    def test_chassis_api_policy(self):
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

    def test_conductor_api_policy(self):
        self._test('ironic.api.controllers.v1.conductor')
