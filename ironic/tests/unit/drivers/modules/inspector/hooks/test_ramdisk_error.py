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


from ironic.common import exception
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import ramdisk_error \
    as ramdisk_error_hook
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class RamdiskErrorTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = {'fake': 'fake-inventory'}
        self.plugin_data = {'error': 'There was an error!'}

    def test_ramdisk_error(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            hook = ramdisk_error_hook.RamdiskErrorHook()
            self.assertRaises(exception.HardwareInspectionFailure,
                              hook.preprocess,
                              task=task, inventory=self.inventory,
                              plugin_data=self.plugin_data)
