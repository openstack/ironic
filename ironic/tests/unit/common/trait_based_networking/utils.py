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


class FauxPortLikeObject(object):
    def __init__(
        self,
        port_id="fake_id",
        uuid="fake_uuid",
        address="test",
        category="cat",
        physical_network="test_physnet",
        vendor="fake_vendor",
    ):
        self.id = port_id
        self.uuid = uuid
        self.address = address
        self.category = category
        self.physical_network = physical_network
        self.vendor = vendor


class FauxNetwork(object):
    def __init__(
        self,
        network_id="fake_net_id",
        name="test_network",
        tags=['test_tag'],
    ):
        self.id = network_id
        self.name = name
        self.tags = tags
