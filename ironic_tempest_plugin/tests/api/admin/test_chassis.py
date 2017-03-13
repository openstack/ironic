# -*- coding: utf-8 -*-
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

from tempest.lib.common.utils import data_utils
from tempest.lib import decorators
from tempest.lib import exceptions as lib_exc

from ironic_tempest_plugin.tests.api.admin import base


class TestChassis(base.BaseBaremetalTest):
    """Tests for chassis."""

    @classmethod
    def resource_setup(cls):
        super(TestChassis, cls).resource_setup()
        _, cls.chassis = cls.create_chassis()

    @decorators.idempotent_id('7c5a2e09-699c-44be-89ed-2bc189992d42')
    def test_create_chassis(self):
        descr = data_utils.rand_name('test-chassis')
        _, chassis = self.create_chassis(description=descr)
        self.assertEqual(descr, chassis['description'])

    @decorators.idempotent_id('cabe9c6f-dc16-41a7-b6b9-0a90c212edd5')
    def test_create_chassis_unicode_description(self):
        # Use a unicode string for testing:
        # 'We ♡ OpenStack in Ukraine'
        descr = u'В Україні ♡ OpenStack!'
        _, chassis = self.create_chassis(description=descr)
        self.assertEqual(descr, chassis['description'])

    @decorators.idempotent_id('c84644df-31c4-49db-a307-8942881f41c0')
    def test_show_chassis(self):
        _, chassis = self.client.show_chassis(self.chassis['uuid'])
        self._assertExpected(self.chassis, chassis)

    @decorators.idempotent_id('29c9cd3f-19b5-417b-9864-99512c3b33b3')
    def test_list_chassis(self):
        _, body = self.client.list_chassis()
        self.assertIn(self.chassis['uuid'],
                      [i['uuid'] for i in body['chassis']])

    @decorators.idempotent_id('5ae649ad-22d1-4fe1-bbc6-97227d199fb3')
    def test_delete_chassis(self):
        _, body = self.create_chassis()
        uuid = body['uuid']

        self.delete_chassis(uuid)
        self.assertRaises(lib_exc.NotFound, self.client.show_chassis, uuid)

    @decorators.idempotent_id('cda8a41f-6be2-4cbf-840c-994b00a89b44')
    def test_update_chassis(self):
        _, body = self.create_chassis()
        uuid = body['uuid']

        new_description = data_utils.rand_name('new-description')
        _, body = (self.client.update_chassis(uuid,
                   description=new_description))
        _, chassis = self.client.show_chassis(uuid)
        self.assertEqual(new_description, chassis['description'])

    @decorators.idempotent_id('76305e22-a4e2-4ab3-855c-f4e2368b9335')
    def test_chassis_node_list(self):
        _, node = self.create_node(self.chassis['uuid'])
        _, body = self.client.list_chassis_nodes(self.chassis['uuid'])
        self.assertIn(node['uuid'], [n['uuid'] for n in body['nodes']])

    @decorators.idempotent_id('dd52bd5d-610c-4f2c-8fa3-d5e59269325f')
    def test_create_chassis_uuid(self):
        uuid = data_utils.rand_uuid()
        _, chassis = self.create_chassis(uuid=uuid)
        self.assertEqual(uuid, chassis['uuid'])
