#
# Copyright 2022 Red Hat, Inc.
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

import os
import tempfile

from ironic.common import dhcp_factory
from ironic.common import utils as common_utils
from ironic.conductor import task_manager
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


class TestDnsmasqDHCPApi(db_base.DbTestCase):

    def setUp(self):
        super(TestDnsmasqDHCPApi, self).setUp()
        self.config(dhcp_provider='dnsmasq',
                    group='dhcp')
        self.node = object_utils.create_test_node(self.context)

        self.ports = [
            object_utils.create_test_port(
                self.context, node_id=self.node.id, id=2,
                uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c782',
                address='52:54:00:cf:2d:32',
                pxe_enabled=True)]

        self.optsdir = tempfile.mkdtemp()
        self.addCleanup(lambda: common_utils.rmtree_without_raise(
                        self.optsdir))
        self.config(dhcp_optsdir=self.optsdir, group='dnsmasq')

        self.hostsdir = tempfile.mkdtemp()
        self.addCleanup(lambda: common_utils.rmtree_without_raise(
                        self.hostsdir))
        self.config(dhcp_hostsdir=self.hostsdir, group='dnsmasq')

        dhcp_factory.DHCPFactory._dhcp_provider = None
        self.api = dhcp_factory.DHCPFactory()
        self.opts = [
            {
                'ip_version': 4,
                'opt_name': '67',
                'opt_value': 'bootx64.efi'
            },
            {
                'ip_version': 4,
                'opt_name': '210',
                'opt_value': '/tftpboot/'
            },
            {
                'ip_version': 4,
                'opt_name': '66',
                'opt_value': '192.0.2.135',
            },
            {
                'ip_version': 4,
                'opt_name': '150',
                'opt_value': '192.0.2.135'
            },
            {
                'ip_version': 4,
                'opt_name': '255',
                'opt_value': '192.0.2.135'
            }
        ]

    def test_update_dhcp(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.api.update_dhcp(task, self.opts)

            dnsmasq_tag = task.node.driver_internal_info.get('dnsmasq_tag')
            self.assertEqual(36, len(dnsmasq_tag))

        hostfile = os.path.join(self.hostsdir,
                                'ironic-52:54:00:cf:2d:32.conf')
        with open(hostfile, 'r') as f:
            self.assertEqual(
                '52:54:00:cf:2d:32,set:%s,set:ironic\n' % dnsmasq_tag,
                f.readline())

        optsfile = os.path.join(self.optsdir,
                                'ironic-%s.conf' % self.node.uuid)
        with open(optsfile, 'r') as f:
            self.assertEqual([
                'tag:%s,67,bootx64.efi\n' % dnsmasq_tag,
                'tag:%s,210,/tftpboot/\n' % dnsmasq_tag,
                'tag:%s,66,192.0.2.135\n' % dnsmasq_tag,
                'tag:%s,150,192.0.2.135\n' % dnsmasq_tag,
                'tag:%s,255,192.0.2.135\n' % dnsmasq_tag],
                f.readlines())

    def test_get_ip_addresses(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            with tempfile.NamedTemporaryFile() as fp:
                self.config(dhcp_leasefile=fp.name, group='dnsmasq')
                fp.write(b"1659975057 52:54:00:cf:2d:32 192.0.2.198 * *\n")
                fp.flush()
                self.assertEqual(
                    ['192.0.2.198'],
                    self.api.provider.get_ip_addresses(task))

    def test_clean_dhcp_opts(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.api.update_dhcp(task, self.opts)

        hostfile = os.path.join(self.hostsdir,
                                'ironic-52:54:00:cf:2d:32.conf')
        optsfile = os.path.join(self.optsdir,
                                'ironic-%s.conf' % self.node.uuid)
        self.assertTrue(os.path.isfile(hostfile))
        self.assertTrue(os.path.isfile(optsfile))

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.api.clean_dhcp(task)

        # assert the host file remains with the ignore directive, and the opts
        # file is deleted
        with open(hostfile, 'r') as f:
            self.assertEqual(
                '52:54:00:cf:2d:32,ignore\n',
                f.readline())
        self.assertFalse(os.path.isfile(optsfile))
