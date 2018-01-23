# coding=utf-8
#
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

import datetime

import mock
from testtools import matchers

from ironic.common import context
from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestNodeObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestNodeObject, self).setUp()
        self.ctxt = context.get_admin_context()
        self.fake_node = db_utils.get_test_node()
        self.node = obj_utils.get_test_node(self.ctxt, **self.fake_node)

    def test_as_dict_insecure(self):
        self.node.driver_info['ipmi_password'] = 'fake'
        self.node.instance_info['configdrive'] = 'data'
        d = self.node.as_dict()
        self.assertEqual('fake', d['driver_info']['ipmi_password'])
        self.assertEqual('data', d['instance_info']['configdrive'])

    def test_as_dict_secure(self):
        self.node.driver_info['ipmi_password'] = 'fake'
        self.node.instance_info['configdrive'] = 'data'
        d = self.node.as_dict(secure=True)
        self.assertEqual('******', d['driver_info']['ipmi_password'])
        self.assertEqual('******', d['instance_info']['configdrive'])

    def test_get_by_id(self):
        node_id = self.fake_node['id']
        with mock.patch.object(self.dbapi, 'get_node_by_id',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node

            node = objects.Node.get(self.context, node_id)

            mock_get_node.assert_called_once_with(node_id)
            self.assertEqual(self.context, node._context)

    def test_get_by_uuid(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node

            node = objects.Node.get(self.context, uuid)

            mock_get_node.assert_called_once_with(uuid)
            self.assertEqual(self.context, node._context)

    def test_get_bad_id_and_uuid(self):
        self.assertRaises(exception.InvalidIdentity,
                          objects.Node.get, self.context, 'not-a-uuid')

    def test_get_by_port_addresses(self):
        with mock.patch.object(self.dbapi, 'get_node_by_port_addresses',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node

            node = objects.Node.get_by_port_addresses(self.context,
                                                      ['aa:bb:cc:dd:ee:ff'])

            mock_get_node.assert_called_once_with(['aa:bb:cc:dd:ee:ff'])
            self.assertEqual(self.context, node._context)

    def test_save(self):
        uuid = self.fake_node['uuid']
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            with mock.patch.object(self.dbapi, 'update_node',
                                   autospec=True) as mock_update_node:
                mock_update_node.return_value = db_utils.get_test_node(
                    properties={"fake": "property"}, driver='fake-driver',
                    driver_internal_info={}, updated_at=test_time)
                n = objects.Node.get(self.context, uuid)
                self.assertEqual({"private_state": "secret value"},
                                 n.driver_internal_info)
                n.properties = {"fake": "property"}
                n.driver = "fake-driver"
                n.save()

                mock_get_node.assert_called_once_with(uuid)
                mock_update_node.assert_called_once_with(
                    uuid, {'properties': {"fake": "property"},
                           'driver': 'fake-driver',
                           'driver_internal_info': {},
                           'version': objects.Node.VERSION})
                self.assertEqual(self.context, n._context)
                res_updated_at = (n.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)
                self.assertEqual({}, n.driver_internal_info)

    def test_save_updated_at_field(self):
        uuid = self.fake_node['uuid']
        extra = {"test": 123}
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            with mock.patch.object(self.dbapi, 'update_node',
                                   autospec=True) as mock_update_node:
                mock_update_node.return_value = (
                    db_utils.get_test_node(extra=extra, updated_at=test_time))
                n = objects.Node.get(self.context, uuid)
                self.assertEqual({"private_state": "secret value"},
                                 n.driver_internal_info)
                n.properties = {"fake": "property"}
                n.extra = extra
                n.driver = "fake-driver"
                n.driver_internal_info = {}
                n.save()

                mock_get_node.assert_called_once_with(uuid)
                mock_update_node.assert_called_once_with(
                    uuid, {'properties': {"fake": "property"},
                           'driver': 'fake-driver',
                           'driver_internal_info': {},
                           'extra': {'test': 123},
                           'version': objects.Node.VERSION})
                self.assertEqual(self.context, n._context)
                res_updated_at = n.updated_at.replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    def test_refresh(self):
        uuid = self.fake_node['uuid']
        returns = [dict(self.fake_node, properties={"fake": "first"}),
                   dict(self.fake_node, properties={"fake": "second"})]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_node:
            n = objects.Node.get(self.context, uuid)
            self.assertEqual({"fake": "first"}, n.properties)
            n.refresh()
            self.assertEqual({"fake": "second"}, n.properties)
            self.assertEqual(expected, mock_get_node.call_args_list)
            self.assertEqual(self.context, n._context)

    def test_save_after_refresh(self):
        # Ensure that it's possible to do object.save() after object.refresh()
        db_node = db_utils.create_test_node()
        n = objects.Node.get_by_uuid(self.context, db_node.uuid)
        n_copy = objects.Node.get_by_uuid(self.context, db_node.uuid)
        n.name = 'b240'
        n.save()
        n_copy.refresh()
        n_copy.name = 'aaff'
        # Ensure this passes and an exception is not generated
        n_copy.save()

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_node_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_node]
            nodes = objects.Node.list(self.context)
            self.assertThat(nodes, matchers.HasLength(1))
            self.assertIsInstance(nodes[0], objects.Node)
            self.assertEqual(self.context, nodes[0]._context)

    def test_reserve(self):
        with mock.patch.object(self.dbapi, 'reserve_node',
                               autospec=True) as mock_reserve:
            mock_reserve.return_value = self.fake_node
            node_id = self.fake_node['id']
            fake_tag = 'fake-tag'
            node = objects.Node.reserve(self.context, fake_tag, node_id)
            self.assertIsInstance(node, objects.Node)
            mock_reserve.assert_called_once_with(fake_tag, node_id)
            self.assertEqual(self.context, node._context)

    def test_reserve_node_not_found(self):
        with mock.patch.object(self.dbapi, 'reserve_node',
                               autospec=True) as mock_reserve:
            node_id = 'non-existent'
            mock_reserve.side_effect = exception.NodeNotFound(node=node_id)
            self.assertRaises(exception.NodeNotFound,
                              objects.Node.reserve, self.context, 'fake-tag',
                              node_id)

    def test_release(self):
        with mock.patch.object(self.dbapi, 'release_node',
                               autospec=True) as mock_release:
            node_id = self.fake_node['id']
            fake_tag = 'fake-tag'
            objects.Node.release(self.context, fake_tag, node_id)
            mock_release.assert_called_once_with(fake_tag, node_id)

    def test_release_node_not_found(self):
        with mock.patch.object(self.dbapi, 'release_node',
                               autospec=True) as mock_release:
            node_id = 'non-existent'
            mock_release.side_effect = exception.NodeNotFound(node=node_id)
            self.assertRaises(exception.NodeNotFound,
                              objects.Node.release, self.context,
                              'fake-tag', node_id)

    def test_touch_provisioning(self):
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            with mock.patch.object(self.dbapi, 'touch_node_provisioning',
                                   autospec=True) as mock_touch:
                node = objects.Node.get(self.context, self.fake_node['uuid'])
                node.touch_provisioning()
                mock_touch.assert_called_once_with(node.id)

    def test_create(self):
        node = objects.Node(self.context, **self.fake_node)
        with mock.patch.object(self.dbapi, 'create_node',
                               autospec=True) as mock_create_node:
            mock_create_node.return_value = db_utils.get_test_node()

            node.create()

            args, _kwargs = mock_create_node.call_args
            self.assertEqual(objects.Node.VERSION, args[0]['version'])

    def test_create_with_invalid_properties(self):
        node = objects.Node(self.context, **self.fake_node)
        node.properties = {"local_gb": "5G"}
        self.assertRaises(exception.InvalidParameterValue, node.create)

    def test_update_with_invalid_properties(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            node = objects.Node.get(self.context, uuid)
            node.properties = {"local_gb": "5G", "memory_mb": "5",
                               'cpus': '-1', 'cpu_arch': 'x86_64'}
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   ".*local_gb=5G, cpus=-1$", node.save)
            mock_get_node.assert_called_once_with(uuid)

    def test__validate_property_values_success(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            node = objects.Node.get(self.context, uuid)
            values = self.fake_node
            expect = {
                'cpu_arch': 'x86_64',
                "cpus": '8',
                "local_gb": '10',
                "memory_mb": '4096',
            }
            node._validate_property_values(values['properties'])
            self.assertEqual(expect, values['properties'])

    def test_payload_schemas(self):
        self._check_payload_schemas(objects.node, objects.Node.fields)
