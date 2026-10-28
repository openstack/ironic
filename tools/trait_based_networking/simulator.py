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


import ironic.common.trait_based_networking.base as tbn
import ironic.common.trait_based_networking.config_file as tbn_config
import ironic.common.trait_based_networking.plan as tbn_plan

import ironic.tests.unit.common.trait_based_networking.utils as test_utils

import argparse
import yaml

arg_parser = argparse.ArgumentParser(
        prog="Trait Based Networking Simulator",
        description=("See how TBN will plan a network for a node given a set "
                     "of network traits, ports, portgroups, etc."))

arg_parser.add_argument('config_file')
arg_parser.add_argument('network_file')


def main():
    args = arg_parser.parse_args()

    cf = tbn_config.ConfigFile(args.config_file)
    print("Read Trait Based Networking configuration file "
          f"'{args.config_file}'")
    valid, reasons = cf.validate()
    if not valid:
        print(f"'{args.config_file}' is NOT valid!")
        for reason in reasons:
            print(f"ERROR: {reason}")
        print("Please correct these errors and try again.")
        return
    print("Configuration is valid.")

    cf.parse()
    print("Parsed configuration.")
    for trait in cf.traits():
        print(f"Got trait '{trait.name}' with {len(trait.actions)} action(s).")
    print("")

    print("Loading test set of network objects (ports, portgroups, networks) "
          f"from '{args.network_file}'")
    data = TestNetworkDataFile(args.network_file)
    print("Test set loaded.")
    print(f"Got {len(data.ports())} test ports.")
    print(f"Got {len(data.portgroups())} test portgroups.")
    print(f"Got {len(data.networks())} test networks.")
    print("")

    for trait in cf.traits():
        print(f"Planning based on trait '{trait.name}':")
        actions = tbn_plan.plan_network(trait,
                                        "fake_node_uuid",
                                        data.ports(),
                                        data.portgroups(),
                                        data.networks(),
                                        data.vif())
        print(f"Got {len(actions)} actions:")
        for action in actions:
            print(f"    {str(action)}")
        print("")


class TestNetworkDataFile(object):
    def __init__(self, filename):
        self._filename = filename
        self.read()

    def read(self):
        with open(self._filename, 'r') as file:
            self._contents = yaml.safe_load(file)

        for typename in ['ports', 'portgroups', 'networks']:
            assert typename in self._contents, (f"no {typename} were found in "
                                                 "the test data file!")

        self._ports = [
            tbn.Port.from_ironic_port(test_utils.FauxPortLikeObject(**port))
            for port in self._contents['ports']
        ]

        self._portgroups = [
            tbn.Portgroup.from_ironic_portgroup(
                test_utils.FauxPortLikeObject(**portgroup))
            for portgroup in self._contents['portgroups']
        ]

        self._networks = [
            tbn.Network(
                id=network['id'],
                name=network['name'],
                tags=frozenset(network.get('tags', ())))
            for network in self._contents['networks']
        ]

        vif = self._contents.get('vif', {})
        self._vif = tbn.Vif(
            id=vif.get('id'),
            name=vif.get('name'),
            tags=frozenset(vif.get('tags', ())))

    def ports(self):
        return self._ports

    def portgroups(self):
        return self._portgroups

    def networks(self):
        return self._networks

    def vif(self):
        return self._vif


if __name__ == "__main__":
    main()
