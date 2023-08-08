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


from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import cpu_capabilities as cpu_hook
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class CPUCapabilitiesTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = {'cpu': {'flags': ['aes', 'aes', 'pdpe1gb']}}
        self.plugin_data = {'plugin_data': 'fake-plugin-data'}

    def test_cpu_capabilities(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            cpu_hook.CPUCapabilitiesHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.node.refresh()
            result = self.node.properties.get('capabilities', '')
            self.assertEqual(result, 'cpu_aes:true,cpu_hugepages_1g:true')
