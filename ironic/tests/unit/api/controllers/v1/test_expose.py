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

import datetime
from http import client as http_client
from importlib import machinery
import inspect
import json
import os
import sys
from unittest import mock

from oslo_utils import uuidutils
import pecan.rest
import pecan.testing

from ironic.api.controllers import root
from ironic.api.controllers import v1
from ironic.api import expose
from ironic.api import types as atypes
from ironic.common import exception
from ironic.tests import base as test_base
from ironic.tests.unit.api import base as test_api_base


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
        expected_calls = [
            'api_utils.check_node_policy_and_retrieve',
            'api_utils.check_list_policy',
            'api_utils.check_multiple_node_policies_and_retrieve',
            'self._get_node_and_topic',
            'api_utils.check_port_policy_and_retrieve',
            'api_utils.check_port_list_policy',
            'self._authorize_patch_and_get_node',
        ]

        for func in self.exposed_methods:
            src = inspect.getsource(func)
            self.assertTrue(
                any(call in src for call in expected_calls)
                or ('policy.authorize' in src
                    and 'context.to_policy_values' in src),
                'no policy check found in in exposed method %s' % func)

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


class UnderscoreStr(atypes.UserType):
    basetype = str
    name = "custom string"

    def tobasetype(self, value):
        return '__' + value


class Obj(atypes.Base):
    id = int
    name = str
    unset_me = str


class NestedObj(atypes.Base):
    o = Obj


class TestJsonRenderer(test_base.TestCase):

    def setUp(self):
        super(TestJsonRenderer, self).setUp()
        self.renderer = expose.JSonRenderer('/', None)

    def test_render_error(self):
        error_dict = {
            'faultcode': 500,
            'faultstring': 'ouch'
        }
        self.assertEqual(
            error_dict,
            json.loads(self.renderer.render('/', error_dict))
        )

    def test_render_exception(self):
        error_dict = {
            'faultcode': 'Server',
            'faultstring': 'ouch',
            'debuginfo': None
        }
        try:
            raise Exception('ouch')
        except Exception:
            excinfo = sys.exc_info()
            self.assertEqual(
                json.dumps(error_dict),
                self.renderer.render('/', expose.format_exception(excinfo))
            )

    def test_render_http_exception(self):
        error_dict = {
            'faultcode': '403',
            'faultstring': 'Not authorized',
            'debuginfo': None
        }
        try:
            e = exception.NotAuthorized()
            e.code = 403
        except exception.IronicException:
            excinfo = sys.exc_info()
            self.assertEqual(
                json.dumps(error_dict),
                self.renderer.render('/', expose.format_exception(excinfo))
            )

    def test_render_int(self):
        self.assertEqual(
            '42',
            self.renderer.render('/', {
                'result': 42,
                'datatype': int
            })
        )

    def test_render_none(self):
        self.assertEqual(
            'null',
            self.renderer.render('/', {
                'result': None,
                'datatype': str
            })
        )

    def test_render_str(self):
        self.assertEqual(
            '"a string"',
            self.renderer.render('/', {
                'result': 'a string',
                'datatype': str
            })
        )

    def test_render_datetime(self):
        self.assertEqual(
            '"2020-04-14T10:35:10.586431"',
            self.renderer.render('/', {
                'result': datetime.datetime(2020, 4, 14, 10, 35, 10, 586431),
                'datatype': datetime.datetime
            })
        )

    def test_render_array(self):
        self.assertEqual(
            json.dumps(['one', 'two', 'three']),
            self.renderer.render('/', {
                'result': ['one', 'two', 'three'],
                'datatype': atypes.ArrayType(str)
            })
        )

    def test_render_dict(self):
        self.assertEqual(
            json.dumps({'one': 'a', 'two': 'b', 'three': 'c'}),
            self.renderer.render('/', {
                'result': {'one': 'a', 'two': 'b', 'three': 'c'},
                'datatype': atypes.DictType(str, str)
            })
        )

    def test_complex_type(self):
        o = Obj()
        o.id = 1
        o.name = 'one'
        o.unset_me = atypes.Unset

        n = NestedObj()
        n.o = o
        self.assertEqual(
            json.dumps({'o': {'id': 1, 'name': 'one'}}),
            self.renderer.render('/', {
                'result': n,
                'datatype': NestedObj
            })
        )

    def test_user_type(self):
        self.assertEqual(
            '"__foo"',
            self.renderer.render('/', {
                'result': 'foo',
                'datatype': UnderscoreStr()
            })
        )


class MyThingController(pecan.rest.RestController):

    _custom_actions = {
        'no_content': ['GET'],
        'response_content': ['GET'],
        'ouch': ['GET'],
    }

    @expose.expose(int, str, int)
    def get(self, name, number):
        return {name: number}

    @expose.expose(str)
    def no_content(self):
        return atypes.PassthruResponse('nothing', status_code=204)

    @expose.expose(str)
    def response_content(self):
        return atypes.PassthruResponse('nothing', status_code=200)

    @expose.expose(str)
    def ouch(self):
        raise Exception('ouch')


class MyV1Controller(v1.Controller):

    things = MyThingController()


class MyRootController(root.RootController):

    v1 = MyV1Controller()


class TestExpose(test_api_base.BaseApiTest):

    block_execute = False

    root_controller = '%s.%s' % (MyRootController.__module__,
                                 MyRootController.__name__)

    def test_expose(self):
        self.assertEqual(
            {'foo': 1},
            self.get_json('/things/', name='foo', number=1)
        )

    def test_response_204(self):
        response = self.get_json('/things/no_content', expect_errors=True)
        self.assertEqual(http_client.NO_CONTENT, response.status_int)
        self.assertIsNone(response.content_type)
        self.assertEqual(b'', response.normal_body)

    def test_response_content(self):
        response = self.get_json('/things/response_content',
                                 expect_errors=True)
        self.assertEqual(http_client.OK, response.status_int)
        self.assertEqual(b'"nothing"', response.normal_body)
        self.assertEqual('application/json', response.content_type)

    def test_exception(self):
        response = self.get_json('/things/ouch',
                                 expect_errors=True)
        error_message = json.loads(response.json['error_message'])
        self.assertEqual(http_client.INTERNAL_SERVER_ERROR,
                         response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual('Server', error_message['faultcode'])
        self.assertEqual('ouch', error_message['faultstring'])
