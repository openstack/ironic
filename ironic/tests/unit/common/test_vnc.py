#   Copyright 2025 Red Hat, Inc.
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

from oslo_config import cfg
from oslo_utils import timeutils

from ironic.common import exception
from ironic.common import vnc as vnc_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class VncTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VncTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_novnc_authorize(self):
        then = timeutils.utcnow()

        vnc_utils.novnc_authorize(self.node)

        # assert token and timestamp were created
        self.assertIsNotNone(
            self.node.driver_internal_info['novnc_secret_token'])
        created = self.node.driver_internal_info['novnc_secret_token_created']
        self.assertIsNotNone(created)
        created_dt = datetime.datetime.strptime(created,
                                                '%Y-%m-%dT%H:%M:%S.%f')
        self.assertLessEqual(then, created_dt)

    def test_novnc_unauthorize(self):
        vnc_utils.novnc_authorize(self.node)
        self.assertIn('novnc_secret_token', self.node.driver_internal_info)
        self.assertIn('novnc_secret_token_created',
                      self.node.driver_internal_info)

        vnc_utils.novnc_unauthorize(self.node)

        # assert token and timestamp were removed
        self.assertNotIn('novnc_secret_token', self.node.driver_internal_info)
        self.assertNotIn('novnc_secret_token_created',
                         self.node.driver_internal_info)

    def test_novnc_validate(self):

        vnc_utils.novnc_authorize(self.node)
        token = self.node.driver_internal_info['novnc_secret_token']

        # assert successful validate
        self.assertIsNone(vnc_utils.novnc_validate(self.node, token))

        # assert wrong token
        self.assertRaises(exception.NotAuthorized, vnc_utils.novnc_validate,
                          self.node, 'wrong token')

        vnc_utils.novnc_unauthorize(self.node)
        # assert unauthorized
        self.assertRaises(exception.NotAuthorized, vnc_utils.novnc_validate,
                          self.node, token)

    def test_novnc_validate_expired(self):

        vnc_utils.novnc_authorize(self.node)
        token = self.node.driver_internal_info['novnc_secret_token']

        # assert successful validate
        self.assertIsNone(vnc_utils.novnc_validate(self.node, token))

        # set the created date to one second before the timeout
        now = timeutils.utcnow()
        timeout = CONF.vnc.token_timeout
        time_delta = datetime.timedelta(seconds=timeout + 1)
        then = now - time_delta
        self.node.set_driver_internal_info('novnc_secret_token_created',
                                           then.isoformat())

        # assert expired token
        self.assertRaises(exception.NotAuthorized, vnc_utils.novnc_validate,
                          self.node, token)

    def test_token_valid_until(self):
        now = timeutils.utcnow()
        self.node.set_driver_internal_info('novnc_secret_token_created',
                                           now.isoformat())
        timeout = CONF.vnc.token_timeout
        time_delta = datetime.timedelta(seconds=timeout)

        # assert that the valid until date is exactly timeout after now
        self.assertEqual(now + time_delta,
                         vnc_utils.token_valid_until(self.node))

    def test_get_console(self):
        self.node.set_driver_internal_info('novnc_secret_token', 'asdf')
        uuid = self.node.uuid
        CONF.set_override('public_url', 'http://192.0.2.1:6090/vnc_auto.html',
                          group='vnc')

        # assert expected console URL
        self.assertEqual({
            'type': 'vnc',
            'url': 'http://192.0.2.1:6090/vnc_auto.html?'
                   f'path=websockify%3Fnode%3D{uuid}%26token%3Dasdf'
        }, vnc_utils.get_console(self.node))
