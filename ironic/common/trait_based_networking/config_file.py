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
    """Provides functionality to read TBN configuration files

    Basic flow for use goes like:

    .. code-block:: python

        cf = ConfigFile("some_tbn_config.yaml") # File is read().
        valid, reasons = cf.validate()
        if not valid:
            # Do something with reasons, like raise an exception and log.
            return reasons
        cf.parse()  # If the file is valid, this *should* parse the config
        traits = cf.traits() # Get the parsed traits as a list.
    """
    def __init__(self, filename):
        self._filename = filename
        self._traits = []
        # TODO(clif): Do this here, or defer to clients of class calling these?
        self.read()

    def read(self):
        """Read the YAML YBN configuration file"""
        with open(self._filename, 'r') as file:
            self._contents = yaml.safe_load(file)

    def validate(self):
        """Check that contents conform to TBN expectations.

        :returns: (valid, reasons): valid is a boolean representing if the
            contents passed validation or not, and reasons is a list of
            strings describing why the contents failed validation if they are
            not valid.
        """
        reasons = []
        valid = True
        for trait_name, trait_members in self._contents.items():
            if 'actions' not in trait_members:
                valid = False
                reasons.append(
                    _(f"'{trait_name}' trait does not include an 'actions' "
                      "key "))
                continue
            if not isinstance(trait_members['actions'], list):
                reasons.append(
                    _(f"'{trait_name}.actions' does not consist of a list of "
                      "actions"))
                valid = False
                continue
            for trait_action in trait_members['actions']:
                # Check necessary keys are present.
                action_valid = True
                for n in base.TraitAction.NECESSARY_KEYS:
                    if n not in trait_action.keys():
                        reasons.append(
                            _(f"'{trait_name}' trait is missing '{n}' key"))
                        action_valid = False
                        valid = False

                # Check for errant keys.
                for sub_key in trait_action.keys():
                    if sub_key not in base.TraitAction.ALL_KEYS:
                        reasons.append(
                            _(f"'{trait_name}' trait action has unrecognized "
                              f"key '{sub_key}'"))
                        action_valid = False
                        valid = False

                # Make sure action is valid
                if 'action' in trait_action.keys():
                    action = trait_action['action']
                    action_obj = None
                    try:
                        action_obj = base.Actions(action)
                    except Exception:
                        action_valid = False
                        valid = False
                        reasons.append(
                            _(f"'{trait_name}' trait action has unrecognized "
                              f"action '{action}'"))

                # Does the filter parse?
                if 'filter' in trait_action.keys():
                    try:
                        base.FilterExpression.parse(trait_action['filter'])
                    except Exception:
                        action_valid = False
                        valid = False
                        # TODO(clif): Surface exception text in reason below?
                        reasons.append(
                            _(f"'{trait_name}' trait action has malformed "
                              "filter expression: "
                              f"'{trait_action['filter']}'"))

                if action_valid:
                    min_count = trait_action.get('min_count', None)
                    if min_count is not None:
                        min_count = int(min_count)
                    max_count = trait_action.get('max_count', None)
                    if max_count is not None:
                        max_count = int(max_count)

                    action_obj = base.TraitAction(
                        trait_name,
                        base.Actions(trait_action['action']),
                        base.FilterExpression.parse(trait_action['filter']),
                        min_count=min_count,
                        max_count=max_count)

                    validated, reason = action_obj.validate()
                    if not validated:
                        valid = False
                        reasons.append(
                            _(f"'{trait_name}' has an invalid '{action}': "
                              f"{reason}"))

        return valid, reasons

    def parse(self):
        """Render contents of configuration file as TBN objects

        The result of this method can later be retrieved by calling traits().
        """
        self._traits = []
        for trait_name, trait_members in self._contents.items():
            parsed_actions = []
            for action in trait_members['actions']:
                min_count = action.get('min_count', None)
                if min_count is not None:
                    min_count = int(min_count)
                max_count = action.get('max_count', None)
                if max_count is not None:
                    max_count = int(max_count)
                parsed_actions.append(base.TraitAction(
                    trait_name,
                    base.Actions(action['action']),
                    base.FilterExpression.parse(action['filter']),
                    min_count=min_count,
                    max_count=max_count))
            order = trait_members.get('order', 1)
            self._traits.append(base.NetworkTrait(trait_name, parsed_actions,
                                                  order))

    def traits(self):
        """Return the parsed traits from the configuration file."""
        return self._traits
