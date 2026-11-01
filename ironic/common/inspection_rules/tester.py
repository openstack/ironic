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

"""Test inspection rules against captured hardware inventory.

This module runs the inspection rules evaluation process to help test and
debug inspection rules before deploying them to a production environment.
It backs the ``ironic-manage inspection-rules check`` command.
"""

import os

import yaml

from ironic.common.inspection_rules import actions
from ironic.common.inspection_rules import engine
from oslo_log import log as logging

LOG = logging.getLogger(__name__)

class FakeNode:
    """Fake node built from 'openstack baremetal node show' output."""

    def __init__(self, data):
        for key, value in data.items():
            setattr(self, key, value)
        self._changes = []

    def save(self):
        pass


class FakeTask:
    """Minimal fake task object for testing."""

    def __init__(self, node):
        self.node = node
        self.context = None


class InspectionRulesEvaluator:
    """Evaluator for testing inspection rules against hardware inventory."""

    def __init__(self, node_file, inventory_file, rules_file):
        self.rules_file = rules_file
        self.inventory_file = inventory_file
        self.node_file = node_file
        self.rules = []
        self.inventory = {}
        self.plugin_data = {}
        self.node_data = {}
        self.results = []

    def _load_file(self, ftype, fname):
        """Load file and report errors."""
        try:
            with open(fname, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            raise Exception(f"{ftype} file not found: {fname}")
        except yaml.YAMLError as e:
            raise Exception(f"Error loading {ftype}: {e}")

    def load_rules(self):
        """Load and validate inspection rules from YAML file."""
        try:
            self.rules = engine.get_built_in_rules(self.rules_file)
        except FileNotFoundError:
            LOG.error("Rules file not found: %s", self.rules_file)
            return False
        except Exception:
            LOG.exception("Error loading rules")
            return False
        return True

    def load_inventory(self):
        """Load hardware inventory and plugin data from JSON or YAML file."""
        try:
            data = self._load_file("inventory", self.inventory_file)
        except Exception:
            LOG.exception("Error loading inventory")
            return False

        self.inventory = data.get("inventory", {})
        self.plugin_data = data.get("plugin_data", {})
        return True

    def load_node(self):
        """Load node data from YAML file."""
        try:
            self.node_data = self._load_file("node", self.node_file)
        except Exception:
            LOG.exception("Error loading node")
            return False
        return True

    def evaluate_rules(self):
        """Evaluate inspection rules against the loaded inventory."""
        node = FakeNode(self.node_data)
        task = FakeTask(node)
        sorted_rules = sorted(
            self.rules, key=lambda r: r.get("priority", 0), reverse=True)
        self.results = [self._evaluate_single_rule(task, rule)
                        for rule in sorted_rules]

    def _evaluate_single_rule(self, task, rule):
        """Evaluate a single rule and return a result dict."""
        result = {
            "uuid": rule.get("uuid"),
            "description": rule.get("description", "No description"),
            "priority": rule.get("priority", 0),
            "matched": False,
            "conditions": [],
            "actions": [],
            "errors": [],
        }

        try:
            check_result = engine._check_rule(
                task, rule, self.inventory, self.plugin_data)
        except Exception as e:
            result["errors"].append(str(e))
            return result

        if not rule.get("conditions"):
            result["matched"] = True
            masked_inventory, masked_plugin_data = (
                self.inventory, self.plugin_data)
        else:
            result["matched"] = check_result is not None
            masked_inventory, masked_plugin_data = (
                check_result if check_result is not None
                else (self.inventory, self.plugin_data))

            for idx, condition in enumerate(rule["conditions"], 1):
                entry = {"index": idx, "op": condition["op"],
                         "args": condition.get("args", {}), "passed": False}
                try:
                    entry["passed"] = engine.check_conditions(
                        task, {
                            "uuid": rule["uuid"],
                            "conditions": [condition]
                        },
                        masked_inventory, masked_plugin_data)
                except Exception as e:
                    result["errors"].append(str(e))
                result["conditions"].append(entry)

        if result["matched"]:
            for idx, action in enumerate(rule["actions"], 1):
                try:
                    action_class = actions.get_action(action["op"])
                    action_obj = action_class()

                    loop_items = action.get("loop", [])
                    if isinstance(loop_items, dict):
                        processed_args = action_obj._process_args(
                            task, action, masked_inventory, masked_plugin_data,
                            {"item": loop_items})
                        result["actions"].append(
                            {"index": idx, "op": action["op"],
                             "args": processed_args, "loop_index": 1})
                    elif isinstance(loop_items, list) and loop_items:
                        for loop_index, item in enumerate(loop_items, 1):
                            processed_args = action_obj._process_args(
                                task, action, masked_inventory,
                                masked_plugin_data, {"item": item})
                            result["actions"].append(
                                {"index": idx, "op": action["op"],
                                 "args": processed_args,
                                 "loop_index": loop_index})
                    else:
                        processed_args = action_obj._process_args(
                            task, action, masked_inventory, masked_plugin_data)
                        result["actions"].append(
                            {"index": idx, "op": action["op"],
                             "args": processed_args})
                except Exception as e:
                    result["errors"].append(str(e))

        return result

    def print_results(self):
        """Print all results in human-readable form."""
        print(f"Node:        {self.node_file}")
        print(f"Inventory:   {self.inventory_file}")
        print(f"Rules file:  {self.rules_file}")
        print()

        for result in self.results:
            status = "[MATCH]" if result["matched"] else "[SKIP]"
            print(f"Rule: {result['description']} {status}")
            print(f"  UUID: {result['uuid']}, Priority: {result['priority']}")

            if result["errors"]:
                for err in result["errors"]:
                    print(f"  ERROR: {err}")
            elif not result["conditions"]:
                print("  Conditions: none (always matches)")
            else:
                for c in result["conditions"]:
                    cstatus = "PASSED" if c["passed"] else "FAILED"
                    print(f"  Condition {c['index']} [{c['op']}]: {cstatus}")

            for a in result["actions"]:
                print(f"  Action {a['index']} [{a['op']}]: {a['args']}")

            print()

        matched = sum(1 for r in self.results if r["matched"])
        total = len(self.results)
        errors = sum(len(r["errors"]) for r in self.results)
        summary = f"Summary: {matched}/{total} rules matched"
        if errors:
            summary += f", {errors} error(s)"
        print(summary)

    def run(self):
        """Run the complete evaluation process."""
        if not self.load_rules():
            return 1
        if not self.load_inventory():
            return 1
        if not self.load_node():
            return 1
        self.evaluate_rules()
        self.print_results()
        if any(r["errors"] for r in self.results):
            return 1
        return 0


def check_files(node_file, inventory_file, rules_file):
    """Evaluate inspection rules against a single set of captured files.

    :param node_file: JSON or YAML file with node data, e.g. from
        ``openstack baremetal node show <node> -f json``.
    :param inventory_file: JSON or YAML file with hardware inventory and
        plugin data, e.g. from ``openstack baremetal node inventory save``.
    :param rules_file: YAML file with the inspection rules to evaluate.
    :returns: an exit code, 0 on success.
    """
    evaluator = InspectionRulesEvaluator(
        node_file, inventory_file, rules_file)
    return evaluator.run()


def _find_case_file(test_dir, base):
    """Find <base>.yaml or <base>.json in a test case directory."""
    for ext in ("yaml", "json"):
        candidate = os.path.join(test_dir, f"{base}.{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None


def run_suite(data_dir, rules_file):
    """Run the inspection rules tester against all test cases in a tree.

    Each subdirectory of ``data_dir`` is one test case and must contain
    a node file (``node.yaml`` or ``node.json``) and an inventory file
    (``inventory.yaml`` or ``inventory.json``). The rules in
    ``rules_file`` are evaluated against every test case.

    :param data_dir: directory containing test case subdirectories.
    :param rules_file: YAML file with the inspection rules to evaluate.
    :returns: an exit code, 0 when all test cases pass.
    """
    if not os.path.isdir(data_dir):
        LOG.error("No data directory found at %s", data_dir)
        return 1

    test_dirs = sorted(
        entry.path for entry in os.scandir(data_dir) if entry.is_dir())
    if not test_dirs:
        LOG.error("No test cases found in %s", data_dir)
        return 1

    passed = 0
    failed = []
    for test_dir in test_dirs:
        test_name = os.path.basename(test_dir)

        node_file = _find_case_file(test_dir, "node")
        if node_file is None:
            print(f"FAIL: {test_name} - missing node.yaml or node.json")
            failed.append(test_name)
            continue

        inventory_file = _find_case_file(test_dir, "inventory")
        if inventory_file is None:
            print(f"FAIL: {test_name} - missing inventory.yaml or "
                  "inventory.json")
            failed.append(test_name)
            continue

        print(f"Running: {test_name}")
        if check_files(node_file, inventory_file, rules_file) == 0:
            print(f"PASS: {test_name}")
            passed += 1
        else:
            print(f"FAIL: {test_name}")
            failed.append(test_name)
        print()

    print(f"Results: {passed} passed, {len(failed)} failed")

    if failed:
        print("Failed tests:")
        for test_name in failed:
            print(f"  - {test_name}")
        return 1

    return 0
