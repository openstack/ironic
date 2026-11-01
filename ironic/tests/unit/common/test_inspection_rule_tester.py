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

import contextlib
import io
import os
import traceback
from unittest import mock

import fixtures
import yaml

from ironic.common.inspection_rules import tester
from ironic.tests import base

NODE = {
    'uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
    'name': 'test-node',
    'driver_info': {},
    'extra': {},
    'properties': {},
}

INVENTORY = {
    'inventory': {
        'memory': {'physical_mb': 131072},
        'system_vendor': {'manufacturer': 'Dell Inc.'},
    },
    'plugin_data': {},
}

MATCHING_RULE = {
    'description': 'Dell node',
    'priority': 10,
    'conditions': [
        {'op': 'contains',
         'args': {'value': '{inventory[system_vendor][manufacturer]}',
                  'regex': '(?i)dell'}},
    ],
    'actions': [
        {'op': 'log', 'args': {'msg': 'found a Dell node'}},
    ],
}

SKIPPED_RULE = {
    'description': 'HPE node',
    'conditions': [
        {'op': 'contains',
         'args': {'value': '{inventory[system_vendor][manufacturer]}',
                  'regex': '(?i)hpe'}},
    ],
    'actions': [
        {'op': 'log', 'args': {'msg': 'found an HPE node'}},
    ],
}

BROKEN_RULE = {
    'description': 'Broken rule',
    'conditions': [
        {'op': 'gt', 'args': {'values': '{inventory[nonexistent][path]}'}},
    ],
    'actions': [
        {'op': 'log', 'args': {'msg': 'never logged'}},
    ],
}


def _capture(func, *args, **kwargs):
    """Call func, returning its result and its stdout, stderr and logs.

    Log calls are recorded by replacing the module logger rather than
    capturing the logging system, since other tests can leave the global
    logging configuration in a state where nothing reaches a handler.
    """
    output = io.StringIO()
    logs = []

    def _record(msg, *log_args, **log_kwargs):
        logs.append(msg % log_args if log_args else msg)

    def _record_exception(msg, *log_args, **log_kwargs):
        _record(msg, *log_args)
        logs.append(traceback.format_exc())

    with (mock.patch.object(tester, 'LOG', autospec=True) as mock_log,
          contextlib.redirect_stdout(output),
          contextlib.redirect_stderr(output)):
        mock_log.error.side_effect = _record
        mock_log.exception.side_effect = _record_exception
        mock_log.warning.side_effect = _record
        mock_log.info.side_effect = _record
        result = func(*args, **kwargs)
    return result, output.getvalue() + '\n'.join(logs)


class BaseTesterTestCase(base.TestCase):

    def setUp(self):
        super().setUp()
        self.temp_dir = self.useFixture(fixtures.TempDir()).path

    def _write(self, name, data, directory=None):
        path = os.path.join(directory or self.temp_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            yaml.safe_dump(data, f)
        return path

    def _write_case(self, name, node=NODE, inventory=INVENTORY):
        case_dir = os.path.join(self.temp_dir, name)
        os.makedirs(case_dir)
        if node is not None:
            self._write('node.yaml', node, directory=case_dir)
        if inventory is not None:
            self._write('inventory.yaml', inventory, directory=case_dir)
        return case_dir


class CheckFilesTestCase(BaseTesterTestCase):

    def setUp(self):
        super().setUp()
        self.node_file = self._write('node.yaml', NODE)
        self.inventory_file = self._write('inventory.yaml', INVENTORY)

    def test_matching_and_skipped_rules(self):
        rules_file = self._write('rules.yaml', [MATCHING_RULE, SKIPPED_RULE])

        rc, output = _capture(tester.check_files, self.node_file,
                              self.inventory_file, rules_file)

        self.assertEqual(0, rc)
        self.assertIn('Rule: Dell node [MATCH]', output)
        self.assertIn('Condition 1 [contains]: PASSED', output)
        self.assertIn("Action 1 [log]: {'msg': 'found a Dell node'}", output)
        self.assertIn('Rule: HPE node [SKIP]', output)
        self.assertIn('Condition 1 [contains]: FAILED', output)
        self.assertIn('Summary: 1/2 rules matched', output)

    def test_rule_without_conditions_always_matches(self):
        rule = {'description': 'unconditional',
                'actions': [{'op': 'log', 'args': {'msg': 'hello'}}]}
        rules_file = self._write('rules.yaml', [rule])

        rc, output = _capture(tester.check_files, self.node_file,
                              self.inventory_file, rules_file)

        self.assertEqual(0, rc)
        self.assertIn('Conditions: none (always matches)', output)
        self.assertIn('Summary: 1/1 rules matched', output)

    def test_broken_rule_fails(self):
        rules_file = self._write('rules.yaml', [BROKEN_RULE])

        rc, output = _capture(tester.check_files, self.node_file,
                              self.inventory_file, rules_file)

        self.assertEqual(1, rc)
        self.assertIn('ERROR:', output)
        self.assertIn('1 error(s)', output)

    def test_missing_rules_file(self):
        rules_file = os.path.join(self.temp_dir, 'nope.yaml')

        rc, output = _capture(tester.check_files, self.node_file,
                              self.inventory_file, rules_file)

        self.assertEqual(1, rc)

    def test_missing_inventory_file(self):
        rules_file = self._write('rules.yaml', [MATCHING_RULE])

        rc, output = _capture(tester.check_files, self.node_file,
                              os.path.join(self.temp_dir, 'nope.yaml'),
                              rules_file)

        self.assertEqual(1, rc)
        self.assertIn('inventory file not found', output)

    def test_invalid_rules_file(self):
        rules_file = self._write('rules.yaml', {'not': 'a list'})

        rc, output = _capture(tester.check_files, self.node_file,
                              self.inventory_file, rules_file)

        self.assertEqual(1, rc)
        self.assertIn('Error loading rules', output)


class RunSuiteTestCase(BaseTesterTestCase):

    def setUp(self):
        super().setUp()
        self.rules_file = self._write('rules.yaml', [MATCHING_RULE])

    def test_all_cases_pass(self):
        self._write_case('case-one')
        self._write_case('case-two')

        rc, output = _capture(tester.run_suite, self.temp_dir,
                              self.rules_file)

        self.assertEqual(0, rc)
        self.assertIn('PASS: case-one', output)
        self.assertIn('PASS: case-two', output)
        self.assertIn('Results: 2 passed, 0 failed', output)

    def test_failing_case(self):
        self._write_case('case-good')
        case_dir = self._write_case('case-bad')
        self._write('rules.yaml', 'ignored', directory=case_dir)
        bad_rules = self._write('bad-rules.yaml', [BROKEN_RULE])

        rc, output = _capture(tester.run_suite, self.temp_dir, bad_rules)

        self.assertEqual(1, rc)
        self.assertIn('FAIL: case-bad', output)
        self.assertIn('FAIL: case-good', output)
        self.assertIn('Results: 0 passed, 2 failed', output)
        self.assertIn('Failed tests:', output)

    def test_missing_node_file(self):
        self._write_case('case-incomplete', node=None)

        rc, output = _capture(tester.run_suite, self.temp_dir,
                              self.rules_file)

        self.assertEqual(1, rc)
        self.assertIn('FAIL: case-incomplete - missing node.yaml or '
                      'node.json', output)

    def test_missing_inventory_file(self):
        self._write_case('case-incomplete', inventory=None)

        rc, output = _capture(tester.run_suite, self.temp_dir,
                              self.rules_file)

        self.assertEqual(1, rc)
        self.assertIn('FAIL: case-incomplete - missing inventory.yaml or '
                      'inventory.json', output)

    def test_json_case_files(self):
        case_dir = os.path.join(self.temp_dir, 'case-json')
        os.makedirs(case_dir)
        self._write('node.json', NODE, directory=case_dir)
        self._write('inventory.json', INVENTORY, directory=case_dir)

        rc, output = _capture(tester.run_suite, self.temp_dir,
                              self.rules_file)

        self.assertEqual(0, rc)
        self.assertIn('PASS: case-json', output)

    def test_no_data_dir(self):
        rc, output = _capture(tester.run_suite,
                              os.path.join(self.temp_dir, 'nope'),
                              self.rules_file)

        self.assertEqual(1, rc)
        self.assertIn('No data directory found', output)

    def test_no_test_cases(self):
        rc, output = _capture(tester.run_suite, self.temp_dir,
                              self.rules_file)

        self.assertEqual(1, rc)
        self.assertIn('No test cases found', output)
