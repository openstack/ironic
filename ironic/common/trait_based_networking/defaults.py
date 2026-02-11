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


from ironic.common.trait_based_networking import base
from ironic.common.trait_based_networking import loader

DEFAULT_TRAIT_NAME = "CUSTOM_DEFAULT_TBN_TRAIT"

DEFAULT_TRAIT = base.NetworkTrait(
    DEFAULT_TRAIT_NAME,
    # Define a single action which should match any available port or
    # portgroup just once.
    [base.TraitAction(DEFAULT_TRAIT_NAME,
                      base.Actions.ATTACH_PORT,
                      base.FilterExpression.parse(
                          "port.is_port || port.is_portgroup"),
                      max_count=1)]
)

def default_network_trait():
    """Gets the default TBN trait

    :returns: A single trait representing the default trait to apply if no
    other traits apply to a node. Will get the default defined in the
    configuration file if present. Otherwise returns a predefined default
    which matches the first available port or portgroup.
    """
    # Return the default trait defined in the configuration file, if present.
    traits_dict = {trait.name: trait
                   for trait in loader.tbn_config_file_traits()}
    if DEFAULT_TRAIT_NAME in traits_dict:
        return traits_dict[DEFAULT_TRAIT_NAME]

    # Otherwise use the pre-defined default trait.
    return DEFAULT_TRAIT
