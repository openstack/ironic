# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

import mock

from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common as ov_common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.tests.unit.drivers.modules.oneview import test_common


class OneViewInspectTestCase(test_common.BaseOneViewTest):

    def setUp(self):
        super(OneViewInspectTestCase, self).setUp()
        self.config(enabled=True, group='inspector')
        self.config(manager_url='https://1.2.3.4', group='oneview')

    def test_get_properties(self):
        expected = deploy_utils.get_properties()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.inspect.get_properties())

    @mock.patch.object(ov_common, 'validate_oneview_resources_compatibility',
                       autospect=True)
    def test_validate(self, mock_validate):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.validate(task)
            self.assertTrue(mock_validate.called)

    @mock.patch.object(deploy_utils, 'allocate_server_hardware_to_ironic',
                       autospect=True)
    def test_inspect_hardware(self, mock_allocate_server_hardware_to_ironic):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertTrue(mock_allocate_server_hardware_to_ironic.called)
