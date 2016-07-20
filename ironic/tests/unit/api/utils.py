# -*- encoding: utf-8 -*-
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
"""
Utils for testing the API service.
"""

import datetime
import hashlib
import json

from ironic.api.controllers.v1 import chassis as chassis_controller
from ironic.api.controllers.v1 import node as node_controller
from ironic.api.controllers.v1 import port as port_controller
from ironic.tests.unit.db import utils

ADMIN_TOKEN = '4562138218392831'
MEMBER_TOKEN = '4562138218392832'

ADMIN_TOKEN_HASH = hashlib.sha256(ADMIN_TOKEN.encode()).hexdigest()
MEMBER_TOKEN_HASH = hashlib.sha256(MEMBER_TOKEN.encode()).hexdigest()

ADMIN_BODY = {
    'access': {
        'token': {'id': ADMIN_TOKEN,
                  'expires': '2100-09-11T00:00:00'},
        'user': {'id': 'user_id1',
                 'name': 'user_name1',
                 'tenantId': '123i2910',
                 'tenantName': 'mytenant',
                 'roles': [{'name': 'admin'}]},
    }
}

MEMBER_BODY = {
    'access': {
        'token': {'id': MEMBER_TOKEN,
                  'expires': '2100-09-11T00:00:00'},
        'user': {'id': 'user_id2',
                 'name': 'user-good',
                 'tenantId': 'project-good',
                 'tenantName': 'goodies',
                 'roles': [{'name': 'Member'}]},
    }
}


class FakeMemcache(object):
    """Fake cache that is used for keystone tokens lookup."""

    # NOTE(lucasagomes): keystonemiddleware >= 2.0.0 the token cache
    # keys are sha256 hashes of the token key. This was introduced in
    # https://review.openstack.org/#/c/186971
    _cache = {
        'tokens/%s' % ADMIN_TOKEN: ADMIN_BODY,
        'tokens/%s' % ADMIN_TOKEN_HASH: ADMIN_BODY,
        'tokens/%s' % MEMBER_TOKEN: MEMBER_BODY,
        'tokens/%s' % MEMBER_TOKEN_HASH: MEMBER_BODY,
    }

    def __init__(self):
        self.set_key = None
        self.set_value = None
        self.token_expiration = None

    def get(self, key):
        dt = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
        return json.dumps((self._cache.get(key), dt.isoformat()))

    def set(self, key, value, time=0, min_compress_len=0):
        self.set_value = value
        self.set_key = key


def remove_internal(values, internal):
    # NOTE(yuriyz): internal attributes should not be posted, except uuid
    int_attr = [attr.lstrip('/') for attr in internal if attr != '/uuid']
    return {k: v for (k, v) in values.items() if k not in int_attr}


def node_post_data(**kw):
    node = utils.get_test_node(**kw)
    # These values are not part of the API object
    node.pop('conductor_affinity')
    node.pop('chassis_id')
    node.pop('tags')

    # NOTE(jroll): pop out fields that were introduced in later API versions,
    # unless explicitly requested. Otherwise, these will cause tests using
    # older API versions to fail.
    if 'network_interface' not in kw:
        node.pop('network_interface')
    if 'resource_class' not in kw:
        node.pop('resource_class')

    internal = node_controller.NodePatchType.internal_attrs()
    return remove_internal(node, internal)


def port_post_data(**kw):
    port = utils.get_test_port(**kw)
    # node_id is not part of the API object
    port.pop('node_id')
    # portgroup_id is not part of the API object
    port.pop('portgroup_id')
    internal = port_controller.PortPatchType.internal_attrs()
    return remove_internal(port, internal)


def chassis_post_data(**kw):
    chassis = utils.get_test_chassis(**kw)
    internal = chassis_controller.ChassisPatchType.internal_attrs()
    return remove_internal(chassis, internal)


def post_get_test_node(**kw):
    # NOTE(lucasagomes): When creating a node via API (POST)
    #                    we have to use chassis_uuid
    node = node_post_data(**kw)
    chassis = utils.get_test_chassis()
    node['chassis_uuid'] = kw.get('chassis_uuid', chassis['uuid'])
    return node
