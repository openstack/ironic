# Copyright 2013 Red Hat, Inc.
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


from oslo_log import log
import yaml

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import actions
from ironic.common.inspection_rules import operators
from ironic.common.inspection_rules import validation
from ironic.common import utils as common_utils
from ironic.conf import CONF
from ironic import objects


LOG = log.getLogger(__name__)
SENSITIVE_FIELDS = ['password', 'auth_token', 'bmc_password']


def get_built_in_rules():
    """Load built-in inspection rules."""
    built_in_rules = []
    built_in_rules_dir = CONF.inspection_rules.built_in_rules

    if not built_in_rules_dir:
        return built_in_rules

    try:
        with open(built_in_rules_dir, 'r') as f:
            rules_data = yaml.safe_load(f)

        for rule_data in rules_data:
            try:
                rule = {
                    'uuid': rule_data.get('uuid'),
                    'priority': rule_data.get('priority', 0),
                    'description': rule_data.get('description'),
                    'scope': rule_data.get('scope'),
                    'sensitive': rule_data.get('sensitive', False),
                    'phase': rule_data.get('phase', 'main'),
                    'actions': rule_data.get('actions', []),
                    'conditions': rule_data.get('conditions', []),
                    'built_in': True
                }
                validation.validate_inspection_rule(rule)
                built_in_rules.append(rule)
            except Exception as e:
                LOG.error(_("Error parsing built-in rule: %s"), e)
                raise
    except FileNotFoundError:
        LOG.error(_("Built-in rules file not found: %s"),
                  built_in_rules_dir)
        raise
    except yaml.YAMLError as e:
        LOG.error(_("Error parsing YAML in built-in rules file %s: %s"),
                  built_in_rules_dir, e)
        raise
    except Exception as e:
        LOG.error(_("Error loading built-in rules from %s: %s"),
                  built_in_rules_dir, e)
        raise

    return built_in_rules


def _mask_sensitive_data(data):
    """Recursively mask sensitive fields in data."""
    if isinstance(data, dict):
        return {key: (_mask_sensitive_data(value)
                      if key not in SENSITIVE_FIELDS else '***')
                for key, value in data.items()}
    elif isinstance(data, list):
        return [_mask_sensitive_data(item) for item in data]
    return data


def check_conditions(task, rule, inventory, plugin_data):
    try:
        if not rule.get('conditions', None):
            return True

        for condition in rule['conditions']:
            op, invtd = common_utils.parse_inverted_operator(
                condition['op'])

            if op not in operators.OPERATORS:
                supported_ops = ', '.join(operators.OPERATORS.keys())
                msg = (_("Unsupported operator: '%(op)s'. Supported "
                         "operators are: %(supported_ops)s.") % {
                             'op': op, 'supported_ops': supported_ops})
                raise ValueError(msg)

            result = False
            plugin = operators.get_operator(op)
            if 'loop' in condition:
                result = plugin()._check_with_loop(task, condition, inventory,
                                                   plugin_data)
            else:
                result = plugin()._check_condition(task, condition, inventory,
                                                   plugin_data)
            if not result:
                LOG.debug("Skipping rule %(rule)s on node %(node)s: "
                          "condition check '%(op)s': '%(args)s' failed ",
                          {'rule': rule['uuid'], 'node': task.node.uuid,
                           'op': condition['op'], 'args': condition['args']})
                return False
        return True

    except Exception as err:
        LOG.error("Error checking condition on node %(node)s: %(err)s.",
                  {'node': task.node.uuid, 'err': err})
        raise


def apply_actions(task, rule, inventory, plugin_data):

    result = {'plugin_data': plugin_data}
    for action in rule['actions']:
        try:
            op = action['op']
            if op not in actions.ACTIONS:
                supported_ops = ', '.join(actions.ACTIONS.keys())
                msg = (_("Unsupported action: '%(op)s'. Supported actions "
                         "are: %(supported_ops)s.") % {
                             'op': op, 'supported_ops': supported_ops})
                raise ValueError(msg)

            plugin = actions.get_action(op)
            if 'loop' in action:
                action_result = plugin()._execute_with_loop(
                    task, action, inventory, result['plugin_data'])
            else:
                action_result = plugin()._execute_action(
                    task, action, inventory, result['plugin_data'])

            if action_result is not None and isinstance(action_result, dict):
                result['plugin_data'] = action_result.get(
                    'plugin_data', result['plugin_data'])
        except exception.IronicException as err:
            LOG.error("Error applying action on node %(node)s: %(err)s.",
                      {'node': task.node.uuid, 'err': err})
            raise
        except Exception as err:
            LOG.exception("Unexpected error applying action on node "
                          "%(node)s: %(err)s.", {'node': task.node.uuid,
                                                 'err': err})
            raise
    return result


def apply_rules(task, inventory, plugin_data, inspection_phase):
    """Apply inspection rules to a node."""
    node = task.node

    all_rules = objects.InspectionRule.list(
        context=task.context,
        filters={'phase': inspection_phase})

    built_in_rules = get_built_in_rules()
    rules = all_rules + built_in_rules

    if not rules:
        LOG.debug("No inspection rules to apply for phase "
                  "'%(phase)s on node: %(node)s'", {
                      'phase': inspection_phase,
                      'node': node.uuid})
        return

    mask_secrets = CONF.inspection_rules.mask_secrets
    if mask_secrets == 'always':
        inventory = _mask_sensitive_data(inventory)
        plugin_data = _mask_sensitive_data(plugin_data)
    elif mask_secrets == 'sensitive':
        # Mask secrets unless the rule is marked as sensitive
        for rule in rules:
            if not rule.get('sensitive', False):
                inventory = _mask_sensitive_data(inventory)
                plugin_data = _mask_sensitive_data(plugin_data)
                break

    rules.sort(key=lambda rule: rule['priority'], reverse=True)
    LOG.debug("Applying %(count)d inspection rules to node %(node)s",
              {'count': len(rules), 'node': node.uuid})

    result = {'plugin_data': plugin_data}
    for rule in rules:
        try:
            if not check_conditions(task, rule, inventory, plugin_data):
                continue

            LOG.info("Applying actions for rule %(rule)s to node %(node)s",
                     {'rule': rule['uuid'], 'node': node.uuid})

            rule_result = apply_actions(task, rule, inventory, plugin_data)
            if rule_result and 'plugin_data' in rule_result:
                result['plugin_data'] = rule_result['plugin_data']

        except exception.HardwareInspectionFailure:
            raise
        except exception.IronicException as e:
            if rule['sensitive']:
                LOG.error("Error applying sensitive rule %(rule)s to node "
                          "%(node)s", {'rule': rule['uuid'],
                                       'node': node.uuid})
            else:
                LOG.error("Error applying rule %(rule)s to node "
                          "%(node)s: %(error)s", {'rule': rule['uuid'],
                                                  'node': node.uuid,
                                                  'error': e})
            raise
        except Exception as e:
            msg = ("Failed to apply rule %(rule)s to node %(node)s: "
                   "%(error)s" % {'rule': rule['uuid'], 'node': node.uuid,
                                  'error': e})

            LOG.exception(msg)

            raise exception.IronicException(msg)

    LOG.info("Finished applying inspection rules to node %s", node.uuid)
    return result
