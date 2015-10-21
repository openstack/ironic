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

"""Tests for manipulating NodeTags via the DB API"""

from ironic.common import exception

from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbNodeTagTestCase(base.DbTestCase):

    def setUp(self):
        super(DbNodeTagTestCase, self).setUp()
        self.node = db_utils.create_test_node()

    def test_set_node_tags(self):
        tags = self.dbapi.set_node_tags(self.node.id, ['tag1', 'tag2'])
        self.assertEqual(self.node.id, tags[0].node_id)
        self.assertItemsEqual(['tag1', 'tag2'], [tag.tag for tag in tags])

        tags = self.dbapi.set_node_tags(self.node.id, [])
        self.assertEqual([], tags)

    def test_set_node_tags_duplicate(self):
        tags = self.dbapi.set_node_tags(self.node.id,
                                        ['tag1', 'tag2', 'tag2'])
        self.assertEqual(self.node.id, tags[0].node_id)
        self.assertItemsEqual(['tag1', 'tag2'], [tag.tag for tag in tags])

    def test_set_node_tags_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.set_node_tags, '1234', ['tag1', 'tag2'])

    def test_get_node_tags_by_node_id(self):
        self.dbapi.set_node_tags(self.node.id, ['tag1', 'tag2'])
        tags = self.dbapi.get_node_tags_by_node_id(self.node.id)
        self.assertEqual(self.node.id, tags[0].node_id)
        self.assertItemsEqual(['tag1', 'tag2'], [tag.tag for tag in tags])

    def test_get_node_tags_empty(self):
        tags = self.dbapi.get_node_tags_by_node_id(self.node.id)
        self.assertEqual([], tags)

    def test_get_node_tags_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_tags_by_node_id, '123')

    def test_unset_node_tags(self):
        self.dbapi.set_node_tags(self.node.id, ['tag1', 'tag2'])
        self.dbapi.unset_node_tags(self.node.id)
        tags = self.dbapi.get_node_tags_by_node_id(self.node.id)
        self.assertEqual([], tags)

    def test_unset_empty_node_tags(self):
        self.dbapi.unset_node_tags(self.node.id)
        tags = self.dbapi.get_node_tags_by_node_id(self.node.id)
        self.assertEqual([], tags)

    def test_unset_node_tags_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.unset_node_tags, '123')

    def test_add_node_tag(self):
        tag = self.dbapi.add_node_tag(self.node.id, 'tag1')
        self.assertEqual(self.node.id, tag.node_id)
        self.assertEqual('tag1', tag.tag)

    def test_add_node_tag_duplicate(self):
        tag = self.dbapi.add_node_tag(self.node.id, 'tag1')
        tag = self.dbapi.add_node_tag(self.node.id, 'tag1')
        self.assertEqual(self.node.id, tag.node_id)
        self.assertEqual('tag1', tag.tag)

    def test_add_node_tag_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.add_node_tag, '123', 'tag1')

    def test_delete_node_tag(self):
        self.dbapi.set_node_tags(self.node.id, ['tag1', 'tag2'])
        self.dbapi.delete_node_tag(self.node.id, 'tag1')
        tags = self.dbapi.get_node_tags_by_node_id(self.node.id)
        self.assertEqual(1, len(tags))
        self.assertEqual('tag2', tags[0].tag)

    def test_delete_node_tag_not_found(self):
        self.assertRaises(exception.NodeTagNotFound,
                          self.dbapi.delete_node_tag, self.node.id, 'tag1')

    def test_delete_node_tag_node_not_found(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.delete_node_tag, '123', 'tag1')

    def test_node_tag_exists(self):
        self.dbapi.set_node_tags(self.node.id, ['tag1', 'tag2'])
        ret = self.dbapi.node_tag_exists(self.node.id, 'tag1')
        self.assertTrue(ret)

    def test_node_tag_not_exists(self):
        ret = self.dbapi.node_tag_exists(self.node.id, 'tag1')
        self.assertFalse(ret)
