#!/usr/bin/env python3
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

"""Inspection Rules Tester - Test inspection rules against hardware inventory.

This tool runs the inspection rules evaluation process to help test and
debug inspection rules before deploying them to a production environment.
"""

import argparse
import json
import sys
import yaml

from ironic.common.inspection_rules import actions
from ironic.common.inspection_rules import engine


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

    def __init__(
        self, node_file, inventory_file, rules_file, json_output=False
    ):
        self.rules_file = rules_file
        self.inventory_file = inventory_file
        self.node_file = node_file
        self.json_output = json_output
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
            print(f"Rules file not found: {self.rules_file}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Error loading rules: {e}", file=sys.stderr)
            return False
        return True

    def load_inventory(self):
        """Load hardware inventory and plugin data from JSON or YAML file."""
        try:
            data = self._load_file("inventory", self.inventory_file)
        except Exception as e:
            print(f"{e}", file=sys.stderr)
            return False

        self.inventory = data.get("inventory", {})
        self.plugin_data = data.get("plugin_data", {})
        return True

    def load_node(self):
        """Load node data from YAML file."""
        try:
            self.node_data = self._load_file("node", self.node_file)
        except Exception as e:
            print(f"{e}", file=sys.stderr)
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

    def output_json(self):
        """Output results in JSON format."""
        output = {
            "summary": {
                "total_rules": len(self.results),
                "matched_rules": sum(1 for r in self.results if r["matched"]),
                "total_errors": sum(len(r["errors"]) for r in self.results),
            },
            "rules": self.results,
            "inventory": self.inventory,
            "plugin_data": self.plugin_data,
            "node": self.node_data,
        }
        print(json.dumps(output, indent=2, default=str))

    def run(self):
        """Run the complete evaluation process."""
        if not self.load_rules():
            return 1
        if not self.load_inventory():
            return 1
        if not self.load_node():
            return 1
        self.evaluate_rules()
        if self.json_output:
            self.output_json()
        else:
            self.print_results()
        return 0


def main():
    parser = argparse.ArgumentParser(
        prog="Inspection Rules Tester",
        description=(
            "Test inspection rules against hardware inventory data "
            "to see which rules match and what actions would be "
            "executed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Capture node and inventory data then evaluate
  openstack baremetal node show <node-id> -f yaml > node.yaml
  openstack baremetal node inventory save --file inventory.json <node-id>
  %(prog)s node.yaml inventory.json rules.yaml

  # JSON output for automation
  %(prog)s --json node.yaml inventory.json rules.yaml > results.json
        """,
    )

    parser.add_argument(
        "node_file",
        help="JSON or YAML file containing node data "
             "(e.g. from 'openstack baremetal node show <id> -f json')"
    )
    parser.add_argument(
        "inventory_file",
        help="JSON or YAML file containing hardware inventory and plugin data "
             "(e.g. from 'openstack baremetal node inventory save')"
    )
    parser.add_argument(
        "rules_file", help="YAML file containing inspection rules"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )

    args = parser.parse_args()

    evaluator = InspectionRulesEvaluator(
        args.node_file,
        args.inventory_file,
        args.rules_file,
        json_output=args.json,
    )

    return evaluator.run()


if __name__ == "__main__":
    sys.exit(main())
