#
# Copyright 2017 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from tempest import config
from tempest import test

from ironic_tempest_plugin.tests.scenario import \
    baremetal_standalone_manager as bsm

CONF = config.CONF


class BaremetalAgentIpmitoolWholedisk(bsm.BaremetalStandaloneScenarioTest):

    driver = 'agent_ipmitool'
    image_ref = CONF.baremetal.whole_disk_image_ref
    wholedisk_image = True

    @test.idempotent_id('defff515-a6ff-44f6-9d8d-2ded51196d98')
    @test.services('image', 'network', 'object_storage')
    def test_ip_access_to_server(self):
        self.ping_ip_address(self.node_ip, should_succeed=True)


class BaremetalAgentIpmitoolPartitioned(bsm.BaremetalStandaloneScenarioTest):

    driver = 'agent_ipmitool'
    image_ref = CONF.baremetal.partition_image_ref
    wholedisk_image = False

    @test.idempotent_id('27b86130-d8dc-419d-880a-fbbbe4ce3f8c')
    @test.services('image', 'network', 'object_storage')
    def test_ip_access_to_server(self):
        self.ping_ip_address(self.node_ip, should_succeed=True)


class BaremetalPxeIpmitoolWholedisk(bsm.BaremetalStandaloneScenarioTest):

    driver = 'pxe_ipmitool'
    image_ref = CONF.baremetal.whole_disk_image_ref
    wholedisk_image = True

    @test.idempotent_id('d8c5badd-45db-4d05-bbe8-35babbed6e86')
    @test.services('image', 'network')
    def test_ip_access_to_server(self):
        self.ping_ip_address(self.node_ip, should_succeed=True)


class BaremetalPxeIpmitoolPartitioned(bsm.BaremetalStandaloneScenarioTest):

    driver = 'pxe_ipmitool'
    image_ref = CONF.baremetal.partition_image_ref
    wholedisk_image = False

    @test.idempotent_id('ea85e19c-6869-4577-b9bb-2eb150f77c90')
    @test.services('image', 'network')
    def test_ip_access_to_server(self):
        self.ping_ip_address(self.node_ip, should_succeed=True)


class BaremetalIpmiWholedisk(bsm.BaremetalStandaloneScenarioTest):

    driver = 'ipmi'
    image_ref = CONF.baremetal.whole_disk_image_ref
    wholedisk_image = True

    @test.idempotent_id('c2db24e7-07dc-4a20-8f93-d4efae2bfd4e')
    @test.services('image', 'network')
    def test_ip_access_to_server(self):
        self.ping_ip_address(self.node_ip, should_succeed=True)


class BaremetalIpmiPartitioned(bsm.BaremetalStandaloneScenarioTest):

    driver = 'ipmi'
    image_ref = CONF.baremetal.partition_image_ref
    wholedisk_image = False

    @test.idempotent_id('7d0b205e-edbc-4e2d-9f6d-95cd74eefecb')
    @test.services('image', 'network')
    def test_ip_access_to_server(self):
        self.ping_ip_address(self.node_ip, should_succeed=True)
