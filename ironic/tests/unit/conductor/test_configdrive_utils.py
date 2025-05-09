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

import base64
import gzip
import json
import os
import tempfile
from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import uuidutils
import pycdlib

from ironic.common import exception
from ironic.common import neutron
from ironic.conductor import configdrive_utils as cd_utils
from ironic.conductor import task_manager
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class MetadataUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(MetadataUtilsTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid())

    def test_is_invalid_network_metadata(self):
        """Test the known invalid state."""
        invalid = {'links': [], 'services': [], 'networks': []}
        self.assertTrue(cd_utils.is_invalid_network_metadata(invalid))

    def test_invalid_network_metadata_list(self):
        self.assertTrue(cd_utils.is_invalid_network_metadata([]))

    def test_is_invalid_network_metadata_valid(self):
        valid = {'links': [{'foo': 'bar', 'mtu': 1500}],
                 'services': [],
                 'networks': [{'bar': 'baz'}]}
        self.assertFalse(cd_utils.is_invalid_network_metadata(valid))

    def test_invalid_network_metadata_null_mtu(self):
        invalid = {'links': [{'mtu': None}],
                   'servies': [],
                   'networks': [{'foo': 'bar'}]}
        self.assertTrue(cd_utils.is_invalid_network_metadata(invalid))

    def test_invalid_network_metadata_null_mtu_disables(self):
        CONF.set_override('disable_metadata_mtu_check', True,
                          group='conductor')
        invalid = {'links': [{'mtu': None}],
                   'servies': [],
                   'networks': [{'foo': 'bar'}]}
        self.assertFalse(cd_utils.is_invalid_network_metadata(invalid))

    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_instance_network_data',
                       autospec=True)
    def test_generate_config_metadata(self, mock_gen, mock_valid):
        # Just enough to be something
        fake_data = {'foo': 'bar'}
        mock_gen.return_value = fake_data
        mock_valid.return_value = False
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            res = cd_utils.generate_config_metadata(task)
            mock_gen.assert_called_once_with(task)
        self.assertEqual(fake_data, res)
        mock_valid.assert_called_once_with(fake_data)

    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_instance_network_data',
                       autospec=True)
    def test_generate_config_metadata_none(self, mock_gen, mock_valid):
        # We don't expect None to ever be returned from
        # generate_instance_network_data, but just in case!
        mock_gen.return_value = None
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            self.assertRaises(
                exception.ConfigDriveRegenerationFailure,
                cd_utils.generate_config_metadata,
                task)
            mock_gen.assert_called_once_with(task)
        mock_valid.assert_called_once_with(None)

    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_instance_network_data',
                       autospec=True)
    def test_generate_config_metadata_invalid(self, mock_gen, mock_valid):
        fake_data = {'foo': 'bar'}
        mock_gen.return_value = fake_data
        mock_valid.return_value = True
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            self.assertRaises(
                exception.ConfigDriveRegenerationFailure,
                cd_utils.generate_config_metadata,
                task)
            mock_gen.assert_called_once_with(task)
        mock_valid.assert_called_once_with(fake_data)

    def test_generate_instance_network_data(self):
        # This is just a test which validates we pass through the method
        # as we expect with no vifs.
        self.node.network_interface = 'noop'
        self.node.save()
        expected_dict = {'links': [], 'networks': [], 'services': []}
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            self.assertNotIn('metadata', task.driver.network.capabilities)
            self.assertDictEqual(
                expected_dict,
                cd_utils.generate_instance_network_data(task))

    def test_generate_instance_network_data_no_vif(self):
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            self.assertEqual(
                {'links': [], 'networks': [], 'services': []},
                cd_utils.generate_instance_network_data(task))

    @mock.patch.object(neutron, 'get_neutron_port_data', autospec=True)
    def test_generate_instance_network_data_single_vif(self, mock_gnpd):
        port = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='86ffb399-6dd4-4e6c-8eb0-069d608bc5ca',
            internal_info={'tenant_vif_port_id': 'meep'})

        gnpd = {
            'links': [
                {
                    'id': port.uuid,
                    'type': 'vif',
                    'ethernet_mac_address': '01:02:03:04:05:06',
                    'vif_id': 'meep',
                    'mtu': 1500
                }
            ],
            'networks': [
                {
                    'id': "boop",
                    'network_id': "a8164a5e-ce7e-4ce4-b017-20c93a559f7c",
                    'type': 'ipv4',
                    'link': port.uuid,
                    'ip_address': "192.168.1.1",
                    'netmask': "255.255.255.0",
                    'routes': []
                }
            ],
            'services': []
        }
        mock_gnpd.return_value = gnpd
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            res = cd_utils.generate_instance_network_data(task)
            # NOTE(TheJulia): Normally, we would expect the method to
            # return slightly different data, specifically superseded
            # mac address and a phy, but the test here is the consolidation
            # of result data together.
            self.assertEqual(gnpd, res)
            mock_gnpd.assert_called_once_with(port.id, 'meep',
                                              mac_address='52:54:00:cf:2d:31',
                                              iface_type='phy')

    @mock.patch.object(neutron, 'get_neutron_port_data', autospec=True)
    def test_generate_instance_network_data_multi_vif(self, mock_gnpd):
        port1 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='86ffb399-6dd4-4e6c-8eb0-069d608bc5ca',
            internal_info={'tenant_vif_port_id': 'meep'})

        port2 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='373960ab-131f-4a37-8329-8cda768ba722',
            internal_info={'tenant_vif_port_id': 'beep'},
            address="51:54:00:cf:2d:32")

        gnpd1 = {
            'links': [
                {'id': port1.uuid,
                 'type': 'phy',
                 'ethernet_mac_address': port1.address,
                 'vif_id': 'meep',
                 'mtu': 1500}],
            'networks': [
                {'id': "boop",
                 'network_id': "a8164a5e-ce7e-4ce4-b017-20c93a559f7c",
                 'type': 'ipv4',
                 'link': port1.uuid,
                 'ip_address': "192.168.1.1",
                 'netmask': "255.255.255.0",
                 'routes': []}],
            'services': []
        }
        gnpd2 = {
            'links': [
                {'id': port2.uuid,
                 'type': 'phy',
                 'ethernet_mac_address': port2.address,
                 'vif_id': 'beep',
                 'mtu': 1500}],
            'networks': [
                {'id': "boop",
                 'network_id': "a8164a5e-ce7e-4ce4-b017-20c93a559f7c",
                 'type': 'ipv4',
                 'link': port2.uuid,
                 'ip_address': "192.168.1.2",
                 'netmask': "255.255.255.0",
                 'routes': []}],
            'services': [{"address": "8.8.8.8", "type": "dns"}]
        }

        expected = {
            'links': [
                {'ethernet_mac_address': '52:54:00:cf:2d:31',
                 'id': 'iface0',
                 'mtu': 1500,
                 'type': 'phy',
                 'vif_id': 'meep'},
                {'ethernet_mac_address': '51:54:00:cf:2d:32',
                 'id': 'iface1',
                 'mtu': 1500,
                 'type': 'phy',
                 'vif_id': 'beep'}],
            'networks': [
                {'id': 'boop',
                 'ip_address': '192.168.1.1',
                 'link': 'iface0',
                 'netmask': '255.255.255.0',
                 'network_id': 'a8164a5e-ce7e-4ce4-b017-20c93a559f7c',
                 'routes': [],
                 'type': 'ipv4'},
                {'id': 'boop',
                 'ip_address': '192.168.1.2',
                 'link': 'iface1',
                 'netmask': '255.255.255.0',
                 'network_id': 'a8164a5e-ce7e-4ce4-b017-20c93a559f7c',
                 'routes': [],
                 'type': 'ipv4'}],
            'services': [{'address': '8.8.8.8', 'type': 'dns'}]
        }

        mock_gnpd.side_effect = [gnpd1, gnpd2]
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            res = cd_utils.generate_instance_network_data(task)
            # NOTE(TheJulia): Normally, we would expect the method to
            # return slightly different data, specifically superseded
            # mac address and a phy, but the test here is the consolidation
            # of result data together.
            self.assertEqual(expected, res)
            mock_gnpd.assert_has_calls([
                mock.call(port1.id, 'meep',
                          mac_address=port1.address,
                          iface_type='phy'),
                mock.call(port2.id, 'beep',
                          mac_address=port2.address,
                          iface_type='phy')])

    @mock.patch.object(neutron, 'get_neutron_port_data', autospec=True)
    def test_generate_instance_network_data_portgroup(self, mock_gnpd):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            uuid='f52c664d-ca02-4c27-94f9-327dcb67d208',
            address='01:02:03:04:05:06',
            internal_info={'tenant_vif_port_id': 'meep'})

        port1 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='86ffb399-6dd4-4e6c-8eb0-069d608bc5ca',
            portgroup_id=pg.id)

        port2 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='373960ab-131f-4a37-8329-8cda768ba722',
            address="51:54:00:cf:2d:32",
            portgroup_id=pg.id)

        gnpd = {
            'links': [
                {'id': pg.uuid,
                 'type': 'phy',
                 'ethernet_mac_address': '01:02:03:04:05:06',
                 'vif_id': 'meep',
                 'mtu': 1500,
                 'bond_links': [port1.uuid, port2.uuid]},
                {'id': port1.uuid,
                 'type': 'phy',
                 'ethernet_mac_address': port1.address,
                 'mtu': 1500},
                {'id': port2.uuid,
                 'type': 'phy',
                 'ethernet_mac_address': port2.address,
                 'mtu': 1500}],
            'networks': [
                {'id': "boop",
                 'network_id': "a8164a5e-ce7e-4ce4-b017-20c93a559f7c",
                 'type': 'ipv4',
                 'link': pg.uuid,
                 'ip_address': "192.168.1.1",
                 'netmask': "255.255.255.0",
                 'routes': []}],
            'services': []
        }
        expected = {
            'links': [
                {'bond_links': ['iface1', 'iface2'],
                 'ethernet_mac_address': '01:02:03:04:05:06',
                 'id': 'iface0',
                 'mtu': 1500,
                 'type': 'phy',
                 'vif_id': 'meep'},
                {'ethernet_mac_address': '52:54:00:cf:2d:31',
                 'id': 'iface1',
                 'mtu': 1500,
                 'type': 'phy'},
                {'ethernet_mac_address': '51:54:00:cf:2d:32',
                 'id': 'iface2',
                 'mtu': 1500,
                 'type': 'phy'}],
            'networks': [{
                'id': 'boop',
                'ip_address': '192.168.1.1',
                'link': 'iface0',
                'netmask': '255.255.255.0',
                'network_id': 'a8164a5e-ce7e-4ce4-b017-20c93a559f7c',
                'routes': [],
                'type': 'ipv4'}],
            'services': []}

        mock_gnpd.return_value = gnpd
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            res = cd_utils.generate_instance_network_data(task)
            self.assertEqual(expected, res)
            mock_gnpd.assert_called_once_with(
                pg.id, 'meep',
                mac_address=pg.address,
                iface_type='bond',
                bond_links=[{'id': port1.uuid, 'type': 'phy',
                             'ethernet_mac_address': port1.address},
                            {'id': port2.uuid, 'type': 'phy',
                             'ethernet_mac_address': port2.address}])

    @mock.patch.object(neutron, 'get_neutron_port_data', autospec=True)
    def test_generate_instance_network_data_portgroups(self, mock_gnpd):
        pg1 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            uuid='f52c664d-ca02-4c27-94f9-327dcb67d208',
            address='01:02:03:04:05:06',
            internal_info={'tenant_vif_port_id': 'meep'})
        port1 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='86ffb399-6dd4-4e6c-8eb0-069d608bc5ca',
            portgroup_id=pg1.id)
        pg2 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            name='second', id=2,
            uuid='c1ef2f0b-36f8-45f6-9b0c-c68bd27beee1',
            address='00:02:03:04:05:07',
            internal_info={'tenant_vif_port_id': 'flop'})
        port2 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='373960ab-131f-4a37-8329-8cda768ba722',
            address="51:54:00:cf:2d:32",
            portgroup_id=pg2.id)

        gnpd = {
            'links': [
                {'id': pg1.uuid,
                 'type': 'phy',
                 'ethernet_mac_address': '01:02:03:04:05:06',
                 'vif_id': 'meep',
                 'mtu': 1500}],
            'networks': [
                {'id': "boop",
                 'network_id': "a8164a5e-ce7e-4ce4-b017-20c93a559f7c",
                 'type': 'ipv4',
                 'link': pg1.uuid,
                 'ip_address': "192.168.1.1",
                 'netmask': "255.255.255.0",
                 'routes': []}],
            'services': []
        }
        # Return something so the rest of the code loops properly
        mock_gnpd.return_value = gnpd
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            cd_utils.generate_instance_network_data(task)
            # NOTE(TheJulia): Not really concerned with the result, the
            # key aspect is to ensure we assembled the bond links correctly
            # from the available data. Other tests ensure the fields
            # get assembled together.
            mock_gnpd.assert_has_calls([
                mock.call(pg1.id, 'meep',
                          mac_address=pg1.address,
                          iface_type='bond',
                          bond_links=[
                              {'id': port1.uuid, 'type': 'phy',
                               'ethernet_mac_address': port1.address}]),
                mock.call(pg2.id, 'flop',
                          mac_address=pg2.address,
                          iface_type='bond',
                          bond_links=[
                              {'id': port2.uuid, 'type': 'phy',
                               'ethernet_mac_address': port2.address}])])

    @mock.patch.object(cd_utils, '_read_config_drive', autospec=True)
    @mock.patch.object(cd_utils, 'regenerate_iso',
                       autospec=True)
    @mock.patch.object(base64, 'b64decode', autospec=True)
    @mock.patch.object(gzip, 'decompress', autospec=True)
    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_config_metadata',
                       autospec=True)
    @mock.patch.object(tempfile, 'mkstemp', autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_check_and_patch_configdrive(
            self,
            mock_pycd, mock_remove,
            mock_temp, mock_mkstemp,
            mock_gen, mock_is_invalid,
            mock_decomp,
            mock_b64_decode,
            mock_regen,
            mock_read_iso):
        invalid_nd = json.dumps({'links': [], 'services': [], 'networks': []})
        mock_pycd.return_value.open_file_from_iso.return_value.__enter__. \
            return_value.read.return_value = invalid_nd
        mock_is_invalid.return_value = True
        mock_gen.return_value = {'foo': 'bar'}
        mock_regen.return_value = '{"foo": "bar"}'
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            cd_utils.check_and_patch_configdrive(task, 'foo')
        mock_regen.assert_called_once_with(
            mock.ANY, mock.ANY,
            {'/openstack/latest/network_data.json': mock.ANY},
            node_uuid=self.node.uuid)
        self.assertTrue(mock_remove.called)
        mock_temp.assert_called_once_with(dir=mock.ANY, mode='wb+')
        mock_mkstemp.assert_called_once_with(dir=mock.ANY)
        self.assertTrue(mock_b64_decode.called)
        self.assertTrue(mock_decomp.called)
        self.assertTrue(mock_is_invalid.called)
        mock_read_iso.assert_called_once_with(mock.ANY)

    @mock.patch.object(cd_utils, '_read_config_drive', autospec=True)
    @mock.patch.object(cd_utils, 'regenerate_iso',
                       autospec=True)
    @mock.patch.object(base64, 'b64decode', autospec=True)
    @mock.patch.object(gzip, 'decompress', autospec=True)
    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_config_metadata',
                       autospec=True)
    @mock.patch.object(tempfile, 'mkstemp', autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_check_and_patch_configdrive_invalid_nework_data(
            self,
            mock_pycd, mock_remove,
            mock_temp, mock_mkstemp,
            mock_gen, mock_is_valid,
            mock_decomp,
            mock_b64_decode,
            mock_regen,
            mock_read_iso):
        invalid_nd = '{"foo":...'
        mock_pycd.return_value.open_file_from_iso.return_value.__enter__. \
            return_value.read.return_value = invalid_nd
        mock_gen.return_value = {'foo': 'bar'}
        mock_regen.return_value = '{"foo": "bar"}'
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            cd_utils.check_and_patch_configdrive(task, 'foo')
        mock_regen.assert_called_once_with(
            mock.ANY, mock.ANY,
            {'/openstack/latest/network_data.json': mock.ANY},
            node_uuid=self.node.uuid)
        self.assertTrue(mock_remove.called)
        mock_temp.assert_called_once_with(dir=mock.ANY, mode='wb+')
        mock_mkstemp.assert_called_once_with(dir=mock.ANY)
        self.assertTrue(mock_b64_decode.called)
        self.assertTrue(mock_decomp.called)
        self.assertFalse(mock_is_valid.called)
        mock_read_iso.assert_called_once_with(mock.ANY)

    @mock.patch.object(cd_utils, '_read_config_drive', autospec=True)
    @mock.patch.object(cd_utils, 'regenerate_iso',
                       autospec=True)
    @mock.patch.object(base64, 'b64decode', autospec=True)
    @mock.patch.object(gzip, 'decompress', autospec=True)
    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_config_metadata',
                       autospec=True)
    @mock.patch.object(tempfile, 'mkstemp', autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_check_and_patch_configdrive_pycdlib_failure(
            self,
            mock_pycd, mock_remove,
            mock_temp, mock_mkstemp,
            mock_gen, mock_is_valid,
            mock_decomp,
            mock_b64_decode,
            mock_regen,
            mock_read_iso):
        mock_pycd.side_effect = \
            pycdlib.pycdlibexception.PyCdlibInvalidInput(msg='failure')
        mock_gen.return_value = {'foo': 'bar'}
        mock_regen.return_value = '{"foo": "bar"}'
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            cd_utils.check_and_patch_configdrive(task, 'foo')
        mock_regen.assert_not_called()
        mock_remove.assert_not_called()
        mock_temp.assert_called_once_with(dir=mock.ANY, mode='wb+')
        mock_mkstemp.assert_not_called()
        self.assertTrue(mock_b64_decode.called)
        self.assertTrue(mock_decomp.called)
        mock_is_valid.assert_not_called()
        mock_read_iso.assert_not_called()

    @mock.patch.object(cd_utils, '_read_config_drive', autospec=True)
    @mock.patch.object(cd_utils, 'regenerate_iso',
                       autospec=True)
    @mock.patch.object(base64, 'b64decode', autospec=True)
    @mock.patch.object(gzip, 'decompress', autospec=True)
    @mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                       autospec=True)
    @mock.patch.object(cd_utils, 'generate_config_metadata',
                       autospec=True)
    @mock.patch.object(tempfile, 'mkstemp', autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(pycdlib, 'PyCdlib', autospec=True)
    def test_check_and_patch_configdrive_metadata_gen_fail(
            self,
            mock_pycd, mock_remove,
            mock_temp, mock_mkstemp,
            mock_gen, mock_is_valid,
            mock_decomp,
            mock_b64_decode,
            mock_regen,
            mock_read_iso):
        invalid_nd = json.dumps({'links': [], 'services': [], 'networks': []})
        mock_pycd.return_value.open_file_from_iso.return_value.__enter__. \
            return_value.read.return_value = invalid_nd
        mock_is_valid.return_value = False
        mock_gen.side_effect = exception.ConfigDriveRegenerationFailure
        mock_regen.return_value = '{"foo": "bar"}'
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            cd_utils.check_and_patch_configdrive(task, 'foo')
        mock_regen.assert_not_called()
        mock_remove.assert_not_called()
        mock_temp.assert_called_once_with(dir=mock.ANY, mode='wb+')
        mock_mkstemp.assert_not_called()
        self.assertTrue(mock_b64_decode.called)
        self.assertTrue(mock_decomp.called)
        self.assertTrue(mock_is_valid.called)
        mock_read_iso.assert_not_called()

    @mock.patch('builtins.open', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(tempfile, 'TemporaryDirectory', autospec=True)
    @mock.patch.object(processutils, 'execute', autospec=True)
    def test_regenerate_iso(self, mock_exec, mock_tempdir, mock_mkdirs,
                            mock_open):
        fake_pycd = mock.Mock()
        fake_pycd.walk.return_value = [('/', ['path'], []),
                                       ('/path', [], ['file']),
                                       ('/path/path2', [], [])]
        fake_pycd.get_record.return_value = 'boop'
        fake_pycd.full_path_from_dirrecord.return_value = 'foo'
        mock_tempdir.return_value.__enter__.return_value = '/tmp/temp_folder'
        mock_write = mock.Mock()
        mock_open.return_value.__enter__.return_value.write = mock_write
        cd_utils.regenerate_iso(
            fake_pycd, '/tmp/foo_file', {'/path/foo.txt': 'meow'})
        mock_exec.assert_called_with(
            'mkisofs',
            '-o', '/tmp/foo_file',
            '-ldots',
            '-allow-lowercase',
            '-allow-multidot',
            '-l',
            '-publisher', 'Ironic',
            '-quiet', '-J', '-r',
            '-V', 'config-2',
            '/tmp/temp_folder', attempts=1)
        mock_mkdirs.assert_has_calls([
            mock.call('/tmp/temp_folder/path', exist_ok=True),
            mock.call('/tmp/temp_folder/path/path2', exist_ok=True)])
        mock_write.assert_has_calls([mock.call('meow')])
        mock_open.assert_called_once_with('/tmp/temp_folder/path/foo.txt',
                                          mode='w')
        fake_pycd.get_record.assert_has_calls([
            mock.call(rr_path='/path/file')])
        fake_pycd.full_path_from_dirrecord.assert_called_once_with(
            'boop', rockridge=True)


@mock.patch.object(cd_utils, 'is_invalid_network_metadata',
                   autospec=True)
@mock.patch.object(cd_utils, 'generate_config_metadata',
                   autospec=True)
@mock.patch.object(cd_utils, 'check_and_patch_configdrive',
                   autospec=True)
class PatchConfigDriveTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PatchConfigDriveTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               instance_info=None)
        self.bad_drive_dict = {
            'network_data': {
                'links': [],
                'networks': [],
                'services': []
            }
        }

        self.mock_network_data = {
            'links': [{'foo': 'bar'}],
            'networks': [{'bar': 'baz'}],
            'services': [],
        }

    def test_check_and_fix_configdrive_metadata(self, mock_cdp, mock_gen,
                                                mock_invalid):
        mock_invalid.return_value = True
        mock_gen.return_value = self.mock_network_data
        with task_manager.acquire(self.context, self.node.uuid) as task:
            res = cd_utils.check_and_fix_configdrive(
                task, self.bad_drive_dict)
            mock_gen.assert_called_once_with(task)
        mock_invalid.assert_called_once_with({
            'links': [], 'networks': [], 'services': []})
        mock_cdp.assert_not_called()
        self.assertEqual({'network_data': self.mock_network_data}, res)

    def test_check_and_fix_configdrive_string(self, mock_cdp, mock_gen,
                                              mock_invalid):
        mock_cdp.return_value = 'foo2'
        with task_manager.acquire(self.context, self.node.uuid) as task:
            res = cd_utils.check_and_fix_configdrive(task, 'foo')
            mock_cdp.assert_called_once_with(task, 'foo')
        mock_invalid.assert_not_called()
        mock_gen.assert_not_called()
        self.assertEqual('foo2', res)

    def test_check_and_fix_configdrive_string_url(
            self, mock_cdp, mock_gen,
            mock_invalid):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            res = cd_utils.check_and_fix_configdrive(
                task, 'https://bifrost/url')
            mock_cdp.assert_not_called()
        mock_invalid.assert_not_called()
        mock_gen.assert_not_called()
        self.assertEqual('https://bifrost/url', res)
