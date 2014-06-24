# Copyright 2014 Red Hat, Inc.
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

import time

import mock
from testtools.matchers import HasLength

from ironic.common import disk_partitioner
from ironic.common import utils
from ironic.tests import base


@mock.patch.object(time, 'sleep', lambda _: None)
@mock.patch.object(utils, 'execute', lambda _: None)
class DiskPartitionerTestCase(base.TestCase):

    def test_add_partition(self):
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        dp.add_partition(1024)
        dp.add_partition(512, fs_type='linux-swap')
        dp.add_partition(2048, bootable=True)
        expected = [(1, {'bootable': False,
                         'fs_type': '',
                         'type': 'primary',
                         'size': 1024}),
                    (2, {'bootable': False,
                         'fs_type': 'linux-swap',
                         'type': 'primary',
                         'size': 512}),
                    (3, {'bootable': True,
                         'fs_type': '',
                         'type': 'primary',
                         'size': 2048})]
        partitions = [(n, p) for n, p in dp.get_partitions()]
        self.assertThat(partitions, HasLength(3))
        self.assertEqual(expected, partitions)

    @mock.patch.object(disk_partitioner.DiskPartitioner, '_exec')
    def test_commit(self, mock_exec):
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        fake_parts = [(1, {'bootable': False,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (2, {'bootable': True,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1})]
        with mock.patch.object(dp, 'get_partitions') as mock_gp:
            mock_gp.return_value = fake_parts
            dp.commit()
        mock_exec.assert_called_once_with('mklabel', 'msdos',
                               'mkpart', 'fake-type', 'fake-fs-type', '1', '2',
                               'mkpart', 'fake-type', 'fake-fs-type', '2', '3',
                               'set', '2', 'boot', 'on')


@mock.patch.object(utils, 'execute')
class ListPartitionsTestCase(base.TestCase):

    def test_correct(self, execute_mock):
        output = """
BYT;
/dev/sda:500107862016B:scsi:512:4096:msdos:ATA HGST HTS725050A7:;
1:1.00MiB:501MiB:500MiB:ext4::boot;
2:501MiB:476940MiB:476439MiB:::;
"""
        expected = [
            {'start': 1, 'end': 501, 'size': 500,
             'filesystem': 'ext4', 'flags': 'boot'},
            {'start': 501, 'end': 476940, 'size': 476439,
             'filesystem': '', 'flags': ''},
        ]
        execute_mock.return_value = (output, '')
        result = disk_partitioner.list_partitions('/dev/fake')
        self.assertEqual(expected, result)
        execute_mock.assert_called_once_with(
            'parted', '-s', '-m', '/dev/fake', 'unit', 'MiB', 'print')

    @mock.patch.object(disk_partitioner.LOG, 'warn')
    def test_incorrect(self, log_mock, execute_mock):
        output = """
BYT;
/dev/sda:500107862016B:scsi:512:4096:msdos:ATA HGST HTS725050A7:;
1:XX1076MiB:---:524MiB:ext4::boot;
"""
        execute_mock.return_value = (output, '')
        self.assertEqual([], disk_partitioner.list_partitions('/dev/fake'))
        self.assertEqual(1, log_mock.call_count)
