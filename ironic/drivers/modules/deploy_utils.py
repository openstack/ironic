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
import gzip
import math
import os
import re
import shutil
import socket
import stat
import tempfile
import time

from oslo.utils import excutils
from oslo.utils import units
from oslo_concurrency import processutils
from oslo_config import cfg
import requests
import six

from ironic.common import disk_partitioner
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common import images
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import image_cache
from ironic.openstack.common import log as logging


deploy_opts = [
    cfg.StrOpt('dd_block_size',
               default='1M',
               help='Block size to use when writing to the nodes disk.'),
    cfg.IntOpt('iscsi_verify_attempts',
               default=3,
               help='Maximum attempts to verify an iSCSI connection is '
                    'active, sleeping 1 second between attempts.'),
    ]

CONF = cfg.CONF
CONF.register_opts(deploy_opts, group='deploy')

LOG = logging.getLogger(__name__)


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
    # NOTE(dprince): partial revert of 4606716 until we debug further
    time.sleep(3)
    # Ensure the login complete
    verify_iscsi_connection(target_iqn)
    # force iSCSI initiator to re-read luns
    force_iscsi_lun_update(target_iqn)


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
                  "%(attempt)d out of %(total)d", {"attempt": attempt + 1,
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


def make_partitions(dev, root_mb, swap_mb, ephemeral_mb,
                    configdrive_mb, commit=True):
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
    :returns: A dictionary containing the partition type as Key and partition
        path as Value for the partitions created by this method.

    """
    LOG.debug("Starting to partition the disk device: %(dev)s",
              {'dev': dev})
    part_template = dev + '-part%d'
    part_dict = {}
    dp = disk_partitioner.DiskPartitioner(dev)
    if ephemeral_mb:
        LOG.debug("Add ephemeral partition (%(size)d MB) to device: %(dev)s",
                 {'dev': dev, 'size': ephemeral_mb})
        part_num = dp.add_partition(ephemeral_mb)
        part_dict['ephemeral'] = part_template % part_num
    if swap_mb:
        LOG.debug("Add Swap partition (%(size)d MB) to device: %(dev)s",
                 {'dev': dev, 'size': swap_mb})
        part_num = dp.add_partition(swap_mb, fs_type='linux-swap')
        part_dict['swap'] = part_template % part_num
    if configdrive_mb:
        LOG.debug("Add config drive partition (%(size)d MB) to device: "
                  "%(dev)s", {'dev': dev, 'size': configdrive_mb})
        part_num = dp.add_partition(configdrive_mb)
        part_dict['configdrive'] = part_template % part_num

    # NOTE(lucasagomes): Make the root partition the last partition. This
    # enables tools like cloud-init's growroot utility to expand the root
    # partition until the end of the disk.
    LOG.debug("Add root partition (%(size)d MB) to device: %(dev)s",
             {'dev': dev, 'size': root_mb})
    part_num = dp.add_partition(root_mb)
    part_dict['root'] = part_template % part_num

    if commit:
        # write to the disk
        dp.commit()
    return part_dict


def is_block_device(dev):
    """Check whether a device is block or not."""
    s = os.stat(dev)
    return stat.S_ISBLK(s.st_mode)


def dd(src, dst):
    """Execute dd from src to dst."""
    utils.dd(src, dst, 'bs=%s' % CONF.deploy.dd_block_size, 'oflag=direct')


def populate_image(src, dst):
    data = images.qemu_img_info(src)
    if data.file_format == 'raw':
        dd(src, dst)
    else:
        images.convert_image(src, dst, 'raw', True)


def mkswap(dev, label='swap1'):
    """Execute mkswap on a device."""
    utils.mkfs('swap', dev, label)


def mkfs_ephemeral(dev, ephemeral_format, label="ephemeral0"):
    utils.mkfs(ephemeral_format, dev, label)


def block_uuid(dev):
    """Get UUID of a block device."""
    out, _err = utils.execute('blkid', '-s', 'UUID', '-o', 'value', dev,
                              run_as_root=True,
                              check_exit_code=[0])
    return out.strip()


def switch_pxe_config(path, root_uuid, boot_mode):
    """Switch a pxe config from deployment mode to service mode."""
    with open(path) as f:
        lines = f.readlines()
    root = 'UUID=%s' % root_uuid
    rre = re.compile(r'\{\{ ROOT \}\}')

    if boot_mode == 'uefi':
        dre = re.compile('^default=.*$')
        boot_line = 'default=boot'
    else:
        pxe_cmd = 'goto' if CONF.pxe.ipxe_enabled else 'default'
        dre = re.compile('^%s .*$' % pxe_cmd)
        boot_line = '%s boot' % pxe_cmd

    with open(path, 'w') as f:
        for line in lines:
            line = rre.sub(root, line)
            line = dre.sub(boot_line, line)
            f.write(line)


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
    # NOTE(NobodyCam): This is needed to work around bug:
    # https://bugs.launchpad.net/ironic/+bug/1317647
    LOG.debug("Start destroy disk metadata for node %(node)s.",
              {'node': node_uuid})
    try:
        utils.execute('dd', 'if=/dev/zero', 'of=%s' % dev,
                      'bs=512', 'count=36', run_as_root=True,
                      check_exit_code=[0])
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
            utils.execute('dd', 'if=/dev/zero', 'of=%s' % dev,
                          'bs=512', 'count=36', 'seek=%d' % seek_value,
                          run_as_root=True, check_exit_code=[0])
        except processutils.ProcessExecutionError as err:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to erase the end of the disk on node "
                              "%(node)s. Command: %(command)s. "
                              "Error: %(error)s."),
                          {'node': node_uuid,
                           'command': err.cmd,
                           'error': err.stderr})


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
        data = six.StringIO(base64.b64decode(data))
    except TypeError:
        error_msg = (_('Config drive for node %s is not base64 encoded '
                       'or the content is malformed.') % node_uuid)
        if is_url:
            error_msg += _(' Downloaded from "%s".') % configdrive
        raise exception.InstanceDeployFailure(error_msg)

    configdrive_file = tempfile.NamedTemporaryFile(delete=False,
                                                   prefix='configdrive')
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
                 configdrive=None):
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
    :returns: the UUID of the root partition.
    """
    if not is_block_device(dev):
        raise exception.InstanceDeployFailure(
            _("Parent device '%s' not found") % dev)

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
                                    configdrive_mb, commit=commit)

        ephemeral_part = part_dict.get('ephemeral')
        swap_part = part_dict.get('swap')
        configdrive_part = part_dict.get('configdrive')
        root_part = part_dict.get('root')

        if not is_block_device(root_part):
            raise exception.InstanceDeployFailure(
                _("Root device '%s' not found") % root_part)

        for part in ('swap', 'ephemeral', 'configdrive'):
            part_device = part_dict.get(part)
            LOG.debug("Checking for %(part)s device (%(dev)s) on node "
                      "%(node)s.", {'part': part, 'dev': part_device,
                      'node': node_uuid})
            if part_device and not is_block_device(part_device):
                raise exception.InstanceDeployFailure(
                    _("'%(partition)s' device '%(part_device)s' not found") %
                    {'partition': part, 'part_device': part_device})

        if configdrive_part:
            # Copy the configdrive content to the configdrive partition
            dd(configdrive_file, configdrive_part)

    finally:
        # If the configdrive was requested make sure we delete the file
        # after copying the content to the partition
        if configdrive_file:
            utils.unlink_without_raise(configdrive_file)

    populate_image(image_path, root_part)

    if swap_part:
        mkswap(swap_part)

    if ephemeral_part and not preserve_ephemeral:
        mkfs_ephemeral(ephemeral_part, ephemeral_format)

    try:
        root_uuid = block_uuid(root_part)
    except processutils.ProcessExecutionError:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE("Failed to detect root device UUID."))

    return root_uuid


def deploy(address, port, iqn, lun, image_path,
           root_mb, swap_mb, ephemeral_mb, ephemeral_format, node_uuid,
           preserve_ephemeral=False, configdrive=None):
    """All-in-one function to deploy a node.

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
    :returns: the UUID of the root partition.
    """
    dev = get_dev(address, port, iqn, lun)
    image_mb = get_image_mb(image_path)
    if image_mb > root_mb:
        root_mb = image_mb
    discovery(address, port)
    login_iscsi(address, port, iqn)
    try:
        root_uuid = work_on_disk(dev, root_mb, swap_mb, ephemeral_mb,
                                 ephemeral_format, image_path, node_uuid,
                                 preserve_ephemeral=preserve_ephemeral,
                                 configdrive=configdrive)
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

    return root_uuid


def notify_deploy_complete(address):
    """Notifies the completion of deployment to the baremetal node.

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
        raise exception.MissingParameterValue(exc_msg %
                    {'error_msg': error_msg, 'missing_info': missing_info})


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
    :raises: InvalidState if the event is not allowed by the associated
             state machine.
    """
    task.process_event('fail')
    node = task.node
    try:
        manager_utils.node_power_action(task, states.POWER_OFF)
    except Exception:
        msg2 = (_LE('Node %s failed to power off while handling deploy '
                    'failure. This may be a serious condition. Node '
                    'should be removed from Ironic or put in maintenance '
                    'mode until the problem is resolved.') % node.uuid)
        LOG.exception(msg2)
    finally:
        # NOTE(deva): node_power_action() erases node.last_error
        #             so we need to set it again here.
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
