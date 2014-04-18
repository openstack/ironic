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

from ironic.common import utils


class DiskPartitioner(object):

    def __init__(self, device, disk_label='msdos', alignment='optimal'):
        """A convenient wrapper around the parted tool.

        :param device: The device path.
        :param disk_label: The type of the partition table. Valid types are:
                           "bsd", "dvh", "gpt", "loop", "mac", "msdos",
                           "pc98", or "sun".
        :param alignment: Set alignment for newly created partitions.
                          Valid types are: none, cylinder, minimal and
                          optimal.

        """
        self._device = device
        self._disk_label = disk_label
        self._alignment = alignment
        self._partitions = []

    def _exec(self, *args):
        # NOTE(lucasagomes): utils.execute() is already a wrapper on top
        #                    of processutils.execute() which raises specific
        #                    exceptions. It also logs any failure so we don't
        #                    need to log it again here.
        utils.execute('parted', '-a', self._alignment, '-s', self._device,
                      '--', 'unit', 'MiB', *args, check_exit_code=[0],
                      run_as_root=True)

    def add_partition(self, size, part_type='primary', fs_type='',
                      bootable=False):
        """Add a partition.

        :param size: The size of the partition in MiB.
        :param part_type: The type of the partition. Valid values are:
                          primary, logical, or extended.
        :param fs_type: The filesystem type. Valid types are: ext2, fat32,
                        fat16, HFS, linux-swap, NTFS, reiserfs, ufs.
                        If blank (''), it will create a Linux native
                        partition (83).
        :param bootable: Boolean value; whether the partition is bootable
                         or not.
        :returns: The partition number.

        """
        self._partitions.append({'size': size,
                                 'type': part_type,
                                 'fs_type': fs_type,
                                 'bootable': bootable})
        return len(self._partitions)

    def get_partitions(self):
        """Get the partitioning layout.

        :returns: An iterator with the partition number and the
                  partition layout.

        """
        return enumerate(self._partitions, 1)

    def commit(self):
        """Write to the disk."""
        cmd_args = ['mklabel', self._disk_label]
        # NOTE(lucasagomes): Lead in with 1MiB to allow room for the
        #                    partition table itself.
        start = 1
        for num, part in self.get_partitions():
            end = start + part['size']
            cmd_args.extend(['mkpart', part['type'], part['fs_type'],
                             str(start), str(end)])
            if part['bootable']:
                cmd_args.extend(['set', str(num), 'boot', 'on'])
            start = end

        self._exec(*cmd_args)
        # TODO(lucasagomes): Do not sleep, use another mechanism to avoid
        #                    the "device is busy" problem. lsof, fuser...
        # avoid "device is busy"
        time.sleep(3)
