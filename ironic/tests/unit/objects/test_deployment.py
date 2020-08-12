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

from oslo_utils import uuidutils

from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class TestDeploymentObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestDeploymentObject, self).setUp()
        self.uuid = uuidutils.generate_uuid()
        self.instance_info = {
            'image_source': 'http://source',
            'kernel': 'http://kernel',
            'ramdisk': 'http://ramdisk',
            'image_checksum': '1234',
            'root_device': {'size': 42},
        }
        self.node = obj_utils.create_test_node(
            self.context,
            provision_state='active',
            instance_uuid=self.uuid,
            instance_info=self.instance_info)

    def _check(self, do):
        self.assertEqual(self.uuid, do.uuid)
        self.assertEqual(self.node.uuid, do.node_uuid)
        self.assertEqual(self.context, do._context)
        self.assertEqual('http://source', do.image_ref)
        self.assertEqual('http://kernel', do.kernel_ref)
        self.assertEqual('http://ramdisk', do.ramdisk_ref)
        self.assertEqual('1234', do.image_checksum)
        self.assertEqual({'size': 42}, do.root_device)

    def test_get_by_uuid(self):
        do = objects.Deployment.get_by_uuid(self.context, self.uuid)
        self._check(do)

    def test_get_by_node_uuid(self):
        do = objects.Deployment.get_by_node_uuid(self.context, self.node.uuid)
        self._check(do)

    def test_not_found(self):
        self.assertRaises(exception.InstanceNotFound,
                          objects.Deployment.get_by_uuid,
                          self.context, uuidutils.generate_uuid())
        self.assertRaises(exception.NodeNotFound,
                          objects.Deployment.get_by_node_uuid,
                          self.context, uuidutils.generate_uuid())

    def test_create(self):
        do = objects.Deployment(self.context)
        do.node_uuid = self.node.uuid
        do.image_ref = 'new-image'
        do.create()
        self.assertIsNotNone(do.uuid)

        node = objects.Node.get_by_uuid(self.context, do.node_uuid)
        self.assertEqual(do.uuid, node.instance_uuid)
        self.assertEqual('new-image', node.instance_info['image_source'])
        self.assertFalse(do.obj_what_changed())

    def test_create_with_node(self):
        do = objects.Deployment(self.context)
        do.node_uuid = self.node.uuid
        do.image_ref = 'new-image'
        do.create(node=self.node)
        self.assertIsNotNone(do.uuid)
        self.assertEqual(do.uuid, self.node.instance_uuid)
        self.assertEqual('new-image', self.node.instance_info['image_source'])
        self.assertFalse(do.obj_what_changed())
        self.assertFalse(self.node.obj_what_changed())

    def test_destroy(self):
        do = objects.Deployment(self.context)
        do.node_uuid = self.node.uuid
        do.image_ref = 'new-image'
        do.create()
        do.destroy()

        node = objects.Node.get_by_uuid(self.context, do.node_uuid)
        self.assertIsNone(node.instance_uuid)
        self.assertEqual({}, node.instance_info)
        self.assertFalse(do.obj_what_changed())

    def test_destroy_with_node(self):
        do = objects.Deployment(self.context)
        do.node_uuid = self.node.uuid
        do.image_ref = 'new-image'
        do.create()
        do.destroy(node=self.node)
        self.assertIsNone(self.node.instance_uuid)
        self.assertEqual({}, self.node.instance_info)
        self.assertFalse(do.obj_what_changed())
        self.assertFalse(self.node.obj_what_changed())

    def test_refresh(self):
        do = objects.Deployment.get_by_uuid(self.context, self.uuid)
        do.node_uuid = None
        do.image_source = 'updated'
        do.refresh()
        self._check(do)
        self.assertFalse(do.obj_what_changed())
