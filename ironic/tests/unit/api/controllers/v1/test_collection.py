# Copyright 2020 Red Hat, Inc.
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

from unittest import mock

from oslo_utils import uuidutils

from ironic import api
from ironic.api.controllers.v1 import collection
from ironic.tests import base


class TestCollection(base.TestCase):

    def setUp(self):
        super(TestCollection, self).setUp()
        p = mock.patch.object(api, 'request', autospec=False)
        mock_req = p.start()
        mock_req.public_url = 'http://192.0.2.1:5050'
        self.addCleanup(p.stop)

    def test_has_next(self):
        self.assertFalse(collection.has_next([], 5))
        self.assertFalse(collection.has_next([1, 2, 3], 5))
        self.assertFalse(collection.has_next([1, 2, 3, 4], 5))
        self.assertTrue(collection.has_next([1, 2, 3, 4, 5], 5))

    def test_list_convert_with_links(self):
        col = self._generate_collection(3)

        # build with next link
        result = collection.list_convert_with_links(
            col, 'things', 3, url='thing')
        self.assertEqual({
            'things': col,
            'next': 'http://192.0.2.1:5050/v1/thing?limit=3&'
                    'marker=%s' % col[2]['uuid']
        }, result)

        # build without next link
        result = collection.list_convert_with_links(
            col, 'things', 5, url='thing')
        self.assertEqual({'things': col}, result)

        # build with a custom sanitize function
        def sanitize(item, fields):
            item.pop('name')

        result = collection.list_convert_with_links(
            col, 'things', 5, url='thing', sanitize_func=sanitize)
        self.assertEqual({
            'things': [
                {'uuid': col[0]['uuid']},
                {'uuid': col[1]['uuid']},
                {'uuid': col[2]['uuid']}
            ]
        }, result)
        # items in the original collection are also sanitized
        self.assertEqual(col, result['things'])

    def _generate_collection(self, length, key_field='uuid'):
        return [{
            key_field: uuidutils.generate_uuid(),
            'name': 'thing-%s' % i}
            for i in range(length)]

    def test_get_next(self):
        col = self._generate_collection(3)

        # build next URL, marker is the last item uuid
        self.assertEqual(
            'http://192.0.2.1:5050/v1/foo?limit=3&marker=%s' % col[-1]['uuid'],
            collection.get_next(col, 3, 'foo'))

        # no next URL, return None
        self.assertIsNone(collection.get_next(col, 4, 'foo'))

        # build next URL, fields and other keyword args included in the url
        self.assertEqual(
            'http://192.0.2.1:5050/v1/foo?bar=baz&fields=uuid,one,two&'
            'limit=3&marker=%s' % col[-1]['uuid'],
            collection.get_next(col, 3, 'foo', fields=['uuid', 'one', 'two'],
                                bar='baz'))

        # build next URL, use alternate sort key
        col = self._generate_collection(3, key_field='identifier')
        self.assertEqual(
            'http://192.0.2.1:5050/v1/foo?limit=3&'
            'marker=%s' % col[-1]['identifier'],
            collection.get_next(col, 3, 'foo', key_field='identifier'))
