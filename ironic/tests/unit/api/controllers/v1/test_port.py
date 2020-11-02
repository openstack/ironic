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
Tests for the API /ports/ methods.
"""

import datetime
from http import client as http_client
import types
from unittest import mock
from urllib import parse as urlparse

from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils
from testtools import matchers

from ironic import api
from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import notification_utils
from ironic.api.controllers.v1 import port as api_port
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common import policy
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import rpcapi
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


# NOTE(lucasagomes): When creating a port via API (POST)
#                    we have to use node_uuid and portgroup_uuid
def post_get_test_port(**kw):
    port = apiutils.port_post_data(**kw)
    node = db_utils.get_test_node()
    portgroup = db_utils.get_test_portgroup()
    port['node_uuid'] = kw.get('node_uuid', node['uuid'])
    port['portgroup_uuid'] = kw.get('portgroup_uuid', portgroup['uuid'])
    return port


def _rpcapi_create_port(self, context, port, topic):
    """Fake used to mock out the conductor RPCAPI's create_port method.

    Performs creation of the port object and returns the created port as-per
    the real method.
    """
    port.create()
    return port


def _rpcapi_update_port(self, context, port, topic):
    """Fake used to mock out the conductor RPCAPI's update_port method.

    Saves the updated port object and returns the updated port as-per the real
    method.
    """
    port.save()
    return port


class TestPortObject(base.TestCase):

    @mock.patch("ironic.api.request")
    def test_port_init(self, mock_pecan_req):
        mock_pecan_req.version.minor = 1
        port_dict = apiutils.port_post_data(node_id=None,
                                            portgroup_uuid=None)
        del port_dict['extra']
        port = api_port.Port(**port_dict)
        self.assertEqual(atypes.Unset, port.extra)


@mock.patch.object(api_utils, 'allow_port_physical_network', autospec=True)
@mock.patch.object(api_utils, 'allow_portgroups_subcontrollers', autospec=True)
@mock.patch.object(api_utils, 'allow_port_advanced_net_fields', autospec=True)
class TestPortsController__CheckAllowedPortFields(base.TestCase):

    def setUp(self):
        super(TestPortsController__CheckAllowedPortFields, self).setUp()
        self.controller = api_port.PortsController()

    def test__check_allowed_port_fields_none(self, mock_allow_port,
                                             mock_allow_portgroup,
                                             mock_allow_physnet):
        self.assertIsNone(
            self.controller._check_allowed_port_fields(None))
        self.assertFalse(mock_allow_port.called)
        self.assertFalse(mock_allow_portgroup.called)
        self.assertFalse(mock_allow_physnet.called)

    def test__check_allowed_port_fields_empty(self, mock_allow_port,
                                              mock_allow_portgroup,
                                              mock_allow_physnet):
        for v in (True, False):
            mock_allow_port.return_value = v
            self.assertIsNone(
                self.controller._check_allowed_port_fields([]))
            mock_allow_port.assert_called_once_with()
            mock_allow_port.reset_mock()
            self.assertFalse(mock_allow_portgroup.called)
            self.assertFalse(mock_allow_physnet.called)

    def test__check_allowed_port_fields_not_allow(self, mock_allow_port,
                                                  mock_allow_portgroup,
                                                  mock_allow_physnet):
        mock_allow_port.return_value = False
        for field in api_port.PortsController.advanced_net_fields:
            self.assertRaises(exception.NotAcceptable,
                              self.controller._check_allowed_port_fields,
                              [field])
            mock_allow_port.assert_called_once_with()
            mock_allow_port.reset_mock()
            self.assertFalse(mock_allow_portgroup.called)
            self.assertFalse(mock_allow_physnet.called)

    def test__check_allowed_port_fields_allow(self, mock_allow_port,
                                              mock_allow_portgroup,
                                              mock_allow_physnet):
        mock_allow_port.return_value = True
        for field in api_port.PortsController.advanced_net_fields:
            self.assertIsNone(
                self.controller._check_allowed_port_fields([field]))
            mock_allow_port.assert_called_once_with()
            mock_allow_port.reset_mock()
            self.assertFalse(mock_allow_portgroup.called)
            self.assertFalse(mock_allow_physnet.called)

    def test__check_allowed_port_fields_portgroup_not_allow(
            self, mock_allow_port, mock_allow_portgroup, mock_allow_physnet):
        mock_allow_port.return_value = True
        mock_allow_portgroup.return_value = False
        self.assertRaises(exception.NotAcceptable,
                          self.controller._check_allowed_port_fields,
                          ['portgroup_uuid'])
        mock_allow_port.assert_called_once_with()
        mock_allow_portgroup.assert_called_once_with()
        self.assertFalse(mock_allow_physnet.called)

    def test__check_allowed_port_fields_portgroup_allow(
            self, mock_allow_port, mock_allow_portgroup, mock_allow_physnet):
        mock_allow_port.return_value = True
        mock_allow_portgroup.return_value = True
        self.assertIsNone(
            self.controller._check_allowed_port_fields(['portgroup_uuid']))
        mock_allow_port.assert_called_once_with()
        mock_allow_portgroup.assert_called_once_with()
        self.assertFalse(mock_allow_physnet.called)

    def test__check_allowed_port_fields_physnet_not_allow(
            self, mock_allow_port, mock_allow_portgroup, mock_allow_physnet):
        mock_allow_port.return_value = True
        mock_allow_physnet.return_value = False
        self.assertRaises(exception.NotAcceptable,
                          self.controller._check_allowed_port_fields,
                          ['physical_network'])
        mock_allow_port.assert_called_once_with()
        self.assertFalse(mock_allow_portgroup.called)
        mock_allow_physnet.assert_called_once_with()

    def test__check_allowed_port_fields_physnet_allow(
            self, mock_allow_port, mock_allow_portgroup, mock_allow_physnet):
        mock_allow_port.return_value = True
        mock_allow_physnet.return_value = True
        self.assertIsNone(
            self.controller._check_allowed_port_fields(['physical_network']))
        mock_allow_port.assert_called_once_with()
        self.assertFalse(mock_allow_portgroup.called)
        mock_allow_physnet.assert_called_once_with()

    def test__check_allowed_port_fields_local_link_connection_none_type(
            self, mock_allow_port, mock_allow_portgroup, mock_allow_physnet):
        mock_allow_port.return_value = True
        mock_allow_physnet.return_value = True
        self.assertIsNone(
            self.controller._check_allowed_port_fields(
                {'local_link_connection': None}))
        mock_allow_port.assert_called_once_with()


@mock.patch.object(objects.Port, 'list', autospec=True)
@mock.patch.object(api, 'request', spec_set=['context'])
class TestPortsController__GetPortsCollection(base.TestCase):

    def setUp(self):
        super(TestPortsController__GetPortsCollection, self).setUp()
        self.controller = api_port.PortsController()

    def test__get_ports_collection(self, mock_request, mock_list):
        mock_request.context = 'fake-context'
        mock_list.return_value = []
        self.controller._get_ports_collection(None, None, None, None, None,
                                              None, 'asc')
        mock_list.assert_called_once_with('fake-context', 1000, None,
                                          project=None, sort_dir='asc',
                                          sort_key=None)


@mock.patch.object(objects.Port, 'get_by_address', autospec=True)
@mock.patch.object(api, 'request', spec_set=['context'])
class TestPortsController__GetPortByAddress(base.TestCase):

    def setUp(self):
        super(TestPortsController__GetPortByAddress, self).setUp()
        self.controller = api_port.PortsController()

    def test__get_ports_by_address(self, mock_request, mock_gba):
        mock_request.context = 'fake-context'
        mock_gba.return_value = None
        self.controller._get_ports_by_address('fake-address')
        mock_gba.assert_called_once_with('fake-context', 'fake-address',
                                         project=None)


class TestListPorts(test_api_base.BaseApiTest):

    def setUp(self):
        super(TestListPorts, self).setUp()
        self.node = obj_utils.create_test_node(self.context, owner='12345')

    def test_empty(self):
        data = self.get_json('/ports')
        self.assertEqual([], data['ports'])

    def test_one(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        data = self.get_json('/ports')
        self.assertEqual(port.uuid, data['ports'][0]["uuid"])
        self.assertNotIn('extra', data['ports'][0])
        self.assertNotIn('node_uuid', data['ports'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['ports'][0])

    # NOTE(jlvillal): autospec=True doesn't work on staticmethods:
    # https://bugs.python.org/issue23078
    @mock.patch.object(objects.Node, 'get', spec_set=types.FunctionType)
    def test_list_with_deleted_node(self, mock_get_node):
        # check that we don't end up with HTTP 400 when node deletion races
        # with listing ports - see https://launchpad.net/bugs/1748893
        obj_utils.create_test_port(self.context, node_id=self.node.id)
        mock_get_node.side_effect = exception.NodeNotFound('boom')
        data = self.get_json('/ports')
        self.assertEqual([], data['ports'])

    # NOTE(jlvillal): autospec=True doesn't work on staticmethods:
    # https://bugs.python.org/issue23078
    @mock.patch.object(objects.Node, 'get', spec_set=types.FunctionType)
    def test_list_detailed_with_deleted_node(self, mock_get_node):
        # check that we don't end up with HTTP 400 when node deletion races
        # with listing ports - see https://launchpad.net/bugs/1748893
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        port2 = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                           uuid=uuidutils.generate_uuid(),
                                           address='66:44:55:33:11:22')
        mock_get_node.side_effect = [exception.NodeNotFound('boom'), self.node]
        data = self.get_json('/ports/detail')
        # The "correct" port is still returned
        self.assertEqual(1, len(data['ports']))
        self.assertIn(data['ports'][0]['uuid'], {port.uuid, port2.uuid})
        self.assertEqual(self.node.uuid, data['ports'][0]['node_uuid'])

    # NOTE(jlvillal): autospec=True doesn't work on staticmethods:
    # https://bugs.python.org/issue23078
    @mock.patch.object(objects.Portgroup, 'get', spec_set=types.FunctionType)
    def test_list_with_deleted_port_group(self, mock_get_pg):
        # check that we don't end up with HTTP 400 when port group deletion
        # races with listing ports - see https://launchpad.net/bugs/1748893
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=portgroup.id)
        mock_get_pg.side_effect = exception.PortgroupNotFound('boom')
        data = self.get_json(
            '/ports/detail',
            headers={api_base.Version.string: str(api_v1.max_version())}
        )
        self.assertEqual(port.uuid, data['ports'][0]["uuid"])
        self.assertIsNone(data['ports'][0]["portgroup_uuid"])

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_list_non_admin_forbidden(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            raise exception.HTTPForbidden(resource='fake')
        mock_authorize.side_effect = mock_authorize_function

        address_template = "aa:bb:cc:dd:ee:f%d"
        for id_ in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address=address_template % id_)

        response = self.get_json('/ports',
                                 headers={'X-Project-Id': '12345'},
                                 expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_list_non_admin_forbidden_no_project(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        address_template = "aa:bb:cc:dd:ee:f%d"
        for id_ in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address=address_template % id_)

        response = self.get_json('/ports', expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_get_one(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        data = self.get_json('/ports/%s' % port.uuid)
        self.assertEqual(port.uuid, data['uuid'])
        self.assertIn('extra', data)
        self.assertIn('node_uuid', data)
        # never expose the node_id, port_id, portgroup_id
        self.assertNotIn('node_id', data)
        self.assertNotIn('port_id', data)
        self.assertNotIn('portgroup_id', data)
        self.assertNotIn('portgroup_uuid', data)

    def test_get_one_portgroup_is_none(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        data = self.get_json('/ports/%s' % port.uuid,
                             headers={api_base.Version.string: '1.24'})
        self.assertEqual(port.uuid, data['uuid'])
        self.assertIn('extra', data)
        self.assertIn('node_uuid', data)
        # never expose the node_id, port_id, portgroup_id
        self.assertNotIn('node_id', data)
        self.assertNotIn('port_id', data)
        self.assertNotIn('portgroup_id', data)
        self.assertIn('portgroup_uuid', data)

    def test_get_one_custom_fields(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        fields = 'address,extra'
        data = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: str(api_v1.max_version())})
        # We always append "links"
        self.assertCountEqual(['address', 'extra', 'links'], data)

    def test_hide_fields_in_newer_versions_internal_info(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          internal_info={"foo": "bar"})
        data = self.get_json(
            '/ports/%s' % port.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())})
        self.assertNotIn('internal_info', data)

        data = self.get_json('/ports/%s' % port.uuid,
                             headers={api_base.Version.string: "1.18"})
        self.assertEqual({"foo": "bar"}, data['internal_info'])

    def test_hide_fields_in_newer_versions_advanced_net(self):
        llc = {'switch_info': 'switch', 'switch_id': 'aa:bb:cc:dd:ee:ff',
               'port_id': 'Gig0/1'}
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          pxe_enabled=True,
                                          local_link_connection=llc)
        data = self.get_json(
            '/ports/%s' % port.uuid,
            headers={api_base.Version.string: "1.18"})
        self.assertNotIn('pxe_enabled', data)
        self.assertNotIn('local_link_connection', data)

        data = self.get_json('/ports/%s' % port.uuid,
                             headers={api_base.Version.string: "1.19"})
        self.assertTrue(data['pxe_enabled'])
        self.assertEqual(llc, data['local_link_connection'])

    def test_hide_fields_in_newer_versions_portgroup_uuid(self):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=portgroup.id)
        data = self.get_json(
            '/ports/%s' % port.uuid,
            headers={api_base.Version.string: "1.23"})
        self.assertNotIn('portgroup_uuid', data)

        data = self.get_json('/ports/%s' % port.uuid,
                             headers={api_base.Version.string: "1.24"})
        self.assertEqual(portgroup.uuid, data['portgroup_uuid'])

    def test_hide_fields_in_newer_versions_physical_network(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          physical_network='physnet1')
        data = self.get_json(
            '/ports/%s' % port.uuid,
            headers={api_base.Version.string: "1.33"})
        self.assertNotIn('physical_network', data)

        data = self.get_json('/ports/%s' % port.uuid,
                             headers={api_base.Version.string: "1.34"})
        self.assertEqual("physnet1", data['physical_network'])

    @mock.patch.object(objects.Port, 'supports_physical_network')
    def test_hide_fields_in_newer_versions_physical_network_upgrade(self,
                                                                    mock_spn):
        mock_spn.return_value = False
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          physical_network='physnet1')
        data = self.get_json(
            '/ports/%s' % port.uuid,
            headers={api_base.Version.string: "1.34"})
        self.assertNotIn('physical_network', data)

    def test_hide_fields_in_newer_versions_is_smartnic(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          is_smartnic=True)
        data = self.get_json(
            '/ports/%s' % port.uuid,
            headers={api_base.Version.string: "1.52"})
        self.assertNotIn('is_smartnic', data)

        data = self.get_json('/ports/%s' % port.uuid,
                             headers={api_base.Version.string: "1.53"})
        self.assertTrue(data['is_smartnic'])

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address='52:54:00:cf:2d:3%s' % i)

        data = self.get_json(
            '/ports?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(3, len(data['ports']))
        for port in data['ports']:
            # We always append "links"
            self.assertCountEqual(['uuid', 'extra', 'links'], port)

    def test_get_collection_next_marker_no_uuid(self):
        fields = 'address'
        limit = 2
        ports = []
        for i in range(3):
            port = obj_utils.create_test_port(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % i
            )
            ports.append(port)

        data = self.get_json(
            '/ports?fields=%s&limit=%s' % (fields, limit),
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(limit, len(data['ports']))
        self.assertIn('marker=%s' % ports[limit - 1].uuid, data['next'])

    def test_get_custom_fields_invalid_fields(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_custom_fields_invalid_api_version(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        fields = 'uuid,extra'
        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

    def test_get_custom_fields_physical_network(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          physical_network='physnet1')
        fields = 'uuid,physical_network'
        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: "1.33"},
            expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: "1.34"})
        # We always append "links".
        self.assertCountEqual(['uuid', 'physical_network', 'links'], response)

    @mock.patch.object(objects.Port, 'supports_physical_network')
    def test_get_custom_fields_physical_network_upgrade(self, mock_spn):
        mock_spn.return_value = False
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          physical_network='physnet1')
        fields = 'uuid,physical_network'
        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: "1.34"},
            expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

    def test_get_custom_fields_is_smartnic(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          is_smartnic=True)
        fields = 'uuid,is_smartnic'
        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: "1.52"},
            expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

        response = self.get_json(
            '/ports/%s?fields=%s' % (port.uuid, fields),
            headers={api_base.Version.string: "1.53"})

        # 'links' field is always retrieved in the response
        # regardless of which fields are specified.
        self.assertCountEqual(['uuid', 'is_smartnic', 'links'], response)

    def test_detail(self):
        llc = {'switch_info': 'switch', 'switch_id': 'aa:bb:cc:dd:ee:ff',
               'port_id': 'Gig0/1'}
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=portgroup.id,
                                          pxe_enabled=False,
                                          local_link_connection=llc,
                                          physical_network='physnet1',
                                          is_smartnic=True)
        data = self.get_json(
            '/ports/detail',
            headers={api_base.Version.string: str(api_v1.max_version())}
        )
        self.assertEqual(port.uuid, data['ports'][0]["uuid"])
        self.assertIn('extra', data['ports'][0])
        self.assertIn('internal_info', data['ports'][0])
        self.assertIn('node_uuid', data['ports'][0])
        self.assertIn('pxe_enabled', data['ports'][0])
        self.assertIn('local_link_connection', data['ports'][0])
        self.assertIn('portgroup_uuid', data['ports'][0])
        self.assertIn('physical_network', data['ports'][0])
        self.assertIn('is_smartnic', data['ports'][0])
        # never expose the node_id and portgroup_id
        self.assertNotIn('node_id', data['ports'][0])
        self.assertNotIn('portgroup_id', data['ports'][0])

    def test_detail_query(self):
        llc = {'switch_info': 'switch', 'switch_id': 'aa:bb:cc:dd:ee:ff',
               'port_id': 'Gig0/1'}
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=portgroup.id,
                                          pxe_enabled=False,
                                          local_link_connection=llc,
                                          physical_network='physnet1')
        data = self.get_json(
            '/ports?detail=True',
            headers={api_base.Version.string: str(api_v1.max_version())}
        )
        self.assertEqual(port.uuid, data['ports'][0]["uuid"])
        self.assertIn('extra', data['ports'][0])
        self.assertIn('internal_info', data['ports'][0])
        self.assertIn('node_uuid', data['ports'][0])
        self.assertIn('pxe_enabled', data['ports'][0])
        self.assertIn('local_link_connection', data['ports'][0])
        self.assertIn('portgroup_uuid', data['ports'][0])
        self.assertIn('physical_network', data['ports'][0])
        # never expose the node_id and portgroup_id
        self.assertNotIn('node_id', data['ports'][0])
        self.assertNotIn('portgroup_id', data['ports'][0])

    def test_detail_query_false(self):
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   pxe_enabled=False,
                                   physical_network='physnet1')
        data1 = self.get_json(
            '/ports',
            headers={api_base.Version.string: str(api_v1.max_version())})
        data2 = self.get_json(
            '/ports?detail=False',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(data1['ports'], data2['ports'])

    def test_detail_using_query_false_and_fields(self):
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   pxe_enabled=False,
                                   physical_network='physnet1')
        data = self.get_json(
            '/ports?detail=False&fields=internal_info',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertIn('internal_info', data['ports'][0])
        self.assertNotIn('uuid', data['ports'][0])

    def test_detail_using_query_and_fields(self):
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   pxe_enabled=False,
                                   physical_network='physnet1')
        response = self.get_json(
            '/ports?detail=True&fields=name',
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_using_query_old_version(self):
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   pxe_enabled=False,
                                   physical_network='physnet1')
        response = self.get_json(
            '/ports?detail=True',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_against_single(self):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        response = self.get_json('/ports/%s/detail' % port.uuid,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_many(self):
        ports = []
        for id_ in range(5):
            port = obj_utils.create_test_port(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_)
            ports.append(port.uuid)
        data = self.get_json('/ports')
        self.assertEqual(len(ports), len(data['ports']))

        uuids = [n['uuid'] for n in data['ports']]
        self.assertCountEqual(ports, uuids)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_many_non_admin(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        ports = []
        # these ports should be retrieved by the API call
        for id_ in range(0, 2):
            port = obj_utils.create_test_port(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_)
            ports.append(port.uuid)
        # these ports should NOT be retrieved by the API call
        for id_ in range(3, 5):
            port = obj_utils.create_test_port(
                self.context, uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_)
        data = self.get_json('/ports', headers={'X-Project-Id': '12345'})
        self.assertEqual(len(ports), len(data['ports']))

        uuids = [n['uuid'] for n in data['ports']]
        self.assertCountEqual(ports, uuids)

    def _test_links(self, public_url=None):
        cfg.CONF.set_override('public_endpoint', public_url, 'api')
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_port(self.context,
                                   uuid=uuid,
                                   node_id=self.node.id)
        data = self.get_json('/ports/%s' % uuid)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for link in data['links']:
            bookmark = link['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(link['href'],
                            bookmark=bookmark))

        if public_url is not None:
            expected = [{'href': '%s/v1/ports/%s' % (public_url, uuid),
                         'rel': 'self'},
                        {'href': '%s/ports/%s' % (public_url, uuid),
                         'rel': 'bookmark'}]
            for i in expected:
                self.assertIn(i, data['links'])

    def test_links(self):
        self._test_links()

    def test_links_public_url(self):
        self._test_links(public_url='http://foo')

    def test_collection_links(self):
        ports = []
        for id_ in range(5):
            port = obj_utils.create_test_port(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_)
            ports.append(port.uuid)
        data = self.get_json('/ports/?limit=3')
        self.assertEqual(3, len(data['ports']))

        next_marker = data['ports'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        ports = []
        for id_ in range(5):
            port = obj_utils.create_test_port(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_)
            ports.append(port.uuid)
        data = self.get_json('/ports')
        self.assertEqual(3, len(data['ports']))

        next_marker = data['ports'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_custom_fields(self):
        fields = 'address,uuid'
        cfg.CONF.set_override('max_limit', 3, 'api')
        for i in range(5):
            obj_utils.create_test_port(
                self.context,
                uuid=uuidutils.generate_uuid(),
                node_id=self.node.id,
                address='52:54:00:cf:2d:3%s' % i)

        data = self.get_json(
            '/ports?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(3, len(data['ports']))
        next_marker = data['ports'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('fields', data['next'])

    def test_port_by_address(self):
        address_template = "aa:bb:cc:dd:ee:f%d"
        for id_ in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address=address_template % id_)

        target_address = address_template % 1
        data = self.get_json('/ports?address=%s' % target_address)
        self.assertThat(data['ports'], matchers.HasLength(1))
        self.assertEqual(target_address, data['ports'][0]['address'])

    def test_port_by_address_non_existent_address(self):
        # non-existent address
        data = self.get_json('/ports?address=%s' % 'aa:bb:cc:dd:ee:ff')
        self.assertThat(data['ports'], matchers.HasLength(0))

    def test_port_by_address_invalid_address_format(self):
        obj_utils.create_test_port(self.context, node_id=self.node.id)
        invalid_address = 'invalid-mac-format'
        response = self.get_json('/ports?address=%s' % invalid_address,
                                 expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(invalid_address, response.json['error_message'])

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_port_by_address_non_admin(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        address_template = "aa:bb:cc:dd:ee:f%d"
        for id_ in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address=address_template % id_)

        target_address = address_template % 1
        data = self.get_json('/ports?address=%s' % target_address,
                             headers={'X-Project-Id': '12345'})
        self.assertThat(data['ports'], matchers.HasLength(1))
        self.assertEqual(target_address, data['ports'][0]['address'])

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_port_by_address_non_admin_no_match(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        address_template = "aa:bb:cc:dd:ee:f%d"
        for id_ in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address=address_template % id_)

        target_address = address_template % 1
        data = self.get_json('/ports?address=%s' % target_address,
                             headers={'X-Project-Id': '54321'})
        self.assertThat(data['ports'], matchers.HasLength(0))

    def test_sort_key(self):
        ports = []
        for id_ in range(3):
            port = obj_utils.create_test_port(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_)
            ports.append(port.uuid)
        data = self.get_json('/ports?sort_key=uuid')
        uuids = [n['uuid'] for n in data['ports']]
        self.assertEqual(sorted(ports), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra', 'internal_info',
                             'local_link_connection']
        for invalid_key in invalid_keys_list:
            response = self.get_json(
                '/ports?sort_key=%s' % invalid_key, expect_errors=True,
                headers={api_base.Version.string: str(api_v1.max_version())}
            )
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    def _test_sort_key_allowed(self, detail=False):
        port_uuids = []
        for id_ in range(2):
            port = obj_utils.create_test_port(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                address='52:54:00:cf:2d:3%s' % id_,
                pxe_enabled=id_ % 2)
            port_uuids.append(port.uuid)
        headers = {api_base.Version.string: str(api_v1.max_version())}
        detail_str = '/detail' if detail else ''
        data = self.get_json('/ports%s?sort_key=pxe_enabled' % detail_str,
                             headers=headers)
        data_uuids = [p['uuid'] for p in data['ports']]
        self.assertEqual(port_uuids, data_uuids)

    def test_sort_key_allowed(self):
        self._test_sort_key_allowed()

    def test_detail_sort_key_allowed(self):
        self._test_sort_key_allowed(detail=True)

    def _test_sort_key_not_allowed(self, detail=False):
        headers = {api_base.Version.string: '1.18'}
        detail_str = '/detail' if detail else ''
        resp = self.get_json('/ports%s?sort_key=pxe_enabled' % detail_str,
                             headers=headers, expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, resp.status_int)
        self.assertEqual('application/json', resp.content_type)

    def test_sort_key_not_allowed(self):
        self._test_sort_key_not_allowed()

    def test_detail_sort_key_not_allowed(self):
        self._test_sort_key_not_allowed(detail=True)

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/ports specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_port(self.context,
                                       node_id=node_id,
                                       uuid=uuidutils.generate_uuid(),
                                       address='52:54:00:cf:2d:3%s' % i)
        data = self.get_json("/ports?node=%s" % 'test-node',
                             headers={api_base.Version.string: '1.5'})
        self.assertEqual(3, len(data['ports']))

    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_name_non_admin(
            self, mock_get_rpc_node, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_get_rpc_node.return_value = self.node

        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_port(self.context,
                                       node_id=node_id,
                                       uuid=uuidutils.generate_uuid(),
                                       address='52:54:00:cf:2d:3%s' % i)
        data = self.get_json("/ports?node=%s" % 'test-node',
                             headers={
                                 api_base.Version.string: '1.5',
                                 'X-Project-Id': '12345'
                             })
        self.assertEqual(3, len(data['ports']))

    @mock.patch.object(policy, 'authorize', spec=True)
    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_name_non_admin_no_match(
            self, mock_get_rpc_node, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        mock_get_rpc_node.return_value = self.node

        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_port(self.context,
                                       node_id=node_id,
                                       uuid=uuidutils.generate_uuid(),
                                       address='52:54:00:cf:2d:3%s' % i)
        data = self.get_json("/ports?node=%s" % 'test-node',
                             headers={
                                 api_base.Version.string: '1.5',
                                 'X-Project-Id': '54321'
                             })
        self.assertEqual(0, len(data['ports']))

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_uuid_and_name(self, mock_get_rpc_node):
        # GET /v1/ports specifying node and uuid - should only use node_uuid
        mock_get_rpc_node.return_value = self.node
        obj_utils.create_test_port(self.context, node_id=self.node.id)
        self.get_json('/ports/detail?node_uuid=%s&node=%s' %
                      (self.node.uuid, 'node-name'))
        mock_get_rpc_node.assert_called_once_with(self.node.uuid)

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_name_not_supported(self, mock_get_rpc_node):
        # GET /v1/ports specifying node_name - name not supported
        mock_get_rpc_node.side_effect = (
            exception.InvalidUuidOrName(name=self.node.uuid))
        for i in range(3):
            obj_utils.create_test_port(self.context,
                                       node_id=self.node.id,
                                       uuid=uuidutils.generate_uuid(),
                                       address='52:54:00:cf:2d:3%s' % i)
        data = self.get_json("/ports?node=%s" % 'test-node',
                             expect_errors=True)
        self.assertEqual(0, mock_get_rpc_node.call_count)
        self.assertEqual(http_client.NOT_ACCEPTABLE, data.status_int)

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_detail_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/ports/detail specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        data = self.get_json('/ports/detail?node=%s' % 'test-node',
                             headers={api_base.Version.string: '1.5'})
        self.assertEqual(port.uuid, data['ports'][0]['uuid'])
        self.assertEqual(self.node.uuid, data['ports'][0]['node_uuid'])

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_detail_by_node_name_not_supported(self, mock_get_rpc_node):
        # GET /v1/ports/detail specifying node_name - name not supported
        mock_get_rpc_node.side_effect = (
            exception.InvalidUuidOrName(name=self.node.uuid))
        obj_utils.create_test_port(self.context, node_id=self.node.id)
        data = self.get_json('/ports/detail?node=%s' % 'test-node',
                             expect_errors=True)
        self.assertEqual(0, mock_get_rpc_node.call_count)
        self.assertEqual(http_client.NOT_ACCEPTABLE, data.status_int)

    def test_get_all_by_portgroup_uuid(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=pg.id)
        data = self.get_json('/ports/detail?portgroup=%s' % pg.uuid,
                             headers={api_base.Version.string: '1.24'})
        self.assertEqual(port.uuid, data['ports'][0]['uuid'])
        self.assertEqual(pg.uuid,
                         data['ports'][0]['portgroup_uuid'])

    def test_get_all_by_portgroup_uuid_older_api_version(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        response = self.get_json(
            '/ports/detail?portgroup=%s' % pg.uuid,
            headers={api_base.Version.string: '1.14'},
            expect_errors=True
        )
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_get_all_by_portgroup_uuid_non_admin(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=pg.id)
        data = self.get_json('/ports/detail?portgroup=%s' % pg.uuid,
                             headers={
                                 api_base.Version.string: '1.24',
                                 'X-Project-Id': '12345'
                             })

        self.assertEqual(port.uuid, data['ports'][0]['uuid'])
        self.assertEqual(pg.uuid,
                         data['ports'][0]['portgroup_uuid'])

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_get_all_by_portgroup_uuid_non_admin_no_match(
            self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:port:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        pg = obj_utils.create_test_portgroup(self.context)
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   portgroup_id=pg.id)
        data = self.get_json('/ports/detail?portgroup=%s' % pg.uuid,
                             headers={
                                 api_base.Version.string: '1.24',
                                 'X-Project-Id': '54321'
                             })

        self.assertThat(data['ports'], matchers.HasLength(0))

    def test_get_all_by_portgroup_name(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=pg.id)
        data = self.get_json('/ports/detail?portgroup=%s' % pg.name,
                             headers={api_base.Version.string: '1.24'})
        self.assertEqual(port.uuid, data['ports'][0]['uuid'])
        self.assertEqual(pg.uuid,
                         data['ports'][0]['portgroup_uuid'])
        self.assertEqual(1, len(data['ports']))

    def test_get_all_by_portgroup_uuid_and_node_uuid(self):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id)
        response = self.get_json(
            '/ports/detail?portgroup=%s&node=%s' % (pg.uuid, self.node.uuid),
            headers={api_base.Version.string: '1.24'},
            expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(api_port.PortsController, '_get_ports_collection',
                       autospec=True)
    def test_detail_with_incorrect_api_usage(self, mock_gpc):
        mock_gpc.return_value = api_port.PortCollection.convert_with_links(
            [], 0)
        # GET /v1/ports/detail specifying node and node_uuid.  In this case
        # we expect the node_uuid interface to be used.
        self.get_json('/ports/detail?node=%s&node_uuid=%s' %
                      ('test-node', self.node.uuid))
        self.assertEqual(1, mock_gpc.call_count)
        self.assertEqual(self.node.uuid, mock_gpc.call_args[0][1])

    def test_portgroups_subresource_node_not_found(self):
        non_existent_uuid = 'eeeeeeee-cccc-aaaa-bbbb-cccccccccccc'
        response = self.get_json('/portgroups/%s/ports' % non_existent_uuid,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_portgroups_subresource_invalid_ident(self):
        invalid_ident = '123 123'
        response = self.get_json('/portgroups/%s/ports' % invalid_ident,
                                 headers={api_base.Version.string: '1.24'},
                                 expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('Expected a logical name or UUID',
                      response.json['error_message'])


@mock.patch.object(rpcapi.ConductorAPI, 'update_port', autospec=True,
                   side_effect=_rpcapi_update_port)
class TestPatch(test_api_base.BaseApiTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)

        p = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = p.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(p.stop)

    def _test_success(self, mock_upd, patch, version):
        # Helper to test an update to a port that is expected to succeed at a
        # given API version.
        headers = {api_base.Version.string: version}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   patch,
                                   headers=headers)

        self.assertEqual(http_client.OK, response.status_code)
        self.assertTrue(mock_upd.called)
        self.assertEqual(self.port.id, mock_upd.call_args[0][2].id)
        return response

    def _test_old_api_version(self, mock_upd, patch, version):
        # Helper to test an update to a port affecting a field that is not
        # available in the specified API version.
        headers = {api_base.Version.string: version}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   patch,
                                   expect_errors=True,
                                   headers=headers)

        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_upd.called)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_update_byid(self, mock_notify, mock_upd):
        extra = {'foo': 'bar'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=atypes.Unset),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=atypes.Unset)])

    def test_update_byaddress_not_allowed(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.address,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn(self.port.address, response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_not_found(self, mock_upd):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/ports/%s' % uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_singular(self, mock_upd):
        address = 'aa:bb:cc:dd:ee:ff'
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(address, response.json['address'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address, kargs.address)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_replace_address_already_exist(self, mock_notify, mock_upd):
        address = 'aa:aa:aa:aa:aa:aa'
        mock_upd.side_effect = exception.MACAlreadyExists(mac=address)
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address, kargs.address)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=atypes.Unset),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=atypes.Unset)])

    def test_replace_node_uuid(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_replace_local_link_connection(self, mock_upd):
        switch_id = 'aa:bb:cc:dd:ee:ff'
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path':
                                     '/local_link_connection/switch_id',
                                     'value': switch_id,
                                     'op': 'replace'}],
                                   headers={api_base.Version.string: '1.19'})
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(switch_id,
                         response.json['local_link_connection']['switch_id'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][2]
        self.assertEqual(switch_id, kargs.local_link_connection['switch_id'])

    def test_remove_local_link_connection_old_api(self, mock_upd):
        response = self.patch_json(
            '/ports/%s' % self.port.uuid,
            [{'path': '/local_link_connection/switch_id', 'op': 'remove'}],
            expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_code)

    def test_add_local_link_connection_network_type(self, mock_upd):
        response = self.patch_json(
            '/ports/%s' % self.port.uuid,
            [{'path': '/local_link_connection/network_type',
              'value': 'unmanaged', 'op': 'add'}],
            headers={api_base.Version.string: '1.64'})
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(
            'unmanaged',
            response.json['local_link_connection']['network_type'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][2]
        self.assertEqual('unmanaged',
                         kargs.local_link_connection['network_type'])

    def test_add_local_link_connection_network_type_old_api(self, mock_upd):
        response = self.patch_json(
            '/ports/%s' % self.port.uuid,
            [{'path': '/local_link_connection/network_type',
              'value': 'unmanaged', 'op': 'add'}],
            headers={api_base.Version.string: '1.63'}, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_code)

    def test_remove_local_link_connection_network_type(self, mock_upd):
        llc = {'network_type': 'unmanaged'}
        port = obj_utils.create_test_port(self.context,
                                          node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='bb:bb:bb:bb:bb:bb',
                                          local_link_connection=llc)
        llc.pop('network_type')
        response = self.patch_json(
            '/ports/%s' % port.uuid,
            [{'path': '/local_link_connection/network_type', 'op': 'remove'}],
            headers={api_base.Version.string: '1.64'})
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertTrue(mock_upd.called)
        self.assertEqual(llc, response.json['local_link_connection'])

    def test_remove_local_link_connection_network_type_old_api(self, mock_upd):
        response = self.patch_json(
            '/ports/%s' % self.port.uuid,
            [{'path': '/local_link_connection/network_type', 'op': 'remove'}],
            headers={api_base.Version.string: '1.63'}, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_code)

    def test_set_pxe_enabled_false_old_api(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/pxe_enabled',
                                     'value': False,
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_code)

    def test_add_portgroup_uuid(self, mock_upd):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id,
                                             uuid=uuidutils.generate_uuid(),
                                             address='bb:bb:bb:bb:bb:bb',
                                             name='bar')
        headers = {api_base.Version.string: '1.24'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path':
                                     '/portgroup_uuid',
                                     'value': pg.uuid,
                                     'op': 'add'}],
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_replace_portgroup_uuid(self, mock_upd):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id,
                                             uuid=uuidutils.generate_uuid(),
                                             address='bb:bb:bb:bb:bb:bb',
                                             name='bar')
        headers = {api_base.Version.string: '1.24'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/portgroup_uuid',
                                     'value': pg.uuid,
                                     'op': 'replace'}],
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_replace_portgroup_uuid_remove(self, mock_upd):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id,
                                             uuid=uuidutils.generate_uuid(),
                                             address='bb:bb:bb:bb:bb:bb',
                                             name='bar')
        headers = {api_base.Version.string: '1.24'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/portgroup_uuid',
                                     'value': pg.uuid,
                                     'op': 'remove'}],
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertIsNone(mock_upd.call_args[0][2].portgroup_id)

    def test_replace_portgroup_uuid_remove_add(self, mock_upd):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id,
                                             uuid=uuidutils.generate_uuid(),
                                             address='bb:bb:bb:bb:bb:bb',
                                             name='bar')
        pg1 = obj_utils.create_test_portgroup(self.context,
                                              node_id=self.node.id,
                                              uuid=uuidutils.generate_uuid(),
                                              address='bb:bb:bb:bb:bb:b1',
                                              name='bbb')
        headers = {api_base.Version.string: '1.24'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/portgroup_uuid',
                                     'value': pg.uuid,
                                     'op': 'remove'},
                                    {'path': '/portgroup_uuid',
                                     'value': pg1.uuid,
                                     'op': 'add'}],
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(pg1.id, mock_upd.call_args[0][2].portgroup_id)

    def test_replace_portgroup_uuid_old_api(self, mock_upd):
        pg = obj_utils.create_test_portgroup(self.context,
                                             node_id=self.node.id,
                                             uuid=uuidutils.generate_uuid(),
                                             address='bb:bb:bb:bb:bb:bb',
                                             name='bar')
        headers = {api_base.Version.string: '1.15'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/portgroup_uuid',
                                     'value': pg.uuid,
                                     'op': 'replace'}],
                                   headers=headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_code)

    def test_add_node_uuid(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_add_node_id(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_node_id(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'replace'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_remove_node_id(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/node_id',
                                     'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_non_existent_node_uuid(self, mock_upd):
        node_uuid = '12506333-a81c-4d59-9987-889ed5f8687b'
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/node_uuid',
                                     'value': node_uuid,
                                     'op': 'replace'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertIn(node_uuid, response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.port.extra = extra
        self.port.save()

        # mutate extra so we replace all of them
        extra = dict((k, extra[k] + 'x') for k in extra)

        patch = []
        for k in extra:
            patch.append({'path': '/extra/%s' % k,
                          'value': extra[k],
                          'op': 'replace'})
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   patch)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

    def test_remove_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.port.extra = extra
        self.port.save()

        # Removing one item from the collection
        extra.pop('foo1')
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/extra/foo1',
                                     'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

        # Removing the collection
        extra = {}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/extra', 'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual({}, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

        # Assert nothing else was changed
        self.assertEqual(self.port.uuid, response.json['uuid'])
        self.assertEqual(self.port.address, response.json['address'])

    def test_remove_non_existent_property_fail(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/extra/non-existent',
                                     'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_remove_mandatory_field(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/address',
                                     'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertIn('mandatory attribute', response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_add_root(self, mock_upd):
        address = 'aa:bb:cc:dd:ee:ff'
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(address, response.json['address'])
        self.assertTrue(mock_upd.called)
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address, kargs.address)

    def test_add_root_non_existent(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
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
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   patch)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(extra, kargs.extra)

    def test_remove_uuid(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/uuid',
                                     'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_address_invalid_format(self, mock_upd):
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/address',
                                     'value': 'invalid-format',
                                     'op': 'replace'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_update_port_address_normalized(self, mock_upd):
        address = 'AA:BB:CC:DD:EE:FF'
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/address',
                                     'value': address,
                                     'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(address.lower(), response.json['address'])
        kargs = mock_upd.call_args[0][2]
        self.assertEqual(address.lower(), kargs.address)

    def test_update_pxe_enabled_allowed(self, mock_upd):
        pxe_enabled = True
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/pxe_enabled',
                                     'value': pxe_enabled,
                                     'op': 'replace'}],
                                   headers={api_base.Version.string: '1.19'})
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(pxe_enabled, response.json['pxe_enabled'])

    def test_update_pxe_enabled_old_api_version(self, mock_upd):
        pxe_enabled = True
        headers = {api_base.Version.string: '1.14'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/pxe_enabled',
                                     'value': pxe_enabled,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_upd.called)

    def _test_physical_network_success(self, mock_upd, patch,
                                       expected_physical_network):
        # Helper to test an update to a port's physical_network that is
        # expected to succeed at API version 1.34.
        response = self._test_success(mock_upd, patch, '1.34')

        self.assertEqual(expected_physical_network,
                         response.json['physical_network'])
        self.port.refresh()
        self.assertEqual(expected_physical_network,
                         self.port.physical_network)

    def test_add_physical_network(self, mock_upd):
        physical_network = 'physnet1'
        patch = [{'path': '/physical_network',
                  'value': physical_network,
                  'op': 'add'}]
        self._test_physical_network_success(mock_upd, patch, physical_network)

    def test_replace_physical_network(self, mock_upd):
        self.port.physical_network = 'physnet1'
        self.port.save()
        new_physical_network = 'physnet2'
        patch = [{'path': '/physical_network',
                  'value': new_physical_network,
                  'op': 'replace'}]
        self._test_physical_network_success(mock_upd, patch,
                                            new_physical_network)

    def test_remove_physical_network(self, mock_upd):
        self.port.physical_network = 'physnet1'
        self.port.save()
        patch = [{'path': '/physical_network', 'op': 'remove'}]
        self._test_physical_network_success(mock_upd, patch, None)

    def _test_physical_network_old_api_version(self, mock_upd, patch,
                                               expected_physical_network):
        # Helper to test an update to a port's physical network that is
        # expected to fail at API version 1.33.
        self._test_old_api_version(mock_upd, patch, '1.33')

        self.port.refresh()
        self.assertEqual(expected_physical_network, self.port.physical_network)

    def test_add_physical_network_old_api_version(self, mock_upd):
        patch = [{'path': '/physical_network',
                  'value': 'physnet1',
                  'op': 'add'}]
        self._test_physical_network_old_api_version(mock_upd, patch, None)

    def test_replace_physical_network_old_api_version(self, mock_upd):
        self.port.physical_network = 'physnet1'
        self.port.save()
        patch = [{'path': '/physical_network',
                  'value': 'physnet2',
                  'op': 'replace'}]
        self._test_physical_network_old_api_version(mock_upd, patch,
                                                    'physnet1')

    def test_remove_physical_network_old_api_version(self, mock_upd):
        self.port.physical_network = 'physnet1'
        self.port.save()
        patch = [{'path': '/physical_network', 'op': 'remove'}]
        self._test_physical_network_old_api_version(mock_upd, patch,
                                                    'physnet1')

    @mock.patch.object(objects.Port, 'supports_physical_network')
    def _test_physical_network_upgrade(self, mock_upd, patch,
                                       expected_physical_network, mock_spn):
        # Helper to test an update to a port's physical network that is
        # expected to fail at API version 1.34 while the API service is pinned
        # to the Ocata release.
        mock_spn.return_value = False
        self._test_old_api_version(mock_upd, patch, '1.34')

        self.port.refresh()
        self.assertEqual(expected_physical_network, self.port.physical_network)

    def test_add_physical_network_upgrade(self, mock_upd):
        patch = [{'path': '/physical_network',
                  'value': 'physnet1',
                  'op': 'add'}]
        self._test_physical_network_upgrade(mock_upd, patch, None)

    def test_replace_physical_network_upgrade(self, mock_upd):
        self.port.physical_network = 'physnet1'
        self.port.save()
        patch = [{'path': '/physical_network',
                  'value': 'physnet2',
                  'op': 'replace'}]
        self._test_physical_network_upgrade(mock_upd, patch, 'physnet1')

    def test_remove_physical_network_upgrade(self, mock_upd):
        self.port.physical_network = 'physnet1'
        self.port.save()
        patch = [{'path': '/physical_network', 'op': 'remove'}]
        self._test_physical_network_upgrade(mock_upd, patch, 'physnet1')

    def test_invalid_physnet_non_text(self, mock_upd):
        physnet = 1234
        headers = {api_base.Version.string: versions.max_version_string()}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/physical_network',
                                     'value': physnet,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('should be string', response.json['error_message'])

    def test_invalid_physnet_too_long(self, mock_upd):
        physnet = 'p' * 65
        headers = {api_base.Version.string: versions.max_version_string()}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/physical_network',
                                     'value': physnet,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('maximum character', response.json['error_message'])

    def test_invalid_physnet_empty_string(self, mock_upd):
        physnet = ''
        headers = {api_base.Version.string: versions.max_version_string()}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/physical_network',
                                     'value': physnet,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('non-empty value', response.json['error_message'])

    def test_portgroups_subresource_patch(self, mock_upd):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          portgroup_id=portgroup.id,
                                          address='52:55:00:cf:2d:31')
        headers = {api_base.Version.string: '1.24'}
        response = self.patch_json(
            '/portgroups/%(portgroup)s/ports/%(port)s' %
            {'portgroup': portgroup.uuid, 'port': port.uuid},
            [{'path': '/address', 'value': '00:00:00:00:00:00',
              'op': 'replace'}], headers=headers, expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
        self.assertEqual('application/json', response.content_type)

    def _test_add_extra_vif_port_id(self, port, headers, mock_warn, mock_upd):
        response = self.patch_json(
            '/ports/%s' % port.uuid,
            [{'path': '/extra/vif_port_id', 'value': 'foo', 'op': 'add'},
             {'path': '/extra/vif_port_id', 'value': 'bar', 'op': 'add'}],
            headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual({'vif_port_id': 'bar'},
                         response.json['extra'])
        self.assertTrue(mock_upd.called)
        return response

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_add_extra_vif_port_id(self, mock_warn, mock_upd):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31')
        expected_intern_info = port.internal_info
        expected_intern_info.update({'tenant_vif_port_id': 'bar'})
        headers = {api_base.Version.string: '1.27'}
        response = self._test_add_extra_vif_port_id(port, headers,
                                                    mock_warn, mock_upd)
        self.assertEqual(expected_intern_info, response.json['internal_info'])
        self.assertFalse(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_add_extra_vif_port_id_no_internal(self, mock_warn, mock_upd):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31')
        expected_intern_info = port.internal_info
        expected_intern_info.update({'tenant_vif_port_id': 'bar'})
        headers = {api_base.Version.string: '1.27'}
        response = self._test_add_extra_vif_port_id(port, headers,
                                                    mock_warn, mock_upd)
        self.assertEqual(expected_intern_info, response.json['internal_info'])
        self.assertFalse(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_add_extra_vif_port_id_deprecated(self, mock_warn, mock_upd):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31')
        expected_intern_info = port.internal_info
        expected_intern_info.update({'tenant_vif_port_id': 'bar'})
        headers = {api_base.Version.string: '1.34'}
        response = self._test_add_extra_vif_port_id(port, headers,
                                                    mock_warn, mock_upd)
        self.assertEqual(expected_intern_info, response.json['internal_info'])
        self.assertTrue(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_replace_extra_vif_port_id(self, mock_warn, mock_upd):
        extra = {'vif_port_id': 'original'}
        internal_info = {'tenant_vif_port_id': 'original'}
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31',
                                          extra=extra,
                                          internal_info=internal_info)
        expected_intern_info = port.internal_info
        expected_intern_info.update({'tenant_vif_port_id': 'bar'})
        headers = {api_base.Version.string: '1.27'}
        response = self._test_add_extra_vif_port_id(port, headers,
                                                    mock_warn, mock_upd)
        self.assertEqual(expected_intern_info, response.json['internal_info'])
        self.assertFalse(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_add_extra_vif_port_id_diff_internal(self, mock_warn, mock_upd):
        internal_info = {'tenant_vif_port_id': 'original'}
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31',
                                          internal_info=internal_info)
        headers = {api_base.Version.string: '1.27'}
        response = self._test_add_extra_vif_port_id(port, headers,
                                                    mock_warn, mock_upd)
        self.assertEqual(internal_info, response.json['internal_info'])
        self.assertFalse(mock_warn.called)

    def _test_remove_extra_vif_port_id(self, port, headers, mock_warn,
                                       mock_upd):
        response = self.patch_json(
            '/ports/%s' % port.uuid,
            [{'path': '/extra/vif_port_id', 'op': 'remove'}],
            headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual({}, response.json['extra'])
        self.assertTrue(mock_upd.called)
        return response

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_remove_extra_vif_port_id(self, mock_warn, mock_upd):
        internal_info = {'tenant_vif_port_id': 'bar'}
        extra = {'vif_port_id': 'bar'}
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31',
                                          internal_info=internal_info,
                                          extra=extra)
        headers = {api_base.Version.string: '1.27'}
        response = self._test_remove_extra_vif_port_id(port, headers,
                                                       mock_warn, mock_upd)
        self.assertEqual({}, response.json['internal_info'])
        self.assertFalse(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_remove_extra_vif_port_id_not_same(self, mock_warn, mock_upd):
        # .internal_info['tenant_vif_port_id'] != .extra['vif_port_id']
        internal_info = {'tenant_vif_port_id': 'bar'}
        extra = {'vif_port_id': 'foo'}
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31',
                                          internal_info=internal_info,
                                          extra=extra)
        headers = {api_base.Version.string: '1.28'}
        response = self._test_remove_extra_vif_port_id(port, headers,
                                                       mock_warn, mock_upd)
        self.assertEqual(internal_info, response.json['internal_info'])
        self.assertTrue(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_remove_extra_vif_port_id_not_internal(self, mock_warn, mock_upd):
        # no .internal_info['tenant_vif_port_id']
        internal_info = {'foo': 'bar'}
        extra = {'vif_port_id': 'bar'}
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          address='52:55:00:cf:2d:31',
                                          internal_info=internal_info,
                                          extra=extra)
        headers = {api_base.Version.string: '1.28'}
        response = self._test_remove_extra_vif_port_id(port, headers,
                                                       mock_warn, mock_upd)
        self.assertEqual(internal_info, response.json['internal_info'])
        self.assertTrue(mock_warn.called)

    def test_update_in_inspecting_not_allowed(self, mock_upd):
        self.node.provision_state = states.INSPECTING
        self.node.save()
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers={api_base.Version.string: "1.39"},
                                   expect_errors=True)
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_update_in_inspecting_allowed(self, mock_upd):
        self.node.provision_state = states.INSPECTING
        self.node.save()
        extra = {'foo': 'bar'}
        response = self.patch_json('/ports/%s' % self.port.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers={api_base.Version.string: "1.38"})
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        self.assertTrue(mock_upd.called)


@mock.patch.object(rpcapi.ConductorAPI, 'create_port', autospec=True,
                   side_effect=_rpcapi_create_port)
class TestPost(test_api_base.BaseApiTest):

    def setUp(self):
        super(TestPost, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.portgroup = obj_utils.create_test_portgroup(self.context,
                                                         node_id=self.node.id)
        self.headers = {api_base.Version.string: str(
            versions.max_version_string())}

        p = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = p.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(p.stop)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(timeutils, 'utcnow')
    def test_create_port(self, mock_utcnow, mock_notify, mock_warn,
                         mock_create):
        pdict = post_get_test_port()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/ports/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/ports/%s' % pdict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=self.portgroup.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=self.portgroup.uuid)])
        self.assertEqual(0, mock_warn.call_count)

    def test_create_port_min_api_version(self, mock_create):
        pdict = post_get_test_port(
            node_uuid=self.node.uuid)
        pdict.pop('local_link_connection')
        pdict.pop('pxe_enabled')
        pdict.pop('extra')
        pdict.pop('physical_network')
        pdict.pop('is_smartnic')
        headers = {api_base.Version.string: str(api_v1.min_version())}
        response = self.post_json('/ports', pdict, headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(self.node.uuid, response.json['node_uuid'])
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_doesnt_contain_id(self, mock_create):
        with mock.patch.object(self.dbapi, 'create_port',
                               wraps=self.dbapi.create_port) as cp_mock:
            pdict = post_get_test_port(extra={'foo': 123})
            self.post_json('/ports', pdict, headers=self.headers)
            result = self.get_json('/ports/%s' % pdict['uuid'],
                                   headers=self.headers)
            self.assertEqual(pdict['extra'], result['extra'])
            cp_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args
            self.assertNotIn('id', cp_mock.call_args[0][0])
            mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                                'test-topic')

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_port_generate_uuid(self, mock_warning, mock_exception,
                                       mock_create):
        pdict = post_get_test_port()
        del pdict['uuid']
        response = self.post_json('/ports', pdict, headers=self.headers)
        result = self.get_json('/ports/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['address'], result['address'])
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warning.called)
        self.assertFalse(mock_exception.called)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_create_port_error(self, mock_notify, mock_create):
        mock_create.side_effect = Exception()
        pdict = post_get_test_port()
        self.post_json('/ports', pdict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=self.portgroup.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=self.portgroup.uuid)])
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_valid_extra(self, mock_create):
        pdict = post_get_test_port(extra={'str': 'foo', 'int': 123,
                                          'float': 0.1, 'bool': True,
                                          'list': [1, 2], 'none': None,
                                          'dict': {'cat': 'meow'}})
        self.post_json('/ports', pdict, headers=self.headers)
        result = self.get_json('/ports/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['extra'], result['extra'])
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_no_mandatory_field_address(self, mock_create):
        pdict = post_get_test_port()
        del pdict['address']
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_no_mandatory_field_node_uuid(self, mock_create):
        pdict = post_get_test_port()
        del pdict['node_uuid']
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_invalid_addr_format(self, mock_create):
        pdict = post_get_test_port(address='invalid-format')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_address_normalized(self, mock_create):
        address = 'AA:BB:CC:DD:EE:FF'
        pdict = post_get_test_port(address=address)
        self.post_json('/ports', pdict, headers=self.headers)
        result = self.get_json('/ports/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(address.lower(), result['address'])
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_with_hyphens_delimiter(self, mock_create):
        pdict = post_get_test_port()
        colonsMAC = pdict['address']
        hyphensMAC = colonsMAC.replace(':', '-')
        pdict['address'] = hyphensMAC
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_invalid_node_uuid_format(self, mock_create):
        pdict = post_get_test_port(node_uuid='invalid-format')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_node_uuid_to_node_id_mapping(self, mock_create):
        pdict = post_get_test_port(node_uuid=self.node['uuid'])
        self.post_json('/ports', pdict, headers=self.headers)
        # GET doesn't return the node_id it's an internal value
        port = self.dbapi.get_port_by_uuid(pdict['uuid'])
        self.assertEqual(self.node['id'], port.node_id)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_node_uuid_not_found(self, mock_create):
        pdict = post_get_test_port(
            node_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_portgroup_uuid_not_found(self, mock_create):
        pdict = post_get_test_port(
            portgroup_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_portgroup_uuid_not_found_old_api_version(self,
                                                                  mock_create):
        pdict = post_get_test_port(
            portgroup_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_portgroup(self, mock_create):
        pdict = post_get_test_port(
            portgroup_uuid=self.portgroup.uuid,
            node_uuid=self.node.uuid)

        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_portgroup_different_nodes(self, mock_create):
        pdict = post_get_test_port(
            portgroup_uuid=self.portgroup.uuid,
            node_uuid=uuidutils.generate_uuid())

        response = self.post_json('/ports', pdict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_portgroup_old_api_version(self, mock_create):
        pdict = post_get_test_port(
            portgroup_uuid=self.portgroup.uuid,
            node_uuid=self.node.uuid
        )
        headers = {api_base.Version.string: '1.15'}
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_create_port_address_already_exist(self, mock_notify, mock_create):
        address = 'AA:AA:AA:11:22:33'
        mock_create.side_effect = exception.MACAlreadyExists(mac=address)
        pdict = post_get_test_port(address=address, node_id=self.node.id)
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.CONFLICT, response.status_int)
        self.assertEqual('application/json', response.content_type)
        error_msg = response.json['error_message']
        self.assertTrue(error_msg)
        self.assertIn(address, error_msg.upper())
        self.assertTrue(mock_create.called)

        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=pdict['portgroup_uuid']),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=pdict['portgroup_uuid'])])

    def test_create_port_with_internal_field(self, mock_create):
        pdict = post_get_test_port()
        pdict['internal_info'] = {'a': 'b'}
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_some_invalid_local_link_connection_key(self,
                                                                mock_create):
        pdict = post_get_test_port(
            local_link_connection={'switch_id': 'value1',
                                   'port_id': 'Ethernet1/15',
                                   'switch_foo': 'value3'})
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_local_link_connection_keys(self, mock_create):
        pdict = post_get_test_port(
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:5f',
                                   'port_id': 'Ethernet1/15',
                                   'switch_info': 'value3'})
        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_local_link_connection_switch_id_bad_mac(self,
                                                                 mock_create):
        pdict = post_get_test_port(
            local_link_connection={'switch_id': 'zz:zz:zz:zz:zz:zz',
                                   'port_id': 'Ethernet1/15',
                                   'switch_info': 'value3'})
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_local_link_connection_missing_mandatory(self,
                                                                 mock_create):
        pdict = post_get_test_port(
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:5f',
                                   'switch_info': 'fooswitch'})
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_local_link_connection_missing_optional(self,
                                                                mock_create):
        pdict = post_get_test_port(
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:5f',
                                   'port_id': 'Ethernet1/15'})
        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_with_llc_old_api_version(self, mock_create):
        headers = {api_base.Version.string: '1.14'}
        pdict = post_get_test_port(
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:5f',
                                   'port_id': 'Ethernet1/15'})
        response = self.post_json('/ports', pdict, headers=headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_with_network_type_in_llc(self, mock_create):
        pdict = post_get_test_port(
            local_link_connection={'network_type': 'unmanaged'})
        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    def test_create_port_with_network_type_in_llc_old_api_version(
            self, mock_create):
        headers = {api_base.Version.string: '1.63'}
        pdict = post_get_test_port(
            local_link_connection={'network_type': 'unmanaged'})
        response = self.post_json('/ports', pdict, headers=headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_with_pxe_enabled_old_api_version(self, mock_create):
        headers = {api_base.Version.string: '1.14'}
        pdict = post_get_test_port(pxe_enabled=False)
        del pdict['local_link_connection']
        del pdict['portgroup_uuid']
        response = self.post_json('/ports', pdict, headers=headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_with_physical_network(self, mock_create):
        physical_network = 'physnet1'
        pdict = post_get_test_port(
            physical_network=physical_network,
            node_uuid=self.node.uuid)

        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')
        self.assertEqual(physical_network, response.json['physical_network'])
        port = objects.Port.get(self.context, pdict['uuid'])
        self.assertEqual(physical_network, port.physical_network)

    def test_create_port_with_physical_network_old_api_version(self,
                                                               mock_create):
        headers = {api_base.Version.string: '1.33'}
        pdict = post_get_test_port(physical_network='physnet1')
        response = self.post_json('/ports', pdict, headers=headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    @mock.patch.object(objects.Port, 'supports_physical_network')
    def test_create_port_with_physical_network_upgrade(self, mock_spn,
                                                       mock_create):
        mock_spn.return_value = False
        pdict = post_get_test_port(physical_network='physnet1')
        response = self.post_json('/ports', pdict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    def test_portgroups_subresource_post(self, mock_create):
        headers = {api_base.Version.string: '1.24'}
        pdict = post_get_test_port()
        response = self.post_json('/portgroups/%s/ports' % self.portgroup.uuid,
                                  pdict, headers=headers, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
        self.assertFalse(mock_create.called)

    def _test_create_port_with_extra_vif_port_id(self, headers, mock_warn,
                                                 mock_create):
        pdict = post_get_test_port(pxe_enabled=False,
                                   extra={'vif_port_id': 'foo'})
        pdict.pop('physical_network')
        pdict.pop('is_smartnic')
        response = self.post_json('/ports', pdict, headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual({'vif_port_id': 'foo'}, response.json['extra'])
        self.assertEqual({'tenant_vif_port_id': 'foo'},
                         response.json['internal_info'])
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_create_port_with_extra_vif_port_id(self, mock_warn, mock_create):
        headers = {api_base.Version.string: '1.27'}
        self._test_create_port_with_extra_vif_port_id(headers, mock_warn,
                                                      mock_create)
        self.assertFalse(mock_warn.called)

    @mock.patch.object(common_utils, 'warn_about_deprecated_extra_vif_port_id',
                       autospec=True)
    def test_create_port_with_extra_vif_port_id_deprecated(self, mock_warn,
                                                           mock_create):
        self._test_create_port_with_extra_vif_port_id(self.headers, mock_warn,
                                                      mock_create)
        self.assertTrue(mock_warn.called)

    def _test_create_port(self, mock_create, has_vif=False, in_portgroup=False,
                          pxe_enabled=True, standalone_ports=True,
                          http_status=http_client.CREATED):
        extra = {}
        if has_vif:
            extra = {'vif_port_id': uuidutils.generate_uuid()}
        pdict = post_get_test_port(
            node_uuid=self.node.uuid,
            pxe_enabled=pxe_enabled,
            extra=extra)

        if not in_portgroup:
            pdict.pop('portgroup_uuid')
        else:
            self.portgroup.standalone_ports_supported = standalone_ports
            self.portgroup.save()

        expect_errors = http_status != http_client.CREATED

        response = self.post_json('/ports', pdict, headers=self.headers,
                                  expect_errors=expect_errors)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_status, response.status_int)
        if not expect_errors:
            expected_portgroup_uuid = pdict.get('portgroup_uuid', None)
            self.assertEqual(expected_portgroup_uuid,
                             response.json['portgroup_uuid'])
            self.assertEqual(extra, response.json['extra'])
            if has_vif:
                expected = {'tenant_vif_port_id': extra['vif_port_id']}
                self.assertEqual(expected, response.json['internal_info'])
            mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                                'test-topic')
        else:
            self.assertFalse(mock_create.called)

    def test_create_port_novif_pxe_noportgroup(self, mock_create):
        self._test_create_port(mock_create, has_vif=False, in_portgroup=False,
                               pxe_enabled=True,
                               http_status=http_client.CREATED)

    def test_create_port_novif_nopxe_noportgroup(self, mock_create):
        self._test_create_port(mock_create, has_vif=False, in_portgroup=False,
                               pxe_enabled=False,
                               http_status=http_client.CREATED)

    def test_create_port_vif_pxe_noportgroup(self, mock_create):
        self._test_create_port(mock_create, has_vif=True, in_portgroup=False,
                               pxe_enabled=True,
                               http_status=http_client.CREATED)

    def test_create_port_vif_nopxe_noportgroup(self, mock_create):
        self._test_create_port(mock_create, has_vif=True, in_portgroup=False,
                               pxe_enabled=False,
                               http_status=http_client.CREATED)

    def test_create_port_novif_pxe_portgroup_standalone_ports(self,
                                                              mock_create):
        self._test_create_port(mock_create, has_vif=False, in_portgroup=True,
                               pxe_enabled=True,
                               standalone_ports=True,
                               http_status=http_client.CREATED)

    def test_create_port_novif_pxe_portgroup_nostandalone_ports(self,
                                                                mock_create):
        self._test_create_port(mock_create, has_vif=False, in_portgroup=True,
                               pxe_enabled=True,
                               standalone_ports=False,
                               http_status=http_client.CONFLICT)

    def test_create_port_novif_nopxe_portgroup_standalone_ports(self,
                                                                mock_create):
        self._test_create_port(mock_create, has_vif=False, in_portgroup=True,
                               pxe_enabled=False,
                               standalone_ports=True,
                               http_status=http_client.CREATED)

    def test_create_port_novif_nopxe_portgroup_nostandalone_ports(self,
                                                                  mock_create):
        self._test_create_port(mock_create, has_vif=False, in_portgroup=True,
                               pxe_enabled=False,
                               standalone_ports=False,
                               http_status=http_client.CREATED)

    def test_create_port_vif_pxe_portgroup_standalone_ports(self, mock_create):
        self._test_create_port(mock_create, has_vif=True, in_portgroup=True,
                               pxe_enabled=True,
                               standalone_ports=True,
                               http_status=http_client.CREATED)

    def test_create_port_vif_pxe_portgroup_nostandalone_ports(self,
                                                              mock_create):
        self._test_create_port(mock_create, has_vif=True, in_portgroup=True,
                               pxe_enabled=True,
                               standalone_ports=False,
                               http_status=http_client.CONFLICT)

    def test_create_port_vif_nopxe_portgroup_standalone_ports(self,
                                                              mock_create):
        self._test_create_port(mock_create, has_vif=True, in_portgroup=True,
                               pxe_enabled=False,
                               standalone_ports=True,
                               http_status=http_client.CREATED)

    def test_create_port_vif_nopxe_portgroup_nostandalone_ports(self,
                                                                mock_create):
        self._test_create_port(mock_create, has_vif=True, in_portgroup=True,
                               pxe_enabled=False,
                               standalone_ports=False,
                               http_status=http_client.CONFLICT)

    def test_create_port_invalid_physnet_non_text(self, mock_create):
        physnet = 1234
        pdict = post_get_test_port(physical_network=physnet)
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('should be string', response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_invalid_physnet_too_long(self, mock_create):
        physnet = 'p' * 65
        pdict = post_get_test_port(physical_network=physnet)
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('maximum character', response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_invalid_physnet_empty_string(self, mock_create):
        physnet = ''
        pdict = post_get_test_port(physical_network=physnet)
        response = self.post_json('/ports', pdict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn('non-empty value', response.json['error_message'])
        self.assertFalse(mock_create.called)

    def test_create_port_with_is_smartnic(self, mock_create):
        llc = {'hostname': 'host1', 'port_id': 'rep0-0'}
        pdict = post_get_test_port(is_smartnic=True, node_uuid=self.node.uuid,
                                   local_link_connection=llc)
        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')
        self.assertTrue(response.json['is_smartnic'])
        port = objects.Port.get(self.context, pdict['uuid'])
        self.assertTrue(port.is_smartnic)

    def test_create_port_with_is_smartnic_default_value(self, mock_create):
        pdict = post_get_test_port(node_uuid=self.node.uuid)
        response = self.post_json('/ports', pdict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        mock_create.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                            'test-topic')
        self.assertFalse(response.json['is_smartnic'])
        port = objects.Port.get(self.context, pdict['uuid'])
        self.assertFalse(port.is_smartnic)

    def test_create_port_with_is_smartnic_old_api_version(self, mock_create):
        pdict = post_get_test_port(is_smartnic=True, node_uuid=self.node.uuid)
        headers = {api_base.Version.string: '1.52'}
        response = self.post_json('/ports', pdict,
                                  headers=headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_with_is_smartnic_missing_hostname(self, mock_create):
        llc = {'switch_info': 'switch',
               'switch_id': 'aa:bb:cc:dd:ee:ff',
               'port_id': 'Gig0/1'}
        pdict = post_get_test_port(is_smartnic=True,
                                   node_uuid=self.node.uuid,
                                   local_link_connection=llc)
        response = self.post_json('/ports', pdict,
                                  headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertFalse(mock_create.called)

    def test_create_port_with_is_smartnic_missing_port_id(self, mock_create):
        llc = {'switch_info': 'switch',
               'switch_id': 'aa:bb:cc:dd:ee:ff',
               'hostname': 'host'}
        pdict = post_get_test_port(is_smartnic=True,
                                   node_uuid=self.node.uuid,
                                   local_link_connection=llc)
        response = self.post_json('/ports', pdict,
                                  headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertFalse(mock_create.called)


@mock.patch.object(rpcapi.ConductorAPI, 'destroy_port')
class TestDelete(test_api_base.BaseApiTest):

    def setUp(self):
        super(TestDelete, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)

        gtf = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = gtf.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(gtf.stop)

    def test_delete_port_byaddress(self, mock_dpt):
        response = self.delete('/ports/%s' % self.port.address,
                               expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(self.port.address, response.json['error_message'])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_port_byid(self, mock_notify, mock_dpt):
        self.delete('/ports/%s' % self.port.uuid, expect_errors=True)
        self.assertTrue(mock_dpt.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=None),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=None)])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_port_node_locked(self, mock_notify, mock_dpt):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_dpt.side_effect = exception.NodeLocked(node='fake-node',
                                                    host='fake-host')
        ret = self.delete('/ports/%s' % self.port.uuid, expect_errors=True)
        self.assertEqual(http_client.CONFLICT, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_dpt.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=None),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid,
                                      portgroup_uuid=None)])

    def test_portgroups_subresource_delete(self, mock_dpt):
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          uuid=uuidutils.generate_uuid(),
                                          portgroup_id=portgroup.id,
                                          address='52:55:00:cf:2d:31')
        headers = {api_base.Version.string: '1.24'}
        response = self.delete(
            '/portgroups/%(portgroup)s/ports/%(port)s' %
            {'portgroup': portgroup.uuid, 'port': port.uuid},
            headers=headers, expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
        self.assertEqual('application/json', response.content_type)
