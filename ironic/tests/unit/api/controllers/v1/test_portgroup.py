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
"""
Tests for the API /portgroups/ methods.
"""

import datetime
from http import client as http_client
from unittest import mock
from urllib import parse as urlparse

from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils
from testtools.matchers import HasLength

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import notification_utils
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import exception
from ironic.common import states
from ironic.conductor import rpcapi
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.objects import utils as obj_utils


def _rpcapi_update_portgroup(self, context, portgroup, topic):
    """Fake used to mock out the conductor RPCAPI's update_portgroup method.

    Saves the updated portgroup object and returns the updated portgroup
    as-per the real method.
    """
    portgroup.save()
    return portgroup


class TestListPortgroups(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestListPortgroups, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_empty(self):
        data = self.get_json('/portgroups', headers=self.headers)
        self.assertEqual([], data['portgroups'])

    def test_one(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups', headers=self.headers)
        self.assertEqual(portgroup.uuid, data['portgroups'][0]["uuid"])
        self.assertEqual(portgroup.address, data['portgroups'][0]["address"])
        self.assertEqual(portgroup.name, data['portgroups'][0]['name'])
        self.assertNotIn('extra', data['portgroups'][0])
        self.assertNotIn('node_uuid', data['portgroups'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['portgroups'][0])
        self.assertNotIn('standalone_ports_supported', data['portgroups'][0])

    def test_get_one(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups/%s' % portgroup.uuid,
                             headers=self.headers)
        self.assertEqual(portgroup.uuid, data['uuid'])
        self.assertIn('extra', data)
        self.assertIn('node_uuid', data)
        self.assertIn('standalone_ports_supported', data)
        # never expose the node_id
        self.assertNotIn('node_id', data)

    def test_get_one_with_json(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups/%s.json' % portgroup.uuid,
                             headers=self.headers)
        self.assertEqual(portgroup.uuid, data['uuid'])

    def test_get_one_with_json_in_name(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    name='pg.json',
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups/%s' % portgroup.uuid,
                             headers=self.headers)
        self.assertEqual(portgroup.uuid, data['uuid'])

    def test_get_one_with_suffix(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    name='pg.1',
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups/%s' % portgroup.uuid,
                             headers=self.headers)
        self.assertEqual(portgroup.uuid, data['uuid'])

    def test_get_one_custom_fields(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        fields = 'address,extra'
        data = self.get_json(
            '/portgroups/%s?fields=%s' % (portgroup.uuid, fields),
            headers=self.headers)
        # We always append "links"
        self.assertCountEqual(['address', 'extra', 'links'], data)

    def test_get_one_mode_field_lower_api_version(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        headers = {api_base.Version.string: '1.25'}
        fields = 'address,mode'
        response = self.get_json(
            '/portgroups/%s?fields=%s' % (portgroup.uuid, fields),
            headers=headers, expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertEqual('application/json', response.content_type)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % i,
                address='52:54:00:cf:2d:3%s' % i)

        data = self.get_json(
            '/portgroups?fields=%s' % fields,
            headers=self.headers)

        self.assertEqual(3, len(data['portgroups']))
        for portgroup in data['portgroups']:
            # We always append "links"
            self.assertCountEqual(['uuid', 'extra', 'links'], portgroup)

    def test_get_collection_properties_field_lower_api_version(self):
        obj_utils.create_test_portgroup(self.context, node_id=self.node.id)
        headers = {api_base.Version.string: '1.25'}
        fields = 'address,properties'
        response = self.get_json(
            '/portgroups/?fields=%s' % fields,
            headers=headers, expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertEqual('application/json', response.content_type)

    def test_get_custom_fields_invalid_fields(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/portgroups/%s?fields=%s' % (portgroup.uuid, fields),
            headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_one_invalid_api_version(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        response = self.get_json(
            '/portgroups/%s' % (portgroup.uuid),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_detail(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups/detail', headers=self.headers)
        self.assertEqual(portgroup.uuid, data['portgroups'][0]["uuid"])
        self.assertIn('extra', data['portgroups'][0])
        self.assertIn('node_uuid', data['portgroups'][0])
        self.assertIn('standalone_ports_supported', data['portgroups'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['portgroups'][0])

    def test_detail_query(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups?detail=True', headers=self.headers)
        self.assertEqual(portgroup.uuid, data['portgroups'][0]["uuid"])
        self.assertIn('extra', data['portgroups'][0])
        self.assertIn('node_uuid', data['portgroups'][0])
        self.assertIn('standalone_ports_supported', data['portgroups'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['portgroups'][0])

    def test_detail_query_false(self):
        obj_utils.create_test_portgroup(self.context,
                                        node_id=self.node.id)
        data1 = self.get_json(
            '/portgroups',
            headers={api_base.Version.string: str(api_v1.max_version())})
        data2 = self.get_json(
            '/portgroups?detail=False',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(data1['portgroups'], data2['portgroups'])

    def test_detail_using_query_false_and_fields(self):
        obj_utils.create_test_portgroup(self.context,
                                        node_id=self.node.id)
        data = self.get_json(
            '/portgroups?detail=False&fields=internal_info',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertIn('internal_info', data['portgroups'][0])
        self.assertNotIn('uuid', data['portgroups'][0])

    def test_detail_using_query_and_fields(self):
        obj_utils.create_test_portgroup(self.context,
                                        node_id=self.node.id)
        response = self.get_json(
            '/portgroups?detail=True&fields=name',
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_using_query_old_version(self):
        obj_utils.create_test_portgroup(self.context,
                                        node_id=self.node.id)
        response = self.get_json(
            '/portgroups?detail=True',
            headers={api_base.Version.string: '1.42'},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_invalid_api_version(self):
        response = self.get_json(
            '/portgroups/detail',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_detail_against_single(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        response = self.get_json('/portgroups/%s/detail' % portgroup.uuid,
                                 expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_many(self):
        portgroups = []
        for id_ in range(5):
            portgroup = obj_utils.create_test_portgroup(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address='52:54:00:cf:2d:3%s' % id_)
            portgroups.append(portgroup.uuid)
        data = self.get_json('/portgroups', headers=self.headers)
        self.assertEqual(len(portgroups), len(data['portgroups']))

        uuids = [n['uuid'] for n in data['portgroups']]
        self.assertCountEqual(portgroups, uuids)

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_portgroup(self.context,
                                        uuid=uuid,
                                        node_id=self.node.id)
        data = self.get_json('/portgroups/%s' % uuid, headers=self.headers)
        self.assertIn('links', data)
        self.assertIn('ports', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for link in data['links']:
            bookmark = link['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(link['href'], bookmark=bookmark,
                            headers=self.headers))

    def test_collection_links(self):
        portgroups = []
        for id_ in range(5):
            portgroup = obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address='52:54:00:cf:2d:3%s' % id_)
            portgroups.append(portgroup.uuid)
        data = self.get_json('/portgroups/?limit=3', headers=self.headers)
        self.assertEqual(3, len(data['portgroups']))

        next_marker = data['portgroups'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        portgroups = []
        for id_ in range(5):
            portgroup = obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address='52:54:00:cf:2d:3%s' % id_)
            portgroups.append(portgroup.uuid)
        data = self.get_json('/portgroups', headers=self.headers)
        self.assertEqual(3, len(data['portgroups']))

        next_marker = data['portgroups'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_custom_fields(self):
        fields = 'address,uuid'
        cfg.CONF.set_override('max_limit', 3, 'api')
        for i in range(5):
            obj_utils.create_test_portgroup(
                self.context,
                uuid=uuidutils.generate_uuid(),
                node_id=self.node.id,
                name='portgroup%s' % i,
                address='52:54:00:cf:2d:3%s' % i)

        data = self.get_json(
            '/portgroups?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(3, len(data['portgroups']))
        next_marker = data['portgroups'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('fields', data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'address'
        limit = 2
        portgroups = []
        for id_ in range(3):
            portgroup = obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address='52:54:00:cf:2d:3%s' % id_)
            portgroups.append(portgroup)

        data = self.get_json(
            '/portgroups?fields=%s&limit=%s' % (fields, limit),
            headers=self.headers)

        self.assertEqual(limit, len(data['portgroups']))
        self.assertIn('marker=%s' % portgroups[limit - 1].uuid, data['next'])

    def test_ports_subresource(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             uuid=uuidutils.generate_uuid(),
                                             node_id=self.node.id)

        for id_ in range(2):
            obj_utils.create_test_port(self.context, node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       portgroup_id=pg.id,
                                       address='52:54:00:cf:2d:3%s' % id_)

        data = self.get_json('/portgroups/%s/ports' % pg.uuid,
                             headers=self.headers)
        self.assertEqual(2, len(data['ports']))
        self.assertNotIn('next', data)

        data = self.get_json('/portgroups/%s/ports/detail' % pg.uuid,
                             headers=self.headers)
        self.assertEqual(2, len(data['ports']))
        self.assertNotIn('next', data)

        # Test collection pagination
        data = self.get_json('/portgroups/%s/ports?limit=1' % pg.uuid,
                             headers=self.headers)
        self.assertEqual(1, len(data['ports']))
        self.assertIn('next', data)

        # Test get one old api version, /portgroups controller not allowed
        response = self.get_json('/portgroups/%s/ports/%s' % (
            pg.uuid, uuidutils.generate_uuid()),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

        # Test get one not allowed to access to /portgroups/<uuid>/ports/<uuid>
        response = self.get_json(
            '/portgroups/%s/ports/%s' % (pg.uuid, uuidutils.generate_uuid()),
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_ports_subresource_no_portgroups_allowed(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             uuid=uuidutils.generate_uuid(),
                                             node_id=self.node.id)

        for id_ in range(2):
            obj_utils.create_test_port(self.context, node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       portgroup_id=pg.id,
                                       address='52:54:00:cf:2d:3%s' % id_)

        response = self.get_json('/portgroups/%s/ports' % pg.uuid,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertEqual('application/json', response.content_type)

    def test_get_all_ports_by_portgroup_uuid(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=pg.id)
        data = self.get_json('/portgroups/%s/ports' % pg.uuid,
                             headers={api_base.Version.string: '1.24'})
        self.assertEqual(port.uuid, data['ports'][0]['uuid'])

    def test_ports_subresource_not_allowed(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        response = self.get_json('/portgroups/%s/ports' % pg.uuid,
                                 expect_errors=True,
                                 headers={api_base.Version.string: '1.23'})
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertIn('Not Found', response.json['error_message'])

    def test_ports_subresource_portgroup_not_found(self):
        non_existent_uuid = 'eeeeeeee-cccc-aaaa-bbbb-cccccccccccc'
        response = self.get_json('/portgroups/%s/ports' % non_existent_uuid,
                                 expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertIn('Portgroup %s could not be found.' % non_existent_uuid,
                      response.json['error_message'])

    def test_portgroup_by_address(self):
        address_template = "aa:bb:cc:dd:ee:f%d"
        for id_ in range(3):
            obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address=address_template % id_)

        target_address = address_template % 1
        data = self.get_json('/portgroups?address=%s' % target_address,
                             headers=self.headers)
        self.assertThat(data['portgroups'], HasLength(1))
        self.assertEqual(target_address, data['portgroups'][0]['address'])

    def test_portgroup_get_all_invalid_api_version(self):
        obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            name='portgroup_1')
        response = self.get_json('/portgroups',
                                 headers={api_base.Version.string: '1.14'},
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_portgroup_by_address_non_existent_address(self):
        # non-existent address
        data = self.get_json('/portgroups?address=%s' % 'aa:bb:cc:dd:ee:ff',
                             headers=self.headers)
        self.assertThat(data['portgroups'], HasLength(0))

    def test_portgroup_by_address_invalid_address_format(self):
        obj_utils.create_test_portgroup(self.context, node_id=self.node.id)
        invalid_address = 'invalid-mac-format'
        response = self.get_json('/portgroups?address=%s' % invalid_address,
                                 expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(invalid_address, response.json['error_message'])

    def test_sort_key(self):
        portgroups = []
        for id_ in range(3):
            portgroup = obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address='52:54:00:cf:2d:3%s' % id_)
            portgroups.append(portgroup.uuid)
        data = self.get_json('/portgroups?sort_key=uuid', headers=self.headers)
        uuids = [n['uuid'] for n in data['portgroups']]
        self.assertEqual(sorted(portgroups), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra', 'internal_info', 'properties']
        for invalid_key in invalid_keys_list:
            response = self.get_json('/portgroups?sort_key=%s' % invalid_key,
                                     expect_errors=True, headers=self.headers)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    def _test_sort_key_allowed(self, detail=False):
        portgroup_uuids = []
        for id_ in range(3, 0, -1):
            portgroup = obj_utils.create_test_portgroup(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % id_,
                address='52:54:00:cf:2d:3%s' % id_,
                mode='mode_%s' % id_)
            portgroup_uuids.append(portgroup.uuid)
        portgroup_uuids.reverse()
        detail_str = '/detail' if detail else ''
        data = self.get_json('/portgroups%s?sort_key=mode' % detail_str,
                             headers=self.headers)
        data_uuids = [p['uuid'] for p in data['portgroups']]
        self.assertEqual(portgroup_uuids, data_uuids)

    def test_sort_key_allowed(self):
        self._test_sort_key_allowed()

    def test_detail_sort_key_allowed(self):
        self._test_sort_key_allowed(detail=True)

    def _test_sort_key_not_allowed(self, detail=False):
        headers = {api_base.Version.string: '1.25'}
        detail_str = '/detail' if detail else ''
        response = self.get_json('/portgroups%s?sort_key=mode' % detail_str,
                                 headers=headers, expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertEqual('application/json', response.content_type)

    def test_sort_key_not_allowed(self):
        self._test_sort_key_not_allowed()

    def test_detail_sort_key_not_allowed(self):
        self._test_sort_key_not_allowed(detail=True)

    @mock.patch.object(api_utils, 'get_rpc_node', autospec=True)
    def test_get_all_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/portgroups specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_portgroup(
                self.context,
                node_id=node_id,
                uuid=uuidutils.generate_uuid(),
                name='portgroup%s' % i,
                address='52:54:00:cf:2d:3%s' % i)
        data = self.get_json("/portgroups?node=%s" % 'test-node',
                             headers=self.headers)
        self.assertEqual(3, len(data['portgroups']))

    @mock.patch.object(api_utils, 'get_rpc_node', autospec=True)
    def test_get_all_by_node_uuid_ok(self, mock_get_rpc_node):
        mock_get_rpc_node.return_value = self.node
        obj_utils.create_test_portgroup(self.context, node_id=self.node.id)
        data = self.get_json('/portgroups/detail?node=%s' % (self.node.uuid),
                             headers=self.headers)
        mock_get_rpc_node.assert_called_once_with(self.node.uuid)
        self.assertEqual(1, len(data['portgroups']))

    @mock.patch.object(api_utils, 'get_rpc_node', autospec=True)
    def test_detail_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/portgroups/detail specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        data = self.get_json('/portgroups/detail?node=%s' % 'test-node',
                             headers=self.headers)
        self.assertEqual(portgroup.uuid, data['portgroups'][0]['uuid'])
        self.assertEqual(self.node.uuid, data['portgroups'][0]['node_uuid'])


@mock.patch.object(rpcapi.ConductorAPI, 'update_portgroup', autospec=True)
class TestPatch(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPatch, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.portgroup = obj_utils.create_test_portgroup(self.context,
                                                         name='pg.1',
                                                         node_id=self.node.id)

        p = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for',
                              autospec=True)
        self.mock_gtf = p.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(p.stop)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_update_byid(self, mock_notify, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    def test_update_byname(self, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.name,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])

    def test_update_byname_with_json(self, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s.json' % self.portgroup.name,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])

    def test_update_invalid_name(self, mock_upd):
        mock_upd.return_value = self.portgroup
        response = self.patch_json('/portgroups/%s' % self.portgroup.name,
                                   [{'path': '/name',
                                     'value': 'aa:bb_cc',
                                     'op': 'replace'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)

    def test_update_byid_invalid_api_version(self, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        headers = {api_base.Version.string: '1.14'}
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=headers,
                                   expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_update_byaddress_not_allowed(self, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.address,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn(self.portgroup.address, response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_not_found(self, mock_upd):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/portgroups/%s' % uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_singular(self, mock_upd):
        address = 'aa:bb:cc:dd:ee:ff'
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.address = address
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(address, response.json['address'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address, kargs.address)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_replace_address_already_exist(self, mock_notify, mock_upd):
        address = 'aa:aa:aa:aa:aa:aa'
        mock_upd.side_effect = exception.MACAlreadyExists(mac=address)
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address, kargs.address)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_replace_node_uuid(self, mock_upd):
        mock_upd.return_value = self.portgroup
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_add_node_uuid(self, mock_upd):
        mock_upd.return_value = self.portgroup
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_add_node_id(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_node_id(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_remove_node_id(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/node_id',
                                     'op': 'remove'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_non_existent_node_uuid(self, mock_upd):
        node_uuid = '12506333-a81c-4d59-9987-889ed5f8687b'
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/node_uuid',
                                     'value': node_uuid,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertIn(node_uuid, response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.portgroup.extra = extra
        self.portgroup.save()

        # mutate extra so we replace all of them
        extra = dict((k, extra[k] + 'x') for k in extra)

        patch = []
        for k in extra:
            patch.append({'path': '/extra/%s' % k,
                          'value': extra[k],
                          'op': 'replace'})
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

    def test_remove_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.portgroup.extra = extra
        self.portgroup.save()

        # Removing one item from the collection
        extra.pop('foo1')
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/extra/foo1',
                                     'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

        # Removing the collection
        extra = {}
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/extra', 'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual({}, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

        # Assert nothing else was changed
        self.assertEqual(self.portgroup.uuid, response.json['uuid'])
        self.assertEqual(self.portgroup.address, response.json['address'])

    def test_remove_non_existent_property_fail(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/extra/non-existent',
                                     'op': 'remove'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_remove_address(self, mock_upd):
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.address = None
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertIsNone(response.json['address'])
        self.assertTrue(mock_upd.called)

    def test_add_root(self, mock_upd):
        address = 'aa:bb:cc:dd:ee:ff'
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.address = address
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(address, response.json['address'])
        self.assertTrue(mock_upd.called)
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address, kargs.address)

    def test_add_root_non_existent(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_add_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        patch = []
        for k in extra:
            patch.append({'path': '/extra/%s' % k,
                          'value': extra[k],
                          'op': 'add'})
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.extra = extra
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

    def test_remove_uuid(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/uuid',
                                     'op': 'remove'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_address_invalid_format(self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': 'invalid-format',
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_portgroup_address_normalized(self, mock_upd):
        address = 'AA:BB:CC:DD:EE:FF'
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.address = address.lower()
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(address.lower(), response.json['address'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address.lower(), kargs.address)

    def test_update_portgroup_standalone_ports_supported(self, mock_upd):
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.standalone_ports_supported = False
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/standalone_ports_supported',
                                     'value': False,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertIs(False, response.json['standalone_ports_supported'])

    def test_update_portgroup_standalone_ports_supported_bad_api_version(
            self, mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/standalone_ports_supported',
                                     'value': False,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers={api_base.Version.string:
                                            str(api_v1.min_version())})
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_portgroup_internal_info_not_allowed(self, mock_upd):
        mock_upd.return_value = self.portgroup
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/internal_info',
                                     'value': False,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_portgroup_mode_properties(self, mock_upd):
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.mode = '802.3ad'
        mock_upd.return_value.properties = {'bond_param': '100'}
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/mode',
                                     'value': '802.3ad',
                                     'op': 'add'},
                                    {'path': '/properties/bond_param',
                                     'value': '100',
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual('802.3ad', response.json['mode'])
        self.assertEqual({'bond_param': '100'}, response.json['properties'])

    def _test_update_portgroup_mode_properties_bad_api_version(self, patch,
                                                               mock_upd):
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   patch, expect_errors=True,
                                   headers={api_base.Version.string: '1.25'})
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_portgroup_mode_properties_bad_api_version(self, mock_upd):
        self._test_update_portgroup_mode_properties_bad_api_version(
            [{'path': '/mode', 'op': 'add', 'value': '802.3ad'}], mock_upd)
        self._test_update_portgroup_mode_properties_bad_api_version(
            [{'path': '/properties/abc', 'op': 'add', 'value': 123}], mock_upd)

    def test_remove_mode_not_allowed(self, mock_upd):
        mock_upd.return_value = self.portgroup
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/mode',
                                     'op': 'remove'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_in_inspecting_not_allowed(self, mock_upd):
        self.node.provision_state = states.INSPECTING
        self.node.save()
        address = 'AA:BB:CC:DD:EE:FF'
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers={api_base.Version.string: "1.39"})
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_update_in_inspecting_allowed(self, mock_upd):
        self.node.provision_state = states.INSPECTING
        self.node.save()
        address = 'AA:BB:CC:DD:EE:FF'
        mock_upd.return_value = self.portgroup
        mock_upd.return_value.address = address.lower()
        response = self.patch_json('/portgroups/%s' % self.portgroup.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers={api_base.Version.string: "1.38"})
        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(address.lower(), response.json['address'])
        self.assertTrue(mock_upd.called)
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address.lower(), kargs.address)


class TestPost(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPost, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_create_portgroup(self, mock_utcnow, mock_notify):
        pdict = apiutils.post_get_test_portgroup()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/portgroups', pdict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/portgroups/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/portgroups/%s' % pdict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_create_portgroup_v123(self, mock_utcnow):
        pdict = apiutils.post_get_test_portgroup()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        headers = {api_base.Version.string: "1.23"}
        response = self.post_json('/portgroups', pdict,
                                  headers=headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/portgroups/%s' % pdict['uuid'],
                               headers=headers)
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertEqual(pdict['node_uuid'], result['node_uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/portgroups/%s' % pdict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)

    def test_create_portgroup_invalid_api_version(self):
        pdict = apiutils.post_get_test_portgroup()
        response = self.post_json(
            '/portgroups', pdict, headers={api_base.Version.string: '1.14'},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_create_portgroup_doesnt_contain_id(self):
        with mock.patch.object(self.dbapi, 'create_portgroup',
                               wraps=self.dbapi.create_portgroup) as cp_mock:
            pdict = apiutils.post_get_test_portgroup(extra={'foo': 123})
            self.post_json('/portgroups', pdict, headers=self.headers)
            result = self.get_json('/portgroups/%s' % pdict['uuid'],
                                   headers=self.headers)
            self.assertEqual(pdict['extra'], result['extra'])
            cp_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args
            self.assertNotIn('id', cp_mock.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_portgroup_generate_uuid(self, mock_warn, mock_except):
        pdict = apiutils.post_get_test_portgroup()
        del pdict['uuid']
        response = self.post_json('/portgroups', pdict, headers=self.headers)
        result = self.get_json('/portgroups/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['address'], result['address'])
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warn.called)
        self.assertFalse(mock_except.called)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(objects.Portgroup, 'create', autospec=True)
    def test_create_portgroup_error(self, mock_create, mock_notify):
        mock_create.side_effect = Exception()
        pdict = apiutils.post_get_test_portgroup()
        self.post_json('/portgroups', pdict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_create_portgroup_valid_extra(self):
        pdict = apiutils.post_get_test_portgroup(
            extra={'str': 'foo', 'int': 123, 'float': 0.1, 'bool': True,
                   'list': [1, 2], 'none': None, 'dict': {'cat': 'meow'}})
        self.post_json('/portgroups', pdict, headers=self.headers)
        result = self.get_json('/portgroups/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['extra'], result['extra'])

    def test_create_portgroup_no_address(self):
        pdict = apiutils.post_get_test_portgroup()
        del pdict['address']
        self.post_json('/portgroups', pdict, headers=self.headers)
        result = self.get_json('/portgroups/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertIsNone(result['address'])

    def test_create_portgroup_no_mandatory_field_node_uuid(self):
        pdict = apiutils.post_get_test_portgroup()
        del pdict['node_uuid']
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_portgroup_invalid_addr_format(self):
        pdict = apiutils.post_get_test_portgroup(address='invalid-format')
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_portgroup_address_normalized(self):
        address = 'AA:BB:CC:DD:EE:FF'
        pdict = apiutils.post_get_test_portgroup(address=address)
        self.post_json('/portgroups', pdict, headers=self.headers)
        result = self.get_json('/portgroups/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(address.lower(), result['address'])

    def test_create_portgroup_with_hyphens_delimiter(self):
        pdict = apiutils.post_get_test_portgroup()
        colonsMAC = pdict['address']
        hyphensMAC = colonsMAC.replace(':', '-')
        pdict['address'] = hyphensMAC
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_portgroup_invalid_node_uuid_format(self):
        pdict = apiutils.post_get_test_portgroup(node_uuid='invalid-format')
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_node_uuid_to_node_id_mapping(self):
        pdict = apiutils.post_get_test_portgroup(node_uuid=self.node['uuid'])
        self.post_json('/portgroups', pdict, headers=self.headers)
        # GET doesn't return the node_id it's an internal value
        portgroup = self.dbapi.get_portgroup_by_uuid(pdict['uuid'])
        self.assertEqual(self.node['id'], portgroup.node_id)

    def test_create_portgroup_node_uuid_not_found(self):
        pdict = apiutils.post_get_test_portgroup(
            node_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_portgroup_address_already_exist(self):
        address = 'AA:AA:AA:11:22:33'
        pdict = apiutils.post_get_test_portgroup(address=address)
        self.post_json('/portgroups', pdict, headers=self.headers)
        pdict['uuid'] = uuidutils.generate_uuid()
        pdict['name'] = uuidutils.generate_uuid()
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.CONFLICT, response.status_int)
        self.assertEqual('application/json', response.content_type)
        error_msg = response.json['error_message']
        self.assertTrue(error_msg)
        self.assertIn(address, error_msg.upper())

    def test_create_portgroup_name_ok(self):
        address = 'AA:AA:AA:11:22:33'
        name = 'foo'
        pdict = apiutils.post_get_test_portgroup(address=address, name=name)
        self.post_json('/portgroups', pdict, headers=self.headers)
        result = self.get_json('/portgroups/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(name, result['name'])

    def test_create_portgroup_name_invalid(self):
        address = 'AA:AA:AA:11:22:33'
        name = 'aa:bb_cc'
        pdict = apiutils.post_get_test_portgroup(address=address, name=name)
        response = self.post_json('/portgroups', pdict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_create_portgroup_internal_info_not_allowed(self):
        pdict = apiutils.post_get_test_portgroup()
        pdict['internal_info'] = 'info'
        response = self.post_json('/portgroups', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_portgroup_mode_old_api_version(self):
        for kwarg in [{'mode': '802.3ad'}, {'properties': {'bond_prop': 123}}]:
            pdict = apiutils.post_get_test_portgroup(**kwarg)
            response = self.post_json(
                '/portgroups', pdict, expect_errors=True,
                headers={api_base.Version.string: '1.25'})
            self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertTrue(response.json['error_message'])

    def test_create_portgroup_mode_properties(self):
        mode = '802.3ad'
        props = {'bond_prop': 123}
        pdict = apiutils.post_get_test_portgroup(mode=mode, properties=props)
        self.post_json('/portgroups', pdict,
                       headers={api_base.Version.string: '1.26'})
        portgroup = self.dbapi.get_portgroup_by_uuid(pdict['uuid'])
        self.assertEqual((mode, props), (portgroup.mode, portgroup.properties))

    def test_create_portgroup_default_mode(self):
        pdict = apiutils.post_get_test_portgroup()
        self.post_json('/portgroups', pdict,
                       headers={api_base.Version.string: '1.26'})
        portgroup = self.dbapi.get_portgroup_by_uuid(pdict['uuid'])
        self.assertEqual('active-backup', portgroup.mode)


@mock.patch.object(rpcapi.ConductorAPI, 'destroy_portgroup', autospec=True)
class TestDelete(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestDelete, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.portgroup = obj_utils.create_test_portgroup(self.context,
                                                         name='pg.1',
                                                         node_id=self.node.id)

        gtf = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for',
                                autospec=True)
        self.mock_gtf = gtf.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(gtf.stop)

    def test_delete_portgroup_byaddress(self, mock_dpt):
        response = self.delete('/portgroups/%s' % self.portgroup.address,
                               expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(self.portgroup.address, response.json['error_message'])

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_delete_portgroup_byid(self, mock_notify, mock_dpt):
        self.delete('/portgroups/%s' % self.portgroup.uuid,
                    headers=self.headers)
        self.assertTrue(mock_dpt.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_delete_portgroup_node_locked(self, mock_notify, mock_dpt):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_dpt.side_effect = exception.NodeLocked(node='fake-node',
                                                    host='fake-host')
        ret = self.delete('/portgroups/%s' % self.portgroup.uuid,
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.CONFLICT, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_dpt.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_delete_portgroup_invalid_api_version(self, mock_dpt):
        response = self.delete('/portgroups/%s' % self.portgroup.uuid,
                               expect_errors=True,
                               headers={api_base.Version.string: '1.14'})
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_delete_portgroup_byname(self, mock_dpt):
        self.delete('/portgroups/%s' % self.portgroup.name,
                    headers=self.headers)
        self.assertTrue(mock_dpt.called)

    def test_delete_portgroup_byname_with_json(self, mock_dpt):
        self.delete('/portgroups/%s.json' % self.portgroup.name,
                    headers=self.headers)
        self.assertTrue(mock_dpt.called)

    def test_delete_portgroup_byname_not_existed(self, mock_dpt):
        res = self.delete('/portgroups/%s' % 'blah', expect_errors=True,
                          headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)
