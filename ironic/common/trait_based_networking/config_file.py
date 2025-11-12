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


from ironic.common.i18n import _
import ironic.common.trait_based_networking.base as base

import yaml


class ConfigFile(object):
    def __init__(self, filename):
        self._filename = filename
        # TODO(clif): Do this here, or defer to clients of class calling these?
        self.read()

    def read(self):
        with open(self._filename, 'r') as file:
            self._contents = yaml.safe_load(file)

    def validate(self):
        """Check that contents conform to TBN expectations."""
        reasons = []
        valid = True
        for key, value_list in self._contents.items():
            if not isinstance(value_list, list):
                reasons.append(
                    _(f"'{key}' trait does not consist of a list of actions"))
                valid = False
                continue
            for v in value_list:
                # Check necessary keys are present.
                for n in base.TraitAction.NECESSARY_KEYS:
                    if n not in v:
                        reasons.append(
                            _(f"'{key}' trait is missing '{n}' key"))
                        valid = False

                # Check for errant keys.
                for sub_key in v.keys():
                    if sub_key not in base.TraitAction.ALL_KEYS:
                        reasons.append(
                            _(f"'{key}' trait action has unrecognized key "
                              f"'{sub_key}'"))
                        valid = False

                # Make sure action is valid
                if 'action' in v:
                    action = v['action']
                    try:
                        base.Actions(action)
                    except Exception:
                        valid = False
                        reasons.append(
                            _(f"'{key}' trait action has unrecognized action "
                              f"'{action}'"))

                # Does the filter parse?
                if 'filter' in v:
                    try:
                        base.FilterExpression.parse(v['filter'])
                    except Exception:
                        valid = False
                        # TODO(clif): Surface exception text in reason below?
                        reasons.append(
                            _(f"'{key}' trait action has malformed "
                              f"filter expression: '{v['filter']}'"))

        return valid, reasons

    def parse(self):
        """Render contents of configuration file as TBN objects"""
        self._traits = []
        for trait_name, actions in self._contents.items():
            parsed_actions = []
            for action in actions:
                parsed_actions.append(base.TraitAction(
                    trait_name,
                    base.Actions(action['action']),
                    base.FilterExpression.parse(action['filter']),
                    min_count=action.get('min_count', None),
                    max_count=action.get('max_count', None)))
            self._traits.append(base.NetworkTrait(trait_name, parsed_actions))

    def traits(self):
        return self._traits
