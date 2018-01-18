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

"""Tests for manipulating NodeTraits via the DB API"""

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbNodeTraitTestCase(base.DbTestCase):

    def setUp(self):
        super(DbNodeTraitTestCase, self).setUp()
        self.node = db_utils.create_test_node()

    def test_set_node_traits(self):
        result = self.dbapi.set_node_traits(self.node.id, ['trait1', 'trait2'],
                                            '1.0')
        self.assertEqual(self.node.id, result[0].node_id)
        self.assertItemsEqual(['trait1', 'trait2'],
                              [trait.trait for trait in result])

        result = self.dbapi.set_node_traits(self.node.id, [], '1.0')
        self.assertEqual([], result)

    def test_set_node_traits_duplicate(self):
        result = self.dbapi.set_node_traits(self.node.id,
                                            ['trait1', 'trait2', 'trait2'],
                                            '1.0')
        self.assertEqual(self.node.id, result[0].node_id)
        self.assertItemsEqual(['trait1', 'trait2'],
                              [trait.trait for trait in result])

    def test_set_node_traits_at_limit(self):
        traits = ['trait%d' % n for n in range(50)]
        result = self.dbapi.set_node_traits(self.node.id, traits, '1.0')
        self.assertEqual(self.node.id, result[0].node_id)
        self.assertItemsEqual(traits, [trait.trait for trait in result])

    def test_set_node_traits_over_limit(self):
        traits = ['trait%d' % n for n in range(51)]
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.set_node_traits, self.node.id, traits,
                          '1.0')
        # Ensure the traits were not set.
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual([], result)

    def test_set_node_traits_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.set_node_traits, '1234',
                          ['trait1', 'trait2'], '1.0')

    def test_get_node_traits_by_node_id(self):
        db_utils.create_test_node_traits(node_id=self.node.id,
                                         traits=['trait1', 'trait2'])
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual(self.node.id, result[0].node_id)
        self.assertItemsEqual(['trait1', 'trait2'],
                              [trait.trait for trait in result])

    def test_get_node_traits_empty(self):
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual([], result)

    def test_get_node_traits_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_traits_by_node_id, '123')

    def test_unset_node_traits(self):
        db_utils.create_test_node_traits(node_id=self.node.id,
                                         traits=['trait1', 'trait2'])
        self.dbapi.unset_node_traits(self.node.id)
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual([], result)

    def test_unset_empty_node_traits(self):
        self.dbapi.unset_node_traits(self.node.id)
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual([], result)

    def test_unset_node_traits_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.unset_node_traits, '123')

    def test_add_node_trait(self):
        result = self.dbapi.add_node_trait(self.node.id, 'trait1', '1.0')
        self.assertEqual(self.node.id, result.node_id)
        self.assertEqual('trait1', result.trait)

    def test_add_node_trait_duplicate(self):
        self.dbapi.add_node_trait(self.node.id, 'trait1', '1.0')
        result = self.dbapi.add_node_trait(self.node.id, 'trait1', '1.0')
        self.assertEqual(self.node.id, result.node_id)
        self.assertEqual('trait1', result.trait)
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual(['trait1'], [trait.trait for trait in result])

    def test_add_node_trait_at_limit(self):
        traits = ['trait%d' % n for n in range(49)]
        db_utils.create_test_node_traits(node_id=self.node.id, traits=traits)

        result = self.dbapi.add_node_trait(self.node.id, 'trait49', '1.0')
        self.assertEqual(self.node.id, result.node_id)
        self.assertEqual('trait49', result.trait)

    def test_add_node_trait_duplicate_at_limit(self):
        traits = ['trait%d' % n for n in range(50)]
        db_utils.create_test_node_traits(node_id=self.node.id, traits=traits)

        result = self.dbapi.add_node_trait(self.node.id, 'trait49', '1.0')
        self.assertEqual(self.node.id, result.node_id)
        self.assertEqual('trait49', result.trait)

    def test_add_node_trait_over_limit(self):
        traits = ['trait%d' % n for n in range(50)]
        db_utils.create_test_node_traits(node_id=self.node.id, traits=traits)

        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.add_node_trait, self.node.id, 'trait50',
                          '1.0')
        # Ensure the trait was not added.
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertNotIn('trait50', [trait.trait for trait in result])

    def test_add_node_trait_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.add_node_trait, '123', 'trait1', '1.0')

    def test_delete_node_trait(self):
        db_utils.create_test_node_traits(node_id=self.node.id,
                                         traits=['trait1', 'trait2'])
        self.dbapi.delete_node_trait(self.node.id, 'trait1')
        result = self.dbapi.get_node_traits_by_node_id(self.node.id)
        self.assertEqual(1, len(result))
        self.assertEqual('trait2', result[0].trait)

    def test_delete_node_trait_not_found(self):
        self.assertRaises(exception.NodeTraitNotFound,
                          self.dbapi.delete_node_trait, self.node.id, 'trait1')

    def test_delete_node_trait_node_not_found(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.delete_node_trait, '123', 'trait1')

    def test_node_trait_exists(self):
        db_utils.create_test_node_traits(node_id=self.node.id,
                                         traits=['trait1', 'trait2'])
        result = self.dbapi.node_trait_exists(self.node.id, 'trait1')
        self.assertTrue(result)

    def test_node_trait_not_exists(self):
        result = self.dbapi.node_trait_exists(self.node.id, 'trait1')
        self.assertFalse(result)

    def test_node_trait_node_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.node_trait_exists, '123', 'trait1')
