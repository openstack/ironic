# Copyright (c) 2012 NTT DOCOMO, INC.
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


import base64
import contextlib
import gzip
import math
import os
import re
import shutil
import socket
import stat
import tempfile
import time

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import units
import requests
import six
from six.moves.urllib import parse

from ironic.common import dhcp_factory
from ironic.common import disk_partitioner
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import image_service
from ironic.common import images
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils
from ironic import objects


deploy_opts = [
    cfg.IntOpt('efi_system_partition_size',
               default=200,
               help=_('Size of EFI system partition in MiB when configuring '
                      'UEFI systems for local boot.')),
    cfg.StrOpt('dd_block_size',
               default='1M',
               help=_('Block size to use when writing to the nodes disk.')),
    cfg.IntOpt('iscsi_verify_attempts',
               default=3,
               help=_('Maximum attempts to verify an iSCSI connection is '
                      'active, sleeping 1 second between attempts.')),
    cfg.StrOpt('http_url',
               help='ironic-conductor node\'s HTTP server URL. '
                    'Example: http://192.1.2.3:8080',
               deprecated_group='pxe'),
    cfg.StrOpt('http_root',
               default='/httpboot',
               help='ironic-conductor node\'s HTTP root path.',
               deprecated_group='pxe'),
    # TODO(rameshg87): Remove the deprecated names for the below two options in
    # Mitaka release.
    cfg.IntOpt('erase_devices_priority',
               deprecated_name='agent_erase_devices_priority',
               deprecated_group='agent',
               help=_('Priority to run in-band erase devices via the Ironic '
                      'Python Agent ramdisk. If unset, will use the priority '
                      'set in the ramdisk (defaults to 10 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('erase_devices_iterations',
               deprecated_name='agent_erase_devices_iterations',
               deprecated_group='agent',
               default=1,
               help=_('Number of iterations to be run for erasing devices.')),
]
CONF = cfg.CONF
CONF.register_opts(deploy_opts, group='deploy')

LOG = logging.getLogger(__name__)

VALID_ROOT_DEVICE_HINTS = set(('size', 'model', 'wwn', 'serial', 'vendor'))

SUPPORTED_CAPABILITIES = {
    'boot_option': ('local', 'netboot'),
    'boot_mode': ('bios', 'uefi'),
    'secure_boot': ('true', 'false'),
    'trusted_boot': ('true', 'false'),
}


# All functions are called from deploy() directly or indirectly.
# They are split for stub-out.

def discovery(portal_address, portal_port):
    """Do iSCSI discovery on portal."""
    utils.execute('iscsiadm',
                  '-m', 'discovery',
                  '-t', 'st',
                  '-p', '%s:%s' % (portal_address, portal_port),
                  run_as_root=True,
                  check_exit_code=[0],
                  attempts=5,
                  delay_on_retry=True)


def login_iscsi(portal_address, portal_port, target_iqn):
    """Login to an iSCSI target."""
    utils.execute('iscsiadm',
                  '-m', 'node',
                  '-p', '%s:%s' % (portal_address, portal_port),
                  '-T', target_iqn,
                  '--login',
                  run_as_root=True,
                  check_exit_code=[0],
                  attempts=5,
                  delay_on_retry=True)
    # Ensure the login complete
    verify_iscsi_connection(target_iqn)
    # force iSCSI initiator to re-read luns
    force_iscsi_lun_update(target_iqn)
    # ensure file system sees the block device
    check_file_system_for_iscsi_device(portal_address,
                                       portal_port,
                                       target_iqn)


def check_file_system_for_iscsi_device(portal_address,
                                       portal_port,
                                       target_iqn):
    """Ensure the file system sees the iSCSI block device."""
    check_dir = "/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-1" % (portal_address,
                                                               portal_port,
                                                               target_iqn)
    total_checks = CONF.deploy.iscsi_verify_attempts
    for attempt in range(total_checks):
        if os.path.exists(check_dir):
            break
        time.sleep(1)
        LOG.debug("iSCSI connection not seen by file system. Rechecking. "
                  "Attempt %(attempt)d out of %(total)d",
                  {"attempt": attempt + 1,
                   "total": total_checks})
    else:
        msg = _("iSCSI connection was not seen by the file system after "
                "attempting to verify %d times.") % total_checks
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)


def verify_iscsi_connection(target_iqn):
    """Verify iscsi connection."""
    LOG.debug("Checking for iSCSI target to become active.")

    for attempt in range(CONF.deploy.iscsi_verify_attempts):
        out, _err = utils.execute('iscsiadm',
                                  '-m', 'node',
                                  '-S',
                                  run_as_root=True,
                                  check_exit_code=[0])
        if target_iqn in out:
            break
        time.sleep(1)
        LOG.debug("iSCSI connection not active. Rechecking. Attempt "
                  "%(attempt)d out of %(total)d",
                  {"attempt": attempt + 1,
                   "total": CONF.deploy.iscsi_verify_attempts})
    else:
        msg = _("iSCSI connection did not become active after attempting to "
                "verify %d times.") % CONF.deploy.iscsi_verify_attempts
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)


def force_iscsi_lun_update(target_iqn):
    """force iSCSI initiator to re-read luns."""
    LOG.debug("Re-reading iSCSI luns.")

    utils.execute('iscsiadm',
                  '-m', 'node',
                  '-T', target_iqn,
                  '-R',
                  run_as_root=True,
                  check_exit_code=[0])


def logout_iscsi(portal_address, portal_port, target_iqn):
    """Logout from an iSCSI target."""
    utils.execute('iscsiadm',
                  '-m', 'node',
                  '-p', '%s:%s' % (portal_address, portal_port),
                  '-T', target_iqn,
                  '--logout',
                  run_as_root=True,
                  check_exit_code=[0],
                  attempts=5,
                  delay_on_retry=True)


def delete_iscsi(portal_address, portal_port, target_iqn):
    """Delete the iSCSI target."""
    # Retry delete until it succeeds (exit code 0) or until there is
    # no longer a target to delete (exit code 21).
    utils.execute('iscsiadm',
                  '-m', 'node',
                  '-p', '%s:%s' % (portal_address, portal_port),
                  '-T', target_iqn,
                  '-o', 'delete',
                  run_as_root=True,
                  check_exit_code=[0, 21],
                  attempts=5,
                  delay_on_retry=True)


def get_disk_identifier(dev):
    """Get the disk identifier from the disk being exposed by the ramdisk.

    This disk identifier is appended to the pxe config which will then be
    used by chain.c32 to detect the correct disk to chainload. This is helpful
    in deployments to nodes with multiple disks.

    http://www.syslinux.org/wiki/index.php/Comboot/chain.c32#mbr:

    :param dev: Path for the already populated disk device.
    :returns The Disk Identifier.
    """
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    disk_identifier = utils.execute('hexdump', '-s', '440', '-n', '4',
                                    '-e', '''\"0x%08x\"''',
                                    dev,
                                    run_as_root=True,
                                    check_exit_code=[0],
                                    attempts=5,
                                    delay_on_retry=True)
    return disk_identifier[0]


def make_partitions(dev, root_mb, swap_mb, ephemeral_mb,
                    configdrive_mb, node_uuid, commit=True,
                    boot_option="netboot", boot_mode="bios"):
    """Partition the disk device.

    Create partitions for root, swap, ephemeral and configdrive on a
    disk device.

    :param root_mb: Size of the root partition in mebibytes (MiB).
    :param swap_mb: Size of the swap partition in mebibytes (MiB). If 0,
        no partition will be created.
    :param ephemeral_mb: Size of the ephemeral partition in mebibytes (MiB).
        If 0, no partition will be created.
    :param configdrive_mb: Size of the configdrive partition in
        mebibytes (MiB). If 0, no partition will be created.
    :param commit: True/False. Default for this setting is True. If False
        partitions will not be written to disk.
    :param boot_option: Can be "local" or "netboot". "netboot" by default.
    :param boot_mode: Can be "bios" or "uefi". "bios" by default.
    :param node_uuid: Node's uuid. Used for logging.
    :returns: A dictionary containing the partition type as Key and partition
        path as Value for the partitions created by this method.

    """
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    LOG.debug("Starting to partition the disk device: %(dev)s "
              "for node %(node)s",
              {'dev': dev, 'node': node_uuid})
    part_template = dev + '-part%d'
    part_dict = {}

    # For uefi localboot, switch partition table to gpt and create the efi
    # system partition as the first partition.
    if boot_mode == "uefi" and boot_option == "local":
        dp = disk_partitioner.DiskPartitioner(dev, disk_label="gpt")
        part_num = dp.add_partition(CONF.deploy.efi_system_partition_size,
                                    fs_type='fat32',
                                    bootable=True)
        part_dict['efi system partition'] = part_template % part_num
    else:
        dp = disk_partitioner.DiskPartitioner(dev)

    if ephemeral_mb:
        LOG.debug("Add ephemeral partition (%(size)d MB) to device: %(dev)s "
                  "for node %(node)s",
                  {'dev': dev, 'size': ephemeral_mb, 'node': node_uuid})
        part_num = dp.add_partition(ephemeral_mb)
        part_dict['ephemeral'] = part_template % part_num
    if swap_mb:
        LOG.debug("Add Swap partition (%(size)d MB) to device: %(dev)s "
                  "for node %(node)s",
                  {'dev': dev, 'size': swap_mb, 'node': node_uuid})
        part_num = dp.add_partition(swap_mb, fs_type='linux-swap')
        part_dict['swap'] = part_template % part_num
    if configdrive_mb:
        LOG.debug("Add config drive partition (%(size)d MB) to device: "
                  "%(dev)s for node %(node)s",
                  {'dev': dev, 'size': configdrive_mb, 'node': node_uuid})
        part_num = dp.add_partition(configdrive_mb)
        part_dict['configdrive'] = part_template % part_num

    # NOTE(lucasagomes): Make the root partition the last partition. This
    # enables tools like cloud-init's growroot utility to expand the root
    # partition until the end of the disk.
    LOG.debug("Add root partition (%(size)d MB) to device: %(dev)s "
              "for node %(node)s",
              {'dev': dev, 'size': root_mb, 'node': node_uuid})
    part_num = dp.add_partition(root_mb, bootable=(boot_option == "local" and
                                                   boot_mode == "bios"))
    part_dict['root'] = part_template % part_num

    if commit:
        # write to the disk
        dp.commit()
    return part_dict


def is_block_device(dev):
    """Check whether a device is block or not."""
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    attempts = CONF.deploy.iscsi_verify_attempts
    for attempt in range(attempts):
        try:
            s = os.stat(dev)
        except OSError as e:
            LOG.debug("Unable to stat device %(dev)s. Attempt %(attempt)d "
                      "out of %(total)d. Error: %(err)s",
                      {"dev": dev, "attempt": attempt + 1,
                       "total": attempts, "err": e})
            time.sleep(1)
        else:
            return stat.S_ISBLK(s.st_mode)
    msg = _("Unable to stat device %(dev)s after attempting to verify "
            "%(attempts)d times.") % {'dev': dev, 'attempts': attempts}
    LOG.error(msg)
    raise exception.InstanceDeployFailure(msg)


def dd(src, dst):
    """Execute dd from src to dst."""
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    utils.dd(src, dst, 'bs=%s' % CONF.deploy.dd_block_size, 'oflag=direct')


def populate_image(src, dst):
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    data = images.qemu_img_info(src)
    if data.file_format == 'raw':
        dd(src, dst)
    else:
        images.convert_image(src, dst, 'raw', True)


def block_uuid(dev):
    """Get UUID of a block device."""
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    out, _err = utils.execute('blkid', '-s', 'UUID', '-o', 'value', dev,
                              run_as_root=True,
                              check_exit_code=[0])
    return out.strip()


def _replace_lines_in_file(path, regex_pattern, replacement):
    with open(path) as f:
        lines = f.readlines()

    compiled_pattern = re.compile(regex_pattern)
    with open(path, 'w') as f:
        for line in lines:
            line = compiled_pattern.sub(replacement, line)
            f.write(line)


def _replace_root_uuid(path, root_uuid):
    root = 'UUID=%s' % root_uuid
    pattern = r'(\(\(|\{\{) ROOT (\)\)|\}\})'
    _replace_lines_in_file(path, pattern, root)


def _replace_boot_line(path, boot_mode, is_whole_disk_image,
                       trusted_boot=False):
    if is_whole_disk_image:
        boot_disk_type = 'boot_whole_disk'
    elif trusted_boot:
        boot_disk_type = 'trusted_boot'
    else:
        boot_disk_type = 'boot_partition'

    if boot_mode == 'uefi':
        pattern = '^((set )?default)=.*$'
        boot_line = '\\1=%s' % boot_disk_type
    else:
        pxe_cmd = 'goto' if CONF.pxe.ipxe_enabled else 'default'
        pattern = '^%s .*$' % pxe_cmd
        boot_line = '%s %s' % (pxe_cmd, boot_disk_type)

    _replace_lines_in_file(path, pattern, boot_line)


def _replace_disk_identifier(path, disk_identifier):
    pattern = r'(\(\(|\{\{) DISK_IDENTIFIER (\)\)|\}\})'
    _replace_lines_in_file(path, pattern, disk_identifier)


def switch_pxe_config(path, root_uuid_or_disk_id, boot_mode,
                      is_whole_disk_image, trusted_boot=False):
    """Switch a pxe config from deployment mode to service mode.

    :param path: path to the pxe config file in tftpboot.
    :param root_uuid_or_disk_id: root uuid in case of partition image or
                                 disk_id in case of whole disk image.
    :param boot_mode: if boot mode is uefi or bios.
    :param is_whole_disk_image: if the image is a whole disk image or not.
    :param trusted_boot: if boot with trusted_boot or not. The usage of
        is_whole_disk_image and trusted_boot are mutually exclusive. You can
        have one or neither, but not both.
    """
    if not is_whole_disk_image:
        _replace_root_uuid(path, root_uuid_or_disk_id)
    else:
        _replace_disk_identifier(path, root_uuid_or_disk_id)

    _replace_boot_line(path, boot_mode, is_whole_disk_image, trusted_boot)


def notify(address, port):
    """Notify a node that it becomes ready to reboot."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((address, port))
        s.send('done')
    finally:
        s.close()


def get_dev(address, port, iqn, lun):
    """Returns a device path for given parameters."""
    dev = ("/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-%s"
           % (address, port, iqn, lun))
    return dev


def get_image_mb(image_path, virtual_size=True):
    """Get size of an image in Megabyte."""
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    mb = 1024 * 1024
    if not virtual_size:
        image_byte = os.path.getsize(image_path)
    else:
        image_byte = images.converted_size(image_path)
    # round up size to MB
    image_mb = int((image_byte + mb - 1) / mb)
    return image_mb


def get_dev_block_size(dev):
    """Get the device size in 512 byte sectors."""
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    block_sz, cmderr = utils.execute('blockdev', '--getsz', dev,
                                     run_as_root=True, check_exit_code=[0])
    return int(block_sz)


def destroy_disk_metadata(dev, node_uuid):
    """Destroy metadata structures on node's disk.

       Ensure that node's disk appears to be blank without zeroing the entire
       drive. To do this we will zero:
       - the first 18KiB to clear MBR / GPT data
       - the last 18KiB to clear GPT and other metadata like: LVM, veritas,
         MDADM, DMRAID, ...
    """
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib

    # NOTE(NobodyCam): This is needed to work around bug:
    # https://bugs.launchpad.net/ironic/+bug/1317647
    LOG.debug("Start destroy disk metadata for node %(node)s.",
              {'node': node_uuid})
    try:
        utils.dd('/dev/zero', dev, 'bs=512', 'count=36')
    except processutils.ProcessExecutionError as err:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Failed to erase beginning of disk for node "
                          "%(node)s. Command: %(command)s. Error: %(error)s."),
                      {'node': node_uuid,
                       'command': err.cmd,
                       'error': err.stderr})

    # now wipe the end of the disk.
    # get end of disk seek value
    try:
        block_sz = get_dev_block_size(dev)
    except processutils.ProcessExecutionError as err:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Failed to get disk block count for node %(node)s. "
                          "Command: %(command)s. Error: %(error)s."),
                      {'node': node_uuid,
                       'command': err.cmd,
                       'error': err.stderr})
    else:
        seek_value = block_sz - 36
        try:
            utils.dd('/dev/zero', dev, 'bs=512', 'count=36',
                     'seek=%d' % seek_value)
        except processutils.ProcessExecutionError as err:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to erase the end of the disk on node "
                              "%(node)s. Command: %(command)s. "
                              "Error: %(error)s."),
                          {'node': node_uuid,
                           'command': err.cmd,
                           'error': err.stderr})
    LOG.info(_LI("Disk metadata on %(dev)s successfully destroyed for node "
                 "%(node)s"), {'dev': dev, 'node': node_uuid})


def _get_configdrive(configdrive, node_uuid):
    """Get the information about size and location of the configdrive.

    :param configdrive: Base64 encoded Gzipped configdrive content or
        configdrive HTTP URL.
    :param node_uuid: Node's uuid. Used for logging.
    :raises: InstanceDeployFailure if it can't download or decode the
       config drive.
    :returns: A tuple with the size in MiB and path to the uncompressed
        configdrive file.

    """
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib
    # Check if the configdrive option is a HTTP URL or the content directly
    is_url = utils.is_http_url(configdrive)
    if is_url:
        try:
            data = requests.get(configdrive).content
        except requests.exceptions.RequestException as e:
            raise exception.InstanceDeployFailure(
                _("Can't download the configdrive content for node %(node)s "
                  "from '%(url)s'. Reason: %(reason)s") %
                {'node': node_uuid, 'url': configdrive, 'reason': e})
    else:
        data = configdrive

    try:
        data = six.BytesIO(base64.b64decode(data))
    except TypeError:
        error_msg = (_('Config drive for node %s is not base64 encoded '
                       'or the content is malformed.') % node_uuid)
        if is_url:
            error_msg += _(' Downloaded from "%s".') % configdrive
        raise exception.InstanceDeployFailure(error_msg)

    configdrive_file = tempfile.NamedTemporaryFile(delete=False,
                                                   prefix='configdrive',
                                                   dir=CONF.tempdir)
    configdrive_mb = 0
    with gzip.GzipFile('configdrive', 'rb', fileobj=data) as gunzipped:
        try:
            shutil.copyfileobj(gunzipped, configdrive_file)
        except EnvironmentError as e:
            # Delete the created file
            utils.unlink_without_raise(configdrive_file.name)
            raise exception.InstanceDeployFailure(
                _('Encountered error while decompressing and writing '
                  'config drive for node %(node)s. Error: %(exc)s') %
                {'node': node_uuid, 'exc': e})
        else:
            # Get the file size and convert to MiB
            configdrive_file.seek(0, os.SEEK_END)
            bytes_ = configdrive_file.tell()
            configdrive_mb = int(math.ceil(float(bytes_) / units.Mi))
        finally:
            configdrive_file.close()

        return (configdrive_mb, configdrive_file.name)


def work_on_disk(dev, root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                 image_path, node_uuid, preserve_ephemeral=False,
                 configdrive=None, boot_option="netboot",
                 boot_mode="bios"):
    """Create partitions and copy an image to the root partition.

    :param dev: Path for the device to work on.
    :param root_mb: Size of the root partition in megabytes.
    :param swap_mb: Size of the swap partition in megabytes.
    :param ephemeral_mb: Size of the ephemeral partition in megabytes. If 0,
        no ephemeral partition will be created.
    :param ephemeral_format: The type of file system to format the ephemeral
        partition.
    :param image_path: Path for the instance's disk image.
    :param node_uuid: node's uuid. Used for logging.
    :param preserve_ephemeral: If True, no filesystem is written to the
        ephemeral block device, preserving whatever content it had (if the
        partition table has not changed).
    :param configdrive: Optional. Base64 encoded Gzipped configdrive content
                        or configdrive HTTP URL.
    :param boot_option: Can be "local" or "netboot". "netboot" by default.
    :param boot_mode: Can be "bios" or "uefi". "bios" by default.
    :returns: a dictionary containing the following keys:
        'root uuid': UUID of root partition
        'efi system partition uuid': UUID of the uefi system partition
                                     (if boot mode is uefi).
        NOTE: If key exists but value is None, it means partition doesn't
              exist.
    """
    # NOTE(jlvillal): This function has been moved to ironic-lib. And is
    # planned to be deleted here. If need to modify this function, please also
    # do the same modification in ironic-lib

    # the only way for preserve_ephemeral to be set to true is if we are
    # rebuilding an instance with --preserve_ephemeral.
    commit = not preserve_ephemeral
    # now if we are committing the changes to disk clean first.
    if commit:
        destroy_disk_metadata(dev, node_uuid)

    try:
        # If requested, get the configdrive file and determine the size
        # of the configdrive partition
        configdrive_mb = 0
        configdrive_file = None
        if configdrive:
            configdrive_mb, configdrive_file = _get_configdrive(configdrive,
                                                                node_uuid)

        part_dict = make_partitions(dev, root_mb, swap_mb, ephemeral_mb,
                                    configdrive_mb, node_uuid,
                                    commit=commit,
                                    boot_option=boot_option,
                                    boot_mode=boot_mode)
        LOG.info(_LI("Successfully completed the disk device"
                     " %(dev)s partitioning for node %(node)s"),
                 {'dev': dev, "node": node_uuid})

        ephemeral_part = part_dict.get('ephemeral')
        swap_part = part_dict.get('swap')
        configdrive_part = part_dict.get('configdrive')
        root_part = part_dict.get('root')

        if not is_block_device(root_part):
            raise exception.InstanceDeployFailure(
                _("Root device '%s' not found") % root_part)

        for part in ('swap', 'ephemeral', 'configdrive',
                     'efi system partition'):
            part_device = part_dict.get(part)
            LOG.debug("Checking for %(part)s device (%(dev)s) on node "
                      "%(node)s.",
                      {'part': part, 'dev': part_device, 'node': node_uuid})
            if part_device and not is_block_device(part_device):
                raise exception.InstanceDeployFailure(
                    _("'%(partition)s' device '%(part_device)s' not found") %
                    {'partition': part, 'part_device': part_device})

        # If it's a uefi localboot, then we have created the efi system
        # partition.  Create a fat filesystem on it.
        if boot_mode == "uefi" and boot_option == "local":
            efi_system_part = part_dict.get('efi system partition')
            utils.mkfs('vfat', efi_system_part, 'efi-part')

        if configdrive_part:
            # Copy the configdrive content to the configdrive partition
            dd(configdrive_file, configdrive_part)
            LOG.info(_LI("Configdrive for node %(node)s successfully copied "
                         "onto partition %(partition)s"),
                     {'node': node_uuid, 'partition': configdrive_part})

    finally:
        # If the configdrive was requested make sure we delete the file
        # after copying the content to the partition
        if configdrive_file:
            utils.unlink_without_raise(configdrive_file)

    populate_image(image_path, root_part)
    LOG.info(_LI("Image for %(node)s successfully populated"),
             {'node': node_uuid})

    if swap_part:
        utils.mkfs('swap', swap_part, 'swap1')
        LOG.info(_LI("Swap partition %(swap)s successfully formatted "
                     "for node %(node)s"),
                 {'swap': swap_part, 'node': node_uuid})

    if ephemeral_part and not preserve_ephemeral:
        utils.mkfs(ephemeral_format, ephemeral_part, "ephemeral0")
        LOG.info(_LI("Ephemeral partition %(ephemeral)s successfully "
                     "formatted for node %(node)s"),
                 {'ephemeral': ephemeral_part, 'node': node_uuid})

    uuids_to_return = {
        'root uuid': root_part,
        'efi system partition uuid': part_dict.get('efi system partition')
    }

    try:
        for part, part_dev in uuids_to_return.items():
            if part_dev:
                uuids_to_return[part] = block_uuid(part_dev)

    except processutils.ProcessExecutionError:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Failed to detect %s"), part)

    return uuids_to_return


def deploy_partition_image(
        address, port, iqn, lun, image_path,
        root_mb, swap_mb, ephemeral_mb, ephemeral_format, node_uuid,
        preserve_ephemeral=False, configdrive=None,
        boot_option="netboot", boot_mode="bios"):
    """All-in-one function to deploy a partition image to a node.

    :param address: The iSCSI IP address.
    :param port: The iSCSI port number.
    :param iqn: The iSCSI qualified name.
    :param lun: The iSCSI logical unit number.
    :param image_path: Path for the instance's disk image.
    :param root_mb: Size of the root partition in megabytes.
    :param swap_mb: Size of the swap partition in megabytes.
    :param ephemeral_mb: Size of the ephemeral partition in megabytes. If 0,
        no ephemeral partition will be created.
    :param ephemeral_format: The type of file system to format the ephemeral
        partition.
    :param node_uuid: node's uuid. Used for logging.
    :param preserve_ephemeral: If True, no filesystem is written to the
        ephemeral block device, preserving whatever content it had (if the
        partition table has not changed).
    :param configdrive: Optional. Base64 encoded Gzipped configdrive content
                        or configdrive HTTP URL.
    :param boot_option: Can be "local" or "netboot". "netboot" by default.
    :param boot_mode: Can be "bios" or "uefi". "bios" by default.
    :raises: InstanceDeployFailure if image virtual size is bigger than root
        partition size.
    :returns: a dictionary containing the following keys:
        'root uuid': UUID of root partition
        'efi system partition uuid': UUID of the uefi system partition
                                     (if boot mode is uefi).
        NOTE: If key exists but value is None, it means partition doesn't
              exist.
    """
    image_mb = get_image_mb(image_path)
    if image_mb > root_mb:
        msg = (_('Root partition is too small for requested image. Image '
                 'virtual size: %(image_mb)d MB, Root size: %(root_mb)d MB')
               % {'image_mb': image_mb, 'root_mb': root_mb})
        raise exception.InstanceDeployFailure(msg)

    with _iscsi_setup_and_handle_errors(address, port, iqn, lun) as dev:
        uuid_dict_returned = work_on_disk(
            dev, root_mb, swap_mb, ephemeral_mb, ephemeral_format, image_path,
            node_uuid, preserve_ephemeral=preserve_ephemeral,
            configdrive=configdrive, boot_option=boot_option,
            boot_mode=boot_mode)

    return uuid_dict_returned


def deploy_disk_image(address, port, iqn, lun,
                      image_path, node_uuid):
    """All-in-one function to deploy a whole disk image to a node.

    :param address: The iSCSI IP address.
    :param port: The iSCSI port number.
    :param iqn: The iSCSI qualified name.
    :param lun: The iSCSI logical unit number.
    :param image_path: Path for the instance's disk image.
    :param node_uuid: node's uuid. Used for logging. Currently not in use
        by this function but could be used in the future.
    :returns: a dictionary containing the key 'disk identifier' to identify
        the disk which was used for deployment.
    """
    with _iscsi_setup_and_handle_errors(address, port, iqn,
                                        lun) as dev:
        populate_image(image_path, dev)
        disk_identifier = get_disk_identifier(dev)

    return {'disk identifier': disk_identifier}


@contextlib.contextmanager
def _iscsi_setup_and_handle_errors(address, port, iqn, lun):
    """Function that yields an iSCSI target device to work on.

    :param address: The iSCSI IP address.
    :param port: The iSCSI port number.
    :param iqn: The iSCSI qualified name.
    :param lun: The iSCSI logical unit number.
    """
    dev = get_dev(address, port, iqn, lun)
    discovery(address, port)
    login_iscsi(address, port, iqn)
    if not is_block_device(dev):
        raise exception.InstanceDeployFailure(_("Parent device '%s' not found")
                                              % dev)
    try:
        yield dev
    except processutils.ProcessExecutionError as err:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Deploy to address %s failed."), address)
            LOG.error(_LE("Command: %s"), err.cmd)
            LOG.error(_LE("StdOut: %r"), err.stdout)
            LOG.error(_LE("StdErr: %r"), err.stderr)
    except exception.InstanceDeployFailure as e:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Deploy to address %s failed."), address)
            LOG.error(e)
    finally:
        logout_iscsi(address, port, iqn)
        delete_iscsi(address, port, iqn)


def notify_ramdisk_to_proceed(address):
    """Notifies the ramdisk waiting for instructions from Ironic.

    DIB ramdisk (from init script) makes vendor passhthrus and listens
    on port 10000 for Ironic to notify back the completion of the task.
    This method connects to port 10000 of the bare metal running the
    ramdisk and then sends some data to notify the ramdisk to proceed
    with it's next task.

    :param address: The IP address of the node.
    """
    # Ensure the node started netcat on the port after POST the request.
    time.sleep(3)
    notify(address, 10000)


def check_for_missing_params(info_dict, error_msg, param_prefix=''):
    """Check for empty params in the provided dictionary.

    :param info_dict: The dictionary to inspect.
    :param error_msg: The error message to prefix before printing the
        information about missing parameters.
    :param param_prefix: Add this prefix to each parameter for error messages
    :raises: MissingParameterValue, if one or more parameters are
        empty in the provided dictionary.
    """
    missing_info = []
    for label, value in info_dict.items():
        if not value:
            missing_info.append(param_prefix + label)

    if missing_info:
        exc_msg = _("%(error_msg)s. Missing are: %(missing_info)s")
        raise exception.MissingParameterValue(
            exc_msg % {'error_msg': error_msg, 'missing_info': missing_info})


def fetch_images(ctx, cache, images_info, force_raw=True):
    """Check for available disk space and fetch images using ImageCache.

    :param ctx: context
    :param cache: ImageCache instance to use for fetching
    :param images_info: list of tuples (image href, destination path)
    :param force_raw: boolean value, whether to convert the image to raw
                      format
    :raises: InstanceDeployFailure if unable to find enough disk space
    """

    try:
        image_cache.clean_up_caches(ctx, cache.master_dir, images_info)
    except exception.InsufficientDiskSpace as e:
        raise exception.InstanceDeployFailure(reason=e)

    # NOTE(dtantsur): This code can suffer from race condition,
    # if disk space is used between the check and actual download.
    # This is probably unavoidable, as we can't control other
    # (probably unrelated) processes
    for href, path in images_info:
        cache.fetch_image(href, path, ctx=ctx, force_raw=force_raw)


def set_failed_state(task, msg):
    """Sets the deploy status as failed with relevant messages.

    This method sets the deployment as fail with the given message.
    It sets node's provision_state to DEPLOYFAIL and updates last_error
    with the given error message. It also powers off the baremetal node.

    :param task: a TaskManager instance containing the node to act on.
    :param msg: the message to set in last_error of the node.
    """
    node = task.node
    try:
        task.process_event('fail')
    except exception.InvalidState:
        msg2 = (_LE('Internal error. Node %(node)s in provision state '
                    '"%(state)s" could not transition to a failed state.')
                % {'node': node.uuid, 'state': node.provision_state})
        LOG.exception(msg2)

    try:
        manager_utils.node_power_action(task, states.POWER_OFF)
    except Exception:
        msg2 = (_LE('Node %s failed to power off while handling deploy '
                    'failure. This may be a serious condition. Node '
                    'should be removed from Ironic or put in maintenance '
                    'mode until the problem is resolved.') % node.uuid)
        LOG.exception(msg2)

    # NOTE(deva): node_power_action() erases node.last_error
    #             so we need to set it here.
    node.last_error = msg
    node.save()


def get_single_nic_with_vif_port_id(task):
    """Returns the MAC address of a port which has a VIF port id.

    :param task: a TaskManager instance containing the ports to act on.
    :returns: MAC address of the port connected to deployment network.
              None if it cannot find any port with vif id.
    """
    for port in task.ports:
        if port.extra.get('vif_port_id'):
            return port.address


def parse_instance_info_capabilities(node):
    """Parse the instance_info capabilities.

    One way of having these capabilities set is via Nova, where the
    capabilities are defined in the Flavor extra_spec and passed to
    Ironic by the Nova Ironic driver.

    NOTE: Although our API fully supports JSON fields, to maintain the
    backward compatibility with Juno the Nova Ironic driver is sending
    it as a string.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: A dictionary with the capabilities if found, otherwise an
              empty dictionary.
    """

    def parse_error():
        error_msg = (_('Error parsing capabilities from Node %s instance_info '
                       'field. A dictionary or a "jsonified" dictionary is '
                       'expected.') % node.uuid)
        raise exception.InvalidParameterValue(error_msg)

    capabilities = node.instance_info.get('capabilities', {})
    if isinstance(capabilities, six.string_types):
        try:
            capabilities = jsonutils.loads(capabilities)
        except (ValueError, TypeError):
            parse_error()

    if not isinstance(capabilities, dict):
        parse_error()

    return capabilities


def agent_get_clean_steps(task, interface=None, override_priorities=None):
    """Get the list of clean steps from the agent.

    #TODO(JoshNang) move to BootInterface

    :param task: a TaskManager object containing the node
    :param interface: The interface for which clean steps
        are to be returned. If this is not provided, it returns the
        clean steps for all interfaces.
    :param override_priorities: a dictionary with keys being step names and
        values being new priorities for them. If a step isn't in this
        dictionary, the step's original priority is used.
    :raises: NodeCleaningFailure if the agent returns invalid results
    :returns: A list of clean step dictionaries
    """
    override_priorities = override_priorities or {}
    client = agent_client.AgentClient()
    ports = objects.Port.list_by_node_id(
        task.context, task.node.id)
    result = client.get_clean_steps(task.node, ports).get('command_result')

    if ('clean_steps' not in result or
            'hardware_manager_version' not in result):
        raise exception.NodeCleaningFailure(_(
            'get_clean_steps for node %(node)s returned invalid result:'
            ' %(result)s') % ({'node': task.node.uuid, 'result': result}))

    driver_internal_info = task.node.driver_internal_info
    driver_internal_info['hardware_manager_version'] = result[
        'hardware_manager_version']
    task.node.driver_internal_info = driver_internal_info
    task.node.save()

    # Clean steps looks like {'HardwareManager': [{step1},{steps2}..]..}
    # Flatten clean steps into one list
    steps_list = [step for step_list in
                  result['clean_steps'].values()
                  for step in step_list]
    result = []
    for step in steps_list:
        if interface and step.get('interface') != interface:
            continue
        new_priority = override_priorities.get(step.get('step'))
        if new_priority is not None:
            step['priority'] = new_priority
        result.append(step)

    return result


def agent_execute_clean_step(task, step):
    """Execute a clean step asynchronously on the agent.

    #TODO(JoshNang) move to BootInterface

    :param task: a TaskManager object containing the node
    :param step: a clean step dictionary to execute
    :raises: NodeCleaningFailure if the agent does not return a command status
    :returns: states.CLEANWAIT to signify the step will be completed async
    """
    client = agent_client.AgentClient()
    ports = objects.Port.list_by_node_id(
        task.context, task.node.id)
    result = client.execute_clean_step(step, task.node, ports)
    if not result.get('command_status'):
        raise exception.NodeCleaningFailure(_(
            'Agent on node %(node)s returned bad command result: '
            '%(result)s') % {'node': task.node.uuid,
                             'result': result.get('command_error')})
    return states.CLEANWAIT


def agent_add_clean_params(task):
    """Add required config parameters to node's driver_interal_info.

    Adds the required conf options to node's driver_internal_info.
    It is Required to pass the information to IPA.

    :param task: a TaskManager instance.
    """
    info = task.node.driver_internal_info
    passes = CONF.deploy.erase_devices_iterations
    info['agent_erase_devices_iterations'] = passes
    task.node.driver_internal_info = info
    task.node.save()


def try_set_boot_device(task, device, persistent=True):
    """Tries to set the boot device on the node.

    This method tries to set the boot device on the node to the given
    boot device.  Under uefi boot mode, setting of boot device may differ
    between different machines. IPMI does not work for setting boot
    devices in uefi mode for certain machines.  This method ignores the
    expected IPMI failure for uefi boot mode and just logs a message.
    In error cases, it is expected the operator has to manually set the
    node to boot from the correct device.

    :param task: a TaskManager object containing the node
    :param device: the boot device
    :param persistent: Whether to set the boot device persistently
    :raises: Any exception from set_boot_device except IPMIFailure
        (setting of boot device using ipmi is expected to fail).
    """
    try:
        manager_utils.node_set_boot_device(task, device,
                                           persistent=persistent)
    except exception.IPMIFailure:
        if get_boot_mode_for_deploy(task.node) == 'uefi':
            LOG.warning(_LW("ipmitool is unable to set boot device while "
                            "the node %s is in UEFI boot mode. Please set "
                            "the boot device manually.") % task.node.uuid)
        else:
            raise


def parse_root_device_hints(node):
    """Parse the root_device property of a node.

    Parse the root_device property of a node and make it a flat string
    to be passed via the PXE config.

    :param node: a single Node.
    :returns: A flat string with the following format
              opt1=value1,opt2=value2. Or None if the
              Node contains no hints.
    :raises: InvalidParameterValue, if some information is invalid.

    """
    root_device = node.properties.get('root_device')
    if not root_device:
        return

    # Find invalid hints for logging
    invalid_hints = set(root_device) - VALID_ROOT_DEVICE_HINTS
    if invalid_hints:
        raise exception.InvalidParameterValue(
            _('The hints "%(invalid_hints)s" are invalid. '
              'Valid hints are: "%(valid_hints)s"') %
            {'invalid_hints': ', '.join(invalid_hints),
             'valid_hints': ', '.join(VALID_ROOT_DEVICE_HINTS)})

    if 'size' in root_device:
        try:
            int(root_device['size'])
        except ValueError:
            raise exception.InvalidParameterValue(
                _('Root device hint "size" is not an integer value.'))

    hints = []
    for key, value in root_device.items():
        # NOTE(lucasagomes): We can't have spaces in the PXE config
        # file, so we are going to url/percent encode the value here
        # and decode on the other end.
        if isinstance(value, six.string_types):
            value = value.strip()
            value = parse.quote(value)

        hints.append("%s=%s" % (key, value))

    return ','.join(hints)


def is_secure_boot_requested(node):
    """Returns True if secure_boot is requested for deploy.

    This method checks node property for secure_boot and returns True
    if it is requested.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: True if secure_boot is requested.
    """

    capabilities = parse_instance_info_capabilities(node)
    sec_boot = capabilities.get('secure_boot', 'false').lower()

    return sec_boot == 'true'


def is_trusted_boot_requested(node):
    """Returns True if trusted_boot is requested for deploy.

    This method checks instance property for trusted_boot and returns True
    if it is requested.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: True if trusted_boot is requested.
    """

    capabilities = parse_instance_info_capabilities(node)
    trusted_boot = capabilities.get('trusted_boot', 'false').lower()

    return trusted_boot == 'true'


def get_boot_mode_for_deploy(node):
    """Returns the boot mode that would be used for deploy.

    This method returns boot mode to be used for deploy.
    It returns 'uefi' if 'secure_boot' is set to 'true' or returns 'bios' if
    'trusted_boot' is set to 'true' in 'instance_info/capabilities' of node.
    Otherwise it returns value of 'boot_mode' in 'properties/capabilities'
    of node if set. If that is not set, it returns boot mode in
    'instance_info/deploy_boot_mode' for the node.
    It would return None if boot mode is present neither in 'capabilities' of
    node 'properties' nor in node's 'instance_info' (which could also be None).

    :param node: an ironic node object.
    :returns: 'bios', 'uefi' or None
    """

    if is_secure_boot_requested(node):
        LOG.debug('Deploy boot mode is uefi for %s.', node.uuid)
        return 'uefi'

    if is_trusted_boot_requested(node):
        # TODO(lintan) Trusted boot also supports uefi, but at the moment,
        # it should only boot with bios.
        LOG.debug('Deploy boot mode is bios for %s.', node.uuid)
        return 'bios'

    boot_mode = driver_utils.get_node_capability(node, 'boot_mode')
    if boot_mode is None:
        instance_info = node.instance_info
        boot_mode = instance_info.get('deploy_boot_mode')

    LOG.debug('Deploy boot mode is %(boot_mode)s for %(node)s.',
              {'boot_mode': boot_mode, 'node': node.uuid})

    return boot_mode.lower() if boot_mode else boot_mode


def validate_capabilities(node):
    """Validates that specified supported capabilities have valid value

    This method checks if the any of the supported capability is present in
    Node capabilities. For all supported capabilities specified for a Node,
    it validates that it has a valid value.
    The node can have capability as part of the 'properties' or
    'instance_info' or both.
    Note that the actual value of a capability does not need to be the same
    in the node's 'properties' and 'instance_info'.

    :param node: an ironic node object.
    :raises: InvalidParameterValue, if the capability is not set to a
        valid value.
    """
    exp_str = _("The parameter '%(capability)s' from %(field)s has an "
                "invalid value: '%(value)s'. Acceptable values are: "
                "%(valid_values)s.")

    for capability_name, valid_values in SUPPORTED_CAPABILITIES.items():
        # Validate capability_name in node's properties/capabilities
        value = driver_utils.get_node_capability(node, capability_name)
        if value and (value not in valid_values):
            field = "properties/capabilities"
            raise exception.InvalidParameterValue(
                exp_str %
                {'capability': capability_name, 'field': field,
                 'value': value, 'valid_values': ', '.join(valid_values)})

        # Validate capability_name in node's instance_info/['capabilities']
        capabilities = parse_instance_info_capabilities(node)
        value = capabilities.get(capability_name)

        if value and (value not in valid_values):
            field = "instance_info['capabilities']"
            raise exception.InvalidParameterValue(
                exp_str %
                {'capability': capability_name, 'field': field,
                 'value': value, 'valid_values': ', '.join(valid_values)})


def validate_image_properties(ctx, deploy_info, properties):
    """Validate the image.

    For Glance images it checks that the image exists in Glance and its
    properties or deployment info contain the properties passed. If it's not a
    Glance image, it checks that deployment info contains needed properties.

    :param ctx: security context
    :param deploy_info: the deploy_info to be validated
    :param properties: the list of image meta-properties to be validated.
    :raises: InvalidParameterValue if:
        * connection to glance failed;
        * authorization for accessing image failed;
        * HEAD request to image URL failed or returned response code != 200;
        * HEAD request response does not contain Content-Length header;
        * the protocol specified in image URL is not supported.
    :raises: MissingParameterValue if the image doesn't contain
        the mentioned properties.
    """
    image_href = deploy_info['image_source']
    try:
        img_service = image_service.get_image_service(image_href, context=ctx)
        image_props = img_service.show(image_href)['properties']
    except (exception.GlanceConnectionFailed,
            exception.ImageNotAuthorized,
            exception.Invalid):
        raise exception.InvalidParameterValue(_(
            "Failed to connect to Glance to get the properties "
            "of the image %s") % image_href)
    except exception.ImageNotFound:
        raise exception.InvalidParameterValue(_(
            "Image %s can not be found.") % image_href)
    except exception.ImageRefValidationFailed as e:
        raise exception.InvalidParameterValue(e)

    missing_props = []
    for prop in properties:
        if not (deploy_info.get(prop) or image_props.get(prop)):
            missing_props.append(prop)

    if missing_props:
        props = ', '.join(missing_props)
        raise exception.MissingParameterValue(_(
            "Image %(image)s is missing the following properties: "
            "%(properties)s") % {'image': image_href, 'properties': props})


def get_boot_option(node):
    """Gets the boot option.

    :param node: A single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
         dict or is malformed.
    :returns: A string representing the boot option type. Defaults to
        'netboot'.
    """
    capabilities = parse_instance_info_capabilities(node)
    return capabilities.get('boot_option', 'netboot').lower()


def prepare_cleaning_ports(task):
    """Prepare the Ironic ports of the node for cleaning.

    This method deletes the cleaning ports currently existing
    for all the ports of the node and then creates a new one
    for each one of them.  It also adds 'vif_port_id' to port.extra
    of each Ironic port, after creating the cleaning ports.

    :param task: a TaskManager object containing the node
    :raises NodeCleaningFailure: if the previous cleaning ports cannot
        be removed or if new cleaning ports cannot be created
    """
    provider = dhcp_factory.DHCPFactory()
    # If we have left over ports from a previous cleaning, remove them
    if getattr(provider.provider, 'delete_cleaning_ports', None):
        # Allow to raise if it fails, is caught and handled in conductor
        provider.provider.delete_cleaning_ports(task)

    # Create cleaning ports if necessary
    if getattr(provider.provider, 'create_cleaning_ports', None):
        # Allow to raise if it fails, is caught and handled in conductor
        ports = provider.provider.create_cleaning_ports(task)

        # Add vif_port_id for each of the ports because some boot
        # interfaces expects these to prepare for booting ramdisk.
        for port in task.ports:
            extra_dict = port.extra
            try:
                extra_dict['vif_port_id'] = ports[port.uuid]
            except KeyError:
                # This is an internal error in Ironic.  All DHCP providers
                # implementing create_cleaning_ports are supposed to
                # return a VIF port ID for all Ironic ports.  But
                # that doesn't seem to be true here.
                error = (_("When creating cleaning ports, DHCP provider "
                           "didn't return VIF port ID for %s") % port.uuid)
                raise exception.NodeCleaningFailure(
                    node=task.node.uuid, reason=error)
            else:
                port.extra = extra_dict
                port.save()


def tear_down_cleaning_ports(task):
    """Deletes the cleaning ports created for each of the Ironic ports.

    This method deletes the cleaning port created before cleaning
    was started.

    :param task: a TaskManager object containing the node
    :raises NodeCleaningFailure: if the cleaning ports cannot be
        removed.
    """
    # If we created cleaning ports, delete them
    provider = dhcp_factory.DHCPFactory()
    if getattr(provider.provider, 'delete_cleaning_ports', None):
        # Allow to raise if it fails, is caught and handled in conductor
        provider.provider.delete_cleaning_ports(task)

        for port in task.ports:
            if 'vif_port_id' in port.extra:
                extra_dict = port.extra
                extra_dict.pop('vif_port_id', None)
                port.extra = extra_dict
                port.save()


def build_agent_options(node):
    """Build the options to be passed to the agent ramdisk.

    :param node: an ironic node object
    :returns: a dictionary containing the parameters to be passed to
        agent ramdisk.
    """
    ironic_api = (CONF.conductor.api_url or
                  keystone.get_service_url()).rstrip('/')
    agent_config_opts = {
        'ipa-api-url': ironic_api,
        'ipa-driver-name': node.driver,
        # NOTE: The below entry is a temporary workaround for bug/1433812
        'coreos.configdrive': 0,
    }
    root_device = parse_root_device_hints(node)
    if root_device:
        agent_config_opts['root_device'] = root_device

    return agent_config_opts


def prepare_inband_cleaning(task, manage_boot=True):
    """Prepares the node to boot into agent for in-band cleaning.

    This method does the following:
    1. Prepares the cleaning ports for the bare metal
       node and updates the clean parameters in node's driver_internal_info.
    2. If 'manage_boot' parameter is set to true, it also calls the
       'prepare_ramdisk' method of boot interface to boot the agent ramdisk.
    3. Reboots the bare metal node.

    :param task: a TaskManager object containing the node
    :param manage_boot: If this is set to True, this method calls the
        'prepare_ramdisk' method of boot interface to boot the agent
        ramdisk. If False, it skips preparing the boot agent ramdisk using
        boot interface, and assumes that the environment is setup to
        automatically boot agent ramdisk every time bare metal node is
        rebooted.
    :returns: states.CLEANWAIT to signify an asynchronous prepare.
    :raises NodeCleaningFailure: if the previous cleaning ports cannot
        be removed or if new cleaning ports cannot be created
    """
    prepare_cleaning_ports(task)

    # Append required config parameters to node's driver_internal_info
    # to pass to IPA.
    agent_add_clean_params(task)

    if manage_boot:
        ramdisk_opts = build_agent_options(task.node)
        task.driver.boot.prepare_ramdisk(task, ramdisk_opts)
    manager_utils.node_power_action(task, states.REBOOT)

    # Tell the conductor we are waiting for the agent to boot.
    return states.CLEANWAIT


def tear_down_inband_cleaning(task, manage_boot=True):
    """Tears down the environment setup for in-band cleaning.

    This method does the following:
    1. Powers off the bare metal node.
    2. If 'manage_boot' parameter is set to true, it also
    calls the 'clean_up_ramdisk' method of boot interface to clean up
    the environment that was set for booting agent ramdisk.
    3. Deletes the cleaning ports which were setup as part
    of cleaning.

    :param task: a TaskManager object containing the node
    :param manage_boot: If this is set to True, this method calls the
        'clean_up_ramdisk' method of boot interface to boot the agent
        ramdisk. If False, it skips this step.
    :raises NodeCleaningFailure: if the cleaning ports cannot be
        removed.
    """
    manager_utils.node_power_action(task, states.POWER_OFF)
    if manage_boot:
        task.driver.boot.clean_up_ramdisk(task)

    tear_down_cleaning_ports(task)
