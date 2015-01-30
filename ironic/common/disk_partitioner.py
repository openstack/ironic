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

import re

from oslo.config import cfg
from oslo_concurrency import processutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LW
from ironic.common import utils
from ironic.openstack.common import log as logging
from ironic.openstack.common import loopingcall

opts = [
    cfg.IntOpt('check_device_interval',
               default=1,
               help='After Ironic has completed creating the partition table, '
                    'it continues to check for activity on the attached iSCSI '
                    'device status at this interval prior to copying the image'
                    ' to the node, in seconds'),
    cfg.IntOpt('check_device_max_retries',
               default=20,
               help='The maximum number of times to check that the device is '
                    'not accessed by another process. If the device is still '
                    'busy after that, the disk partitioning will be treated as'
                    ' having failed.'),
]

CONF = cfg.CONF
opt_group = cfg.OptGroup(name='disk_partitioner',
                         title='Options for the disk partitioner')
CONF.register_group(opt_group)
CONF.register_opts(opts, opt_group)

LOG = logging.getLogger(__name__)


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
        self._fuser_pids_re = re.compile(r'((\d)+\s*)+')

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

    def _wait_for_disk_to_become_available(self, retries, max_retries, pids,
                                           stderr):
        retries[0] += 1
        if retries[0] > max_retries:
            raise loopingcall.LoopingCallDone()

        try:
            # NOTE(ifarkas): fuser returns a non-zero return code if none of
            #                the specified files is accessed
            out, err = utils.execute('fuser', self._device,
                                     check_exit_code=[0, 1], run_as_root=True)

            if not out and not err:
                raise loopingcall.LoopingCallDone()
            else:
                if err:
                    stderr[0] = err
                if out:
                    pids_match = re.search(self._fuser_pids_re, out)
                    pids[0] = pids_match.group()
        except processutils.ProcessExecutionError as exc:
            LOG.warning(_LW('Failed to check the device %(device)s with fuser:'
                            ' %(err)s'), {'device': self._device, 'err': exc})

    def commit(self):
        """Write to the disk."""
        LOG.debug("Committing partitions to disk.")
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

        retries = [0]
        pids = ['']
        fuser_err = ['']
        interval = CONF.disk_partitioner.check_device_interval
        max_retries = CONF.disk_partitioner.check_device_max_retries

        timer = loopingcall.FixedIntervalLoopingCall(
                    self._wait_for_disk_to_become_available,
                    retries, max_retries, pids, fuser_err)
        timer.start(interval=interval).wait()

        if retries[0] > max_retries:
            if pids[0]:
                raise exception.InstanceDeployFailure(
                    _('Disk partitioning failed on device %(device)s. '
                      'Processes with the following PIDs are holding it: '
                      '%(pids)s. Time out waiting for completion.')
                    % {'device': self._device, 'pids': pids[0]})
            else:
                raise exception.InstanceDeployFailure(
                    _('Disk partitioning failed on device %(device)s. Fuser '
                      'exited with "%(fuser_err)s". Time out waiting for '
                      'completion.')
                    % {'device': self._device, 'fuser_err': fuser_err[0]})


_PARTED_PRINT_RE = re.compile(r"^\d+:([\d\.]+)MiB:"
                              "([\d\.]+)MiB:([\d\.]+)MiB:(\w*)::(\w*)")


def list_partitions(device):
    """Get partitions information from given device.

    :param device: The device path.
    :returns: list of dictionaries (one per partition) with keys:
              start, end, size (in MiB), filesystem, flags
    """
    output = utils.execute(
        'parted', '-s', '-m', device, 'unit', 'MiB', 'print',
        use_standard_locale=True)[0]
    lines = [line for line in output.split('\n') if line.strip()][2:]
    # Example of line: 1:1.00MiB:501MiB:500MiB:ext4::boot
    fields = ('start', 'end', 'size', 'filesystem', 'flags')
    result = []
    for line in lines:
        match = _PARTED_PRINT_RE.match(line)
        if match is None:
            LOG.warn(_LW("Partition information from parted for device "
                         "%(device)s does not match "
                         "expected format: %(line)s"),
                     dict(device=device, line=line))
            continue
        # Cast int fields to ints (some are floats and we round them down)
        groups = [int(float(x)) if i < 3 else x
                  for i, x in enumerate(match.groups())]
        result.append(dict(zip(fields, groups)))
    return result
