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

from dataclasses import dataclass
from dataclasses import field


@dataclass
class FauxPortLikeObject(object):
    id: str = "fake_id"
    uuid: str = "fake_uuid"
    address: str = "test"
    category: str = "cat"
    physical_network: str = "test_physnet"
    vendor: str = "fake_vendor"


@dataclass
class FauxNetwork(object):
    network_id: str = "fake_net_id"
    name: str = "test_network"
    tags: list[str] = field(default_factory=list)

def default_faux_instance_info(traits=None):
    return {
        'traits': traits
    }


@dataclass
class FauxNode(object):
    uuid: str = "fake_node_uuid"
    instance_info: dict = field(
            default_factory=default_faux_instance_info)


@dataclass
class FauxTask(object):
    node: FauxNode
    ports: list[FauxPortLikeObject] = field(default_factory=list)
    portgroups: list[FauxPortLikeObject] = field(default_factory=list)
