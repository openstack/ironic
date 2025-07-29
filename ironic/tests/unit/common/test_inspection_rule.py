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

from ironic.common import exception
from ironic.common import inspection_rules
from ironic.common.inspection_rules import base
from ironic.common.inspection_rules import engine
from ironic.common.inspection_rules import utils
from ironic.common.inspection_rules import validation
from ironic.conductor import task_manager
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class TestInspectionRules(db_base.DbTestCase):
    def setUp(self):
        super(TestInspectionRules, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               driver_info={},
                                               extra={})

        self.sensitive_fields = ['password', 'auth_token', 'bmc_password']
        self.test_data = {
            'username': 'testuser',
            'password': 'secret123',
            'nested': {
                'normal': 'value',
                'password': 'nested_secret'
            },
            'list_data': [
                {'name': 'item1', 'password': 'item1_secret'},
                {'name': 'item2', 'normal': 'value2'}
            ],
            'auth_token': 'abc123token'
        }

        self.inventory = {
            'cpu': {'count': 4, 'architecture': 'x86_64'},
            'memory': {'total': 8192, 'physical_mb': 8192},
            'interfaces': [
                {'name': 'eth0', 'mac_address': '2a:03:9c:53:4e:46'},
                {'name': 'eth1', 'mac_address': 'a2:67:c1:b8:c1:bd'}
            ],
            'disks': [
                {'name': '/dev/sda', 'size': 1000000, 'model': 'test-disk-1'},
                {'name': '/dev/sdb', 'size': 2000000, 'model': 'test-disk-2'}
            ],
            'bmc_address': '192.168.1.100',
            'bmc_password': 'secret'
        }
        self.plugin_data = {"plugin": "data", "logs": "test logs",
                            "password": "plugin_secret"}

        self.rule1 = obj_utils.create_test_inspection_rule(self.context)
        self.rule2 = obj_utils.create_test_inspection_rule(self.context)
        self.sensitive_rule = obj_utils.create_test_inspection_rule(
            self.context, sensitive=True)


@mock.patch('ironic.objects.InspectionRule.list', autospec=True)
class TestApplyRules(TestInspectionRules):
    def setUp(self):
        super(TestApplyRules, self).setUp()

    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_no_rules(self, mock_apply_actions,
                                  mock_check_conditions, mock_get_built_in,
                                  mock_list):
        mock_list.return_value = []
        mock_get_built_in.return_value = []

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = engine.apply_rules(task, self.inventory,
                                        self.plugin_data, 'main')

        mock_list.assert_called_once_with(
            context=self.context,
            filters={'phase': 'main'})
        mock_get_built_in.assert_called_once()

        mock_check_conditions.assert_not_called()
        mock_apply_actions.assert_not_called()
        self.assertIsNone(result)

    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_success(self, mock_apply_actions,
                                 mock_check_conditions, mock_get_built_in,
                                 mock_list):
        rule1 = {'uuid': 'rule-1', 'priority': 100, 'conditions': [],
                 'actions': [{'op': 'set-attribute',
                              'args': {'path': 'a', 'value': 'b'}}]}
        rule2 = {'uuid': 'rule-2', 'priority': 50, 'conditions': [],
                 'actions': [
                     {'op': 'set-capability',
                      'args': {'name': 'boot_mode', 'value': 'uefi'}}]}
        mock_list.return_value = [rule1]
        mock_get_built_in.return_value = [rule2]
        mock_check_conditions.return_value = True

        with task_manager.acquire(self.context, self.node.uuid) as task:
            engine.apply_rules(task, self.inventory, self.plugin_data, 'main')

        mock_list.assert_called_once_with(
            context=self.context,
            filters={'phase': 'main'})

        mock_get_built_in.assert_called_once()
        self.assertEqual(2, mock_check_conditions.call_count)
        self.assertEqual(2, mock_apply_actions.call_count)

    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_some_conditions_pass(self, mock_apply_actions,
                                              mock_check_conditions,
                                              mock_get_built_in,
                                              mock_list):
        """Test that rules are skipped when conditions don't match."""
        mock_list.return_value = [self.rule1]
        mock_get_built_in.return_value = [self.rule2]

        mock_check_conditions.side_effect = [False, True]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            engine.apply_rules(task, self.inventory, self.plugin_data, 'main')

        self.assertEqual(2, mock_check_conditions.call_count)
        mock_apply_actions.assert_called_once()

    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_all_conditions_fail(self, mock_apply_actions,
                                             mock_check_conditions,
                                             mock_get_built_in,
                                             mock_list):
        """Test that rules are skipped when conditions don't match."""
        mock_list.return_value = [self.rule1]
        mock_get_built_in.return_value = [self.rule2]

        mock_check_conditions.side_effect = [False, False]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            engine.apply_rules(task, self.inventory, self.plugin_data, 'main')

        self.assertEqual(2, mock_check_conditions.call_count)
        mock_apply_actions.assert_not_called()

    @mock.patch.object(engine, 'LOG', autospec=True)
    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_ironic_exception(self, mock_apply_actions,
                                          mock_check_conditions,
                                          mock_get_built_in,
                                          mock_log, mock_list):
        """Test that IronicException is re-raised."""
        mock_list.return_value = [self.rule1, self.rule2]
        mock_get_built_in.return_value = []
        mock_check_conditions.return_value = True

        mock_apply_actions.side_effect = [
            exception.IronicException("Expected error"),
            {'plugin_data': {'updated': 'data'}}
        ]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IronicException,
                              engine.apply_rules, task, self.inventory,
                              self.plugin_data, 'main')

        mock_log.error.assert_called_once()

        self.assertEqual(1, mock_apply_actions.call_count)

    @mock.patch.object(utils, 'ShallowMaskDict', autospec=True)
    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_with_always_mask(self, mock_apply_actions,
                                          mock_check_conditions,
                                          mock_get_built_in,
                                          mock_masked_dict, mock_list):
        """Test apply_rules with mask_secrets='always'."""
        self.config(mask_secrets='always', group='inspection_rules')

        mock_list.return_value = [self.rule1]
        mock_get_built_in.return_value = [self.rule2]
        mock_check_conditions.return_value = True

        masked_inventory = mock.MagicMock()
        masked_plugin_data = mock.MagicMock()
        mock_masked_dict.side_effect = [masked_inventory, masked_plugin_data,
                                        mock.MagicMock(), mock.MagicMock()]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            engine.apply_rules(task, self.inventory, self.plugin_data, 'main')

        mock_masked_dict.assert_has_calls([
            mock.call(self.inventory,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=True),
            mock.call(self.plugin_data,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=True),
            mock.call(self.inventory,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=True),
            mock.call(self.plugin_data,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=True)
        ])

    @mock.patch.object(utils, 'ShallowMaskDict', autospec=True)
    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_with_never_mask(self, mock_apply_actions,
                                         mock_check_conditions,
                                         mock_get_built_in, mock_masked_dict,
                                         mock_list):
        """Test apply_rules with mask_secrets='never'."""
        self.config(mask_secrets='never', group='inspection_rules')

        mock_list.return_value = [self.rule1]
        mock_get_built_in.return_value = [self.rule2]
        mock_check_conditions.return_value = True

        masked_inventory = mock.MagicMock()
        masked_plugin_data = mock.MagicMock()
        mock_masked_dict.side_effect = [masked_inventory, masked_plugin_data,
                                        mock.MagicMock(), mock.MagicMock()]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            engine.apply_rules(task, self.inventory, self.plugin_data, 'main')

        mock_masked_dict.assert_has_calls([
            mock.call(self.inventory,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=False),
            mock.call(self.plugin_data,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=False),
            mock.call(self.inventory,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=False),
            mock.call(self.plugin_data,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=False)
        ])

    @mock.patch.object(utils, 'ShallowMaskDict', autospec=True)
    @mock.patch.object(engine, 'get_built_in_rules', autospec=True)
    @mock.patch.object(engine, 'check_conditions', autospec=True)
    @mock.patch.object(engine, 'apply_actions', autospec=True)
    def test_apply_rules_with_sensitive_mask(self, mock_apply_actions,
                                             mock_check_conditions,
                                             mock_get_built_in,
                                             mock_masked_dict, mock_list):
        """Test apply_rules with mask_secrets='sensitive'."""
        self.config(mask_secrets='sensitive', group='inspection_rules')

        mock_list.return_value = [self.rule1, self.sensitive_rule]
        mock_get_built_in.return_value = []
        mock_check_conditions.return_value = True

        masked_inventory1 = mock.MagicMock()
        masked_plugin_data1 = mock.MagicMock()
        masked_inventory2 = mock.MagicMock()
        masked_plugin_data2 = mock.MagicMock()
        mock_masked_dict.side_effect = [
            masked_inventory1, masked_plugin_data1,
            masked_inventory2, masked_plugin_data2
        ]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            engine.apply_rules(task, self.inventory, self.plugin_data, 'main')

        mock_masked_dict.assert_has_calls([
            mock.call(self.inventory,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=True),
            mock.call(self.plugin_data,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=True),
            mock.call(self.inventory,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=False),
            mock.call(self.plugin_data,
                      sensitive_fields=engine.SENSITIVE_FIELDS,
                      mask_enabled=False)
        ])


class TestOperators(TestInspectionRules):
    def setUp(self):
        super(TestOperators, self).setUp()

    def test_operator_exceptions(self):
        """Test that operators raise proper exceptions for invalid inputs."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # NetOperator with invalid subnet
            net_op = inspection_rules.operators.NetOperator()
            self.assertRaises(
                exception.InspectionRuleExecutionFailure,
                net_op, task, address='192.168.1.1', subnet='invalid-subnet'
            )

            # MatchesOperator with invalid regex
            matches_op = inspection_rules.operators.MatchesOperator()
            self.assertRaises(
                exception.InspectionRuleExecutionFailure,
                matches_op, task, value='test', regex='[unclosed'
            )

            # ContainsOperator with invalid regex
            contains_op = inspection_rules.operators.ContainsOperator()
            self.assertRaises(
                exception.InspectionRuleExecutionFailure,
                contains_op, task, value='test', regex='[unclosed'
            )

            # SimpleOperator with non-list values
            eq_op = inspection_rules.operators.EqOperator()
            self.assertRaises(
                exception.RuleConditionCheckFailure,
                eq_op, task, values="not-a-list"
            )

    def test_oneofoperator_edge_cases(self):
        """Test OneOfOperator with edge cases."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            op = inspection_rules.operators.OneOfOperator()

            self.assertFalse(op(task, value='test', values=[]))
            self.assertFalse(op(task, value=None, values=['a', 'b']))
            self.assertTrue(op(task, value='a', values=['a', 'b']))

    def test_is_true_false_operators_edge_cases(self):
        """Test IsTrueOperator and IsFalseOperator."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            true_op = inspection_rules.operators.IsTrueOperator()
            false_op = inspection_rules.operators.IsFalseOperator()

            self.assertTrue(true_op(task, value='yes'))
            self.assertTrue(true_op(task, value='TRUE'))
            self.assertFalse(true_op(task, value='no'))

            self.assertTrue(false_op(task, value='no'))
            self.assertTrue(false_op(task, value='FALSE'))
            self.assertFalse(false_op(task, value='yes'))

            self.assertTrue(true_op(task, value=1))
            self.assertTrue(true_op(task, value=0.1))
            self.assertFalse(true_op(task, value=0))

            self.assertTrue(false_op(task, value=0))
            self.assertFalse(false_op(task, value=1))

            self.assertFalse(true_op(task, value=None))
            self.assertTrue(false_op(task, value=None))

            self.assertFalse(true_op(task, value={}))
            self.assertFalse(true_op(task, value=[]))

    def test_operator_with_loop(self):
        """Test operator check_with_loop method."""
        eq_condition = {
            'op': 'eq',
            'args': {'values': [1, '{item}']},
            'loop': [1, 2, 3, 4],
            'multiple': 'any'
        }

        contains_condition = {
            'op': 'contains',
            'args': {'value': '{item}', 'regex': '4'},
            'loop': ['test4', 'value5', 'string6'],
            'multiple': 'any'
        }

        oneof_condition = {
            'op': 'one-of',
            'args': {'value': '{inventory[cpu][architecture]}',
                     'values': ['{item}']},
            'loop': ['x86_64', 'aarch64', 'ppc64le'],
            'multiple': 'any'
        }

        with task_manager.acquire(self.context, self.node.uuid) as task:
            eq_op = inspection_rules.operators.EqOperator()
            contains_op = inspection_rules.operators.ContainsOperator()
            oneof_op = inspection_rules.operators.OneOfOperator()

            # 'any' multiple (should return True)
            self.assertTrue(eq_op.check_with_loop(
                task, eq_condition, self.inventory, self.plugin_data))
            self.assertTrue(contains_op.check_with_loop(
                task, contains_condition, self.inventory, self.plugin_data))
            self.assertTrue(oneof_op.check_with_loop(
                task, oneof_condition, self.inventory, self.plugin_data))

            # 'all' multiple (should return False)
            eq_condition['multiple'] = 'all'
            contains_condition['multiple'] = 'all'
            oneof_condition['multiple'] = 'all'

            self.assertFalse(eq_op.check_with_loop(
                task, eq_condition, self.inventory, self.plugin_data))
            self.assertFalse(contains_op.check_with_loop(
                task, contains_condition, self.inventory, self.plugin_data))
            self.assertFalse(oneof_op.check_with_loop(
                task, oneof_condition, self.inventory, self.plugin_data))

            # 'first' multiple (should return True)
            eq_condition['multiple'] = 'first'
            contains_condition['multiple'] = 'first'
            oneof_condition['multiple'] = 'first'

            self.assertTrue(eq_op.check_with_loop(
                task, eq_condition, self.inventory, self.plugin_data))
            self.assertTrue(contains_op.check_with_loop(
                task, contains_condition, self.inventory, self.plugin_data))
            self.assertTrue(oneof_op.check_with_loop(
                task, oneof_condition, self.inventory, self.plugin_data))

            # 'last' multiple (should return False for eq, True for others)
            eq_condition['multiple'] = 'last'
            contains_condition['multiple'] = 'last'
            oneof_condition['multiple'] = 'last'

            self.assertFalse(eq_op.check_with_loop(task, eq_condition,
                                                   self.inventory,
                                                   self.plugin_data))
            self.assertFalse(contains_op.check_with_loop(
                task, contains_condition, self.inventory, self.plugin_data))
            # This should be False since 'ppc64le' doesn't match 'x86_64'
            self.assertFalse(oneof_op.check_with_loop(
                task, oneof_condition, self.inventory, self.plugin_data))

    def test_rule_operators(self):
        """Test all inspection_rules.operators with True and False cases."""
        operator_tests = {
            inspection_rules.operators.EqOperator: [
                {'values': [5, 5]},
                {'values': [5, 10]}
            ],
            inspection_rules.operators.NeOperator: [
                {'values': [5, 10]},
                {'values': [5, 5]}
            ],
            inspection_rules.operators.LtOperator: [
                {'values': [5, 10]},
                {'values': [10, 5]}
            ],
            inspection_rules.operators.LeOperator: [
                {'values': [5, 10]},
                {'values': [10, 5]}
            ],
            inspection_rules.operators.GtOperator: [
                {'values': [10, 5]},
                {'values': [5, 10]}
            ],
            inspection_rules.operators.GeOperator: [
                {'values': [10, 5]},
                {'values': [5, 10]}
            ],
            inspection_rules.operators.EmptyOperator: [
                {'value': ''},
                {'value': 'not empty'}
            ],
            inspection_rules.operators.NetOperator: [
                {'address': '192.168.1.5', 'subnet': '192.168.1.0/24'},
                {'address': '10.0.0.1', 'subnet': '192.168.1.0/24'}
            ],
            inspection_rules.operators.MatchesOperator: [
                {'value': 'abc123', 'regex': r'abc\d+'},
                {'value': 'xyz123', 'regex': r'abc\d+'}
            ],
            inspection_rules.operators.ContainsOperator: [
                {'value': 'test-abc123-end', 'regex': r'abc\d+'},
                {'value': 'test-xyz-end', 'regex': r'abc\d+'}
            ],
            inspection_rules.operators.OneOfOperator: [
                {'value': 'b', 'values': ['a', 'b', 'c']},
                {'value': 'z', 'values': ['a', 'b', 'c']}
            ],
            inspection_rules.operators.IsNoneOperator: [
                {'value': None},
                {'value': 'something'}
            ],
            inspection_rules.operators.IsTrueOperator: [
                {'value': True},
                {'value': False}
            ],
            inspection_rules.operators.IsFalseOperator: [
                {'value': False},
                {'value': True}
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid) as task:
            for op_class, test_cases in operator_tests.items():
                op = op_class()
                result = op(task, **test_cases[0])
                self.assertTrue(result)

                result = op(task, **test_cases[1])
                self.assertFalse(result)


class TestActions(TestInspectionRules):
    """Test inspection rule actions"""
    def setUp(self):
        super(TestActions, self).setUp()

    @mock.patch.object(inspection_rules.actions.LOG, 'info', autospec=True)
    def test_log_action(self, mock_log):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.LogAction()
            test_msg = "Test log message"
            action(task, msg=test_msg)
            mock_log.assert_called_once_with(test_msg)

    def test_fail_action(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.FailAction()
            error_msg = "Test failure"
            self.assertRaises(exception.HardwareInspectionFailure,
                              action, task, msg=error_msg)

    def test_action_path_dot_slash_notation(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.SetAttributeAction()

            # slash notation
            action(
                task, path='driver_info/new', value={'new_key': 'test_value'})

            # dot notation
            action(task, path='driver_info.next.nested.deeper',
                   value={'next_key': 'test_value'})

            self.assertEqual(
                {'new_key': 'test_value'}, task.node.driver_info['new'])
            self.assertEqual(
                {'nested': {'deeper': {'next_key': 'test_value'}}},
                task.node.driver_info['next'])

    def test_set_attribute_action(self):
        """Test SetAttributeAction sets node attribute."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.SetAttributeAction()

            action(
                task, path='driver_info/new', value={'new_key': 'test_value'})

            self.assertEqual(
                {'new_key': 'test_value'}, task.node.driver_info['new'])

    def test_extend_attribute_action(self):
        """Test ExtendAttributeAction extends a list attribute."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.ExtendAttributeAction()
            task.node.tags = ['existing']
            action(task, path='tags', value='new_tag')
            self.assertEqual(['existing', 'new_tag'], task.node.tags)

    def test_del_attribute_action(self):
        """Test DelAttributeAction deletes a node attribute."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # Set up a value to delete
            task.node.extra = {'to_delete': 'value'}
            action = inspection_rules.actions.DelAttributeAction()
            action(task, path='extra/to_delete')
            self.assertEqual({}, task.node.extra)

    @mock.patch.object(inspection_rules.actions.objects.Trait, 'create',
                       autospec=True)
    def test_add_trait_action(self, mock_create):
        """Test AddTraitAction adds a node trait."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.AddTraitAction()
            trait_name = 'CUSTOM_AWESOME_TRAIT'
            action(task, name=trait_name)
            mock_create.assert_called_once()
            trait = mock_create.call_args[0][0]
            self.assertEqual(trait_name, trait.trait)

    @mock.patch.object(inspection_rules.actions.objects.Trait, 'destroy',
                       autospec=True)
    def test_remove_trait_action(self, mock_destroy):
        """Test RemoveTraitAction removes a node trait."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.RemoveTraitAction()
            trait_name = 'CUSTOM_AWESOME_TRAIT'
            action(task, name=trait_name)
            mock_destroy.assert_called_once_with(
                task.context, node_id=task.node.id, trait=trait_name)

    @mock.patch.object(inspection_rules.actions.driver_utils,
                       'add_node_capability', autospec=True)
    def test_set_capability_action(self, mock_add):
        """Test SetCapabilityAction sets a node capability."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.SetCapabilityAction()
            action(task, name='boot_mode', value='uefi')
            mock_add.assert_called_once_with(task, 'boot_mode', 'uefi')

    def test_unset_capability_action(self):
        """Test UnsetCapabilityAction removes a node capability."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties = {
                'capabilities': 'boot_mode:uefi,other:value'}
            action = inspection_rules.actions.UnsetCapabilityAction()
            action(task, name='boot_mode')
            self.assertEqual('other:value',
                             task.node.properties['capabilities'])

    def test_set_port_attribute_action(self):
        """Test SetPortAttributeAction sets a port attribute."""
        fake_port = mock.Mock()
        fake_port.uuid = uuidutils.generate_uuid()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [fake_port]
            action = inspection_rules.actions.SetPortAttributeAction()
            action(task, port_id=fake_port.uuid, path='extra',
                   value='test_value')
            setattr(fake_port, 'extra', 'test_value')
            fake_port.save.assert_called_once()

    def test_extend_port_attribute_action(self):
        """Test ExtendPortAttributeAction extends a port attribute list."""
        fake_port = mock.Mock()
        fake_port.uuid = uuidutils.generate_uuid()
        fake_port.tags = ['existing']

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [fake_port]
            action = inspection_rules.actions.ExtendPortAttributeAction()
            action(task, port_id=fake_port.uuid, path='tags', value='new_tag')
            setattr(fake_port, 'tags', ['existing', 'new_tag'])
            fake_port.save.assert_called_once()

    def test_del_port_attribute_action(self):
        """Test DelPortAttributeAction deletes a port attribute."""
        fake_port = mock.Mock()
        fake_port.uuid = uuidutils.generate_uuid()
        fake_port.extra = {'to_delete': 'value'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [fake_port]
            action = inspection_rules.actions.DelPortAttributeAction()
            action(task, port_id=fake_port.uuid, path='extra/to_delete')
            fake_port.save.assert_called_once()

    def test_set_plugin_data_action(self):
        """Test SetPluginDataAction sets plugin data."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            plugin_data = {'existing': 'data'}
            action = inspection_rules.actions.SetPluginDataAction()
            action(task, path='test_key', value='test_value',
                   plugin_data=plugin_data)
            expected = {'existing': 'data', 'test_key': 'test_value'}
            self.assertEqual(expected, plugin_data)

    def test_extend_plugin_data_action(self):
        """Test ExtendPluginDataAction extends a plugin data list."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            plugin_data = {'test_list': ['item1']}
            action = inspection_rules.actions.ExtendPluginDataAction()
            action(task, path='test_list', value='item2',
                   plugin_data=plugin_data)
            expected = {'test_list': ['item1', 'item2']}
            self.assertEqual(expected, plugin_data)

    def test_unset_plugin_data_action(self):
        """Test UnsetPluginDataAction removes plugin data."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            plugin_data = {'to_remove': 'value', 'keep': 'value'}
            action = inspection_rules.actions.UnsetPluginDataAction()
            action(task, path='to_remove', plugin_data=plugin_data)
            self.assertEqual({'keep': 'value'}, plugin_data)

    def test_action_error_cases(self):
        """Test that actions properly handle error cases."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # SetAttributeAction nested path on a non-dict
            set_attr = inspection_rules.actions.SetAttributeAction()
            task.node.driver = 'fake-hardware'
            self.assertRaises(
                exception.RuleActionExecutionFailure,
                set_attr, task, path='driver.some_key', value='test'
            )

            # ExtendAttributeAction non-list attribute
            task.node.driver = 'fake-hardware'
            extend_attr = inspection_rules.actions.ExtendAttributeAction()
            self.assertRaises(
                exception.RuleActionExecutionFailure,
                extend_attr, task, path='driver', value='new_item'
            )

            # DelAttributeAction nested path on a non-dict
            del_attr = inspection_rules.actions.DelAttributeAction()
            task.node.driver = 'fake-hardware'
            self.assertRaises(
                exception.RuleActionExecutionFailure,
                del_attr, task, path='driver.nonexistent_key'
            )

            # SetPortAttributeAction non-existent port
            set_port = inspection_rules.actions.SetPortAttributeAction()
            fake_port_id = uuidutils.generate_uuid()
            self.assertRaises(
                exception.PortNotFound,
                set_port, task, port_id=fake_port_id, path='extra',
                value='test'
            )

            # LogAction with invalid log level
            log_action = inspection_rules.actions.LogAction()
            self.assertRaises(
                exception.InspectionRuleExecutionFailure,
                log_action, task, msg='test message', level='invalid_level'
            )

    def test_action_with_list_loop(self):
        """Test action execute_with_loop method."""
        list_loop_data = {
            'op': 'set-attribute',
            'args': {'path': '{item[path]}', 'value': '{item[value]}'},
            'loop': [
                {'path': 'driver_info/ipmi_username', 'value': 'cidadmin'},
                {'path': 'driver_info/ipmi_password', 'value': 'cidpassword'},
                {
                    'path': 'driver_info/ipmi_address',
                    'value': '{inventory[bmc_address]}'
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.SetAttributeAction()
            action.execute_with_loop(task, list_loop_data, self.inventory,
                                     self.plugin_data)
            self.assertEqual('cidadmin',
                             task.node.driver_info['ipmi_username'])
            self.assertEqual('cidpassword',
                             task.node.driver_info['ipmi_password'])
            self.assertEqual('192.168.1.100',
                             task.node.driver_info['ipmi_address'])

    def test_action_with_dict_loop(self):
        """Test action execute_with_loop method."""
        dict_loop_data = {
            'op': 'set-attribute',
            'args': {'path': '{item[path]}', 'value': '{item[value]}'},
            'loop': {
                'path': 'driver_info/ipmi_address',
                'value': '{inventory[bmc_address]}'
            }
        }

        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.SetAttributeAction()
            action.execute_with_loop(task, dict_loop_data, self.inventory,
                                     self.plugin_data)

            self.assertEqual('192.168.1.100',
                             task.node.driver_info['ipmi_address'])

    @mock.patch(
        'ironic.common.inspection_rules.actions.requests.Session',
        autospec=True)
    def test_call_api_hook_action_success(self, mock_session):
        """Test CallAPIHookAction successfully calls an API."""
        mock_session_instance = mock_session.return_value
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_session_instance.get.return_value = mock_response

        with task_manager.acquire(self.context, self.node.uuid) as task:
            action = inspection_rules.actions.CallAPIHookAction()
            test_url = 'http://example.com/simple_hook'
            action(task, url=test_url)
            mock_session_instance.mount.assert_any_call("http://", mock.ANY)
            mock_session_instance.mount.assert_any_call("https://", mock.ANY)
            mock_session_instance.get.assert_called_once_with(
                test_url, timeout=5)
            mock_response.raise_for_status.assert_called_once()


class TestShallowMask(TestInspectionRules):
    def setUp(self):
        super(TestShallowMask, self).setUp()

    def test_set_mask_enabled(self):
        """Test that set_mask_enabled properly toggles masking."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        self.assertEqual('***', masked_dict['password'])

        masked_dict.set_mask_enabled(False)
        self.assertEqual('secret123', masked_dict['password'])

        masked_dict.set_mask_enabled(True)
        self.assertEqual('***', masked_dict['password'])

    def test_getitem_masked(self):
        """Test that __getitem__ masks sensitive fields."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        self.assertEqual('***', masked_dict['password'])
        self.assertEqual('***', masked_dict['auth_token'])

        self.assertEqual('testuser', masked_dict['username'])

    def test_getitem_not_masked(self):
        """Test that __getitem__ doesn't mask when disabled."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=False)

        self.assertEqual('secret123', masked_dict['password'])
        self.assertEqual('abc123token', masked_dict['auth_token'])

    def test_nested_dict_masking(self):
        """Test that nested dictionaries are properly masked."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        nested = masked_dict['nested']
        self.assertIsInstance(nested, utils.ShallowMaskDict)
        self.assertEqual('***', nested['password'])

        self.assertEqual('value', nested['normal'])

    def test_list_masking(self):
        """Test that lists containing dictionaries are properly masked."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        list_data = masked_dict['list_data']
        self.assertEqual('***', list_data[0]['password'])

        self.assertEqual('item1', list_data[0]['name'])
        self.assertEqual('value2', list_data[1]['normal'])

    def test_items_masked(self):
        """Test that items() method returns masked values."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        items = dict(masked_dict.items())

        self.assertEqual('***', items['password'])
        self.assertEqual('***', items['auth_token'])
        self.assertEqual('***', items['nested']['password'])

    def test_values_masked(self):
        """Test that values() method masks sensitive values."""
        test_data = {'username': 'user', 'password': 'secret'}
        masked_dict = utils.ShallowMaskDict(
            test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        values = list(masked_dict.values())

        self.assertIn('user', values)
        self.assertIn('***', values)
        self.assertNotIn('secret', values)

    def test_get_method_masked(self):
        """Test that the get() method properly masks sensitive fields."""
        masked_dict = utils.ShallowMaskDict(
            self.test_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        self.assertEqual('***', masked_dict.get('password'))
        self.assertEqual('testuser', masked_dict.get('username'))

        # Non-existent field should return default
        self.assertIsNone(masked_dict.get('nonexistent'))
        self.assertEqual('default', masked_dict.get('nonexistent', 'default'))

    def test_modifying_dict(self):
        """Test that modifications affect the original data."""
        original_data = {'username': 'user', 'data': [1, 2, 3]}
        masked_dict = utils.ShallowMaskDict(
            original_data, sensitive_fields=self.sensitive_fields,
            mask_enabled=True)

        masked_dict['new_key'] = 'new_value'
        masked_dict['data'].append(4)

        self.assertEqual('new_value', original_data['new_key'])
        self.assertEqual([1, 2, 3, 4], original_data['data'])


class TestInterpolation(TestInspectionRules):
    def setUp(self):
        super(TestInterpolation, self).setUp()

    def test_variable_interpolation(self):
        """Test variable interpolation."""
        loop_context = {
            'item': {
                'key': 'value',
                'nested': {'deep': 'nested_value'}
            }
        }

        with task_manager.acquire(self.context, self.node.uuid) as task:
            value = "{inventory[cpu][architecture]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory, self.plugin_data)
            self.assertEqual("x86_64", result)

            value = "{inventory[interfaces][0][mac_address]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory, self.plugin_data)
            self.assertEqual("2a:03:9c:53:4e:46", result)

            value = "{plugin_data[plugin]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory, self.plugin_data)
            self.assertEqual("data", result)

            value = "{node.driver}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory, self.plugin_data)
            self.assertEqual("fake-hardware", result)

            value = "{item}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory,
                self.plugin_data, loop_context)

            self.assertEqual(
                "{'key': 'value', 'nested': {'deep': 'nested_value'}}",
                result)

            value = "{item[key]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory,
                self.plugin_data, loop_context)
            self.assertEqual("value", result)

            value = "{item[nested][deep]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory,
                self.plugin_data, loop_context)
            self.assertEqual("nested_value", result)

            value = "CPU: {inventory[cpu][count]}, Item: {item[key]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory,
                self.plugin_data, loop_context)
            self.assertEqual("CPU: 4, Item: value", result)

            dict_value = {
                "normal_key": "normal_value",
                "interpolated_key": "{inventory[cpu][architecture]}",
                "nested": {
                    "item_key": "{item[key]}",
                    "inventory_key": "{inventory[bmc_address]}"
                }
            }
            result = base.Base.interpolate_variables(
                dict_value, task.node, self.inventory,
                self.plugin_data, loop_context)
            self.assertEqual({
                "normal_key": "normal_value",
                "interpolated_key": "x86_64",
                "nested": {
                    "item_key": "value",
                    "inventory_key": "192.168.1.100"
                }
            }, result)

            list_value = [
                "normal_value",
                "{inventory[cpu][architecture]}",
                "{item[key]}",
                ["{inventory[bmc_address]}", "{item[nested][deep]}"]
            ]
            result = base.Base.interpolate_variables(
                list_value, task.node, self.inventory,
                self.plugin_data, loop_context)
            self.assertEqual([
                "normal_value",
                "x86_64",
                "value",
                ["192.168.1.100", "nested_value"]
            ], result)

            value = "{inventory[missing][key]}"
            result = base.Base.interpolate_variables(
                value, task.node, self.inventory, self.plugin_data)
            self.assertEqual(value, result)


class TestValidation(TestInspectionRules):
    def test_unsupported_operator_rejected(self):
        """Unsupported operator (even inverted) must raise Invalid."""
        rule = {
            'actions': [{'op': 'noop', 'args': {}}],
            'conditions': [{'op': '!unknown', 'args': {}}]
        }

        self.assertRaises(exception.Invalid, validation.validate_rule, rule)

    def test_conditions_not_list_raises_invalid(self):
        rule = {
            'actions': [{'op': 'noop', 'args': {}}],
            'conditions': {'op': 'eq', 'args': [1, 1]}  # not a list
        }

        self.assertRaises(exception.Invalid, validation.validate_rule, rule)

    def test_missing_actions_key_raises_invalid(self):
        rule = {
            'conditions': [{'op': 'eq', 'args': [1, 1]}]
            # 'actions' is missing
        }

        self.assertRaises(exception.Invalid, validation.validate_rule, rule)
