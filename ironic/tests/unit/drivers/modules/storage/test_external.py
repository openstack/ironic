# Copyright 2016 Hewlett Packard Enterprise Development Company LP.
# Copyright 2016 IBM Corp
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

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.storage import external
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


class ExternalInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ExternalInterfaceTestCase, self).setUp()
        self.config(enabled_storage_interfaces=['noop', 'external'],
                    enabled_boot_interfaces=['fake', 'pxe'])
        self.interface = external.ExternalStorage()

    @mock.patch.object(external, 'LOG', autospec=True)
    def test_validate_fails_with_ipxe_not_enabled(self, mock_log):
        """Ensure a validation failure is raised when iPXE not enabled."""
        self.node = object_utils.create_test_node(
            self.context, storage_interface='external', boot_interface='pxe')
        object_utils.create_test_volume_connector(
            self.context, node_id=self.node.id, type='iqn',
            connector_id='foo.address')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='2345')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
        self.assertTrue(mock_log.error.called)

    # Prevents creating iPXE boot script
    @mock.patch('ironic.drivers.modules.ipxe.iPXEBoot.__init__',
                lambda self: None)
    def test_should_write_image(self):
        self.node = object_utils.create_test_node(
            self.context, storage_interface='external')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234')

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertFalse(self.interface.should_write_image(task))

        self.node.instance_info = {'image_source': 'fake-value'}
        self.node.save()

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertTrue(self.interface.should_write_image(task))
