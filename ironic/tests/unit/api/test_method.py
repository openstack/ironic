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

from http import client as http_client
import json

import pecan.rest
import pecan.testing

from ironic import api
from ironic.api.controllers import root
from ironic.api.controllers import v1
from ironic.api import method
from ironic.api import types as atypes
from ironic.common import args
from ironic.tests.unit.api import base as test_api_base


class MyThingController(pecan.rest.RestController):

    _custom_actions = {
        'no_content': ['GET'],
        'response_content': ['GET'],
        'response_custom_status': ['GET'],
        'ouch': ['GET'],
    }

    @method.expose()
    @args.validate(name=args.string, flag=args.boolean)
    def get(self, name, flag):
        return {name: flag}

    @method.expose()
    def no_content(self):
        api.response.status_code = 204
        return 'nothing'

    @method.expose()
    def response_content(self):
        resp = atypes.PassthruResponse('nothing', status_code=200)
        api.response.status_code = resp.status_code
        return resp.obj

    @method.expose(status_code=202)
    def response_custom_status(self):
        return 'accepted'

    @method.expose()
    def ouch(self):
        raise Exception('ouch')

    @method.expose(status_code=201)
    @method.body('body')
    @args.validate(body=args.schema({
        'type': 'object',
        'properties': {
            'three': {'type': 'string'},
            'four': {'type': 'string', 'maxLength': 4},
            'five': {'type': 'string'},
        },
        'additionalProperties': False,
        'required': ['three']
    }))
    def post(self, body):
        return body


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
            {'foo': True},
            self.get_json('/things', name='foo', flag=True)
        )

    def test_expose_validation(self):
        response = self.get_json('/things', name='foo', flag='truish',
                                 expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

        error = json.loads(response.json['error_message'])
        self.assertEqual('Client', error['faultcode'])
        self.assertIsNone(error['debuginfo'])
        self.assertIn("Unrecognized value 'truish'", error['faultstring'])

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

    def test_response_custom_status(self):
        response = self.get_json('/things/response_custom_status',
                                 expect_errors=True)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'"accepted"', response.normal_body)
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

    def test_post_body(self):
        data = {
            'three': 'three',
            'four': 'four',
            'five': 'five'
        }
        response = self.post_json('/things/', data, expect_errors=True)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(data, response.json)

    def test_post_body_validation(self):
        data = {
            'three': 'three',
            'four': 'fourrrr',
            'five': 'five'
        }
        response = self.post_json('/things/', data, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        error = json.loads(response.json['error_message'])
        self.assertEqual('Client', error['faultcode'])
        self.assertIsNone(error['debuginfo'])
        self.assertIn("Schema error for body:", error['faultstring'])
