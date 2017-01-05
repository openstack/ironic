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


import contextlib
import os
import re
import socket
import time

from ironic_lib import disk_utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import strutils
import six
from six.moves.urllib import parse

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LW
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils
from ironic import objects


deploy_opts = [
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
    cfg.BoolOpt('power_off_after_deploy_failure',
                default=True,
                help=_('Whether to power off a node after deploy failure. '
                       'Defaults to True.')),
]
CONF = cfg.CONF
CONF.register_opts(deploy_opts, group='deploy')

# TODO(Faizan): Move this logic to common/utils.py and deprecate
# rootwrap_config.
# This is required to set the default value of ironic_lib option
# only if rootwrap_config does not contain the default value.
if CONF.rootwrap_config != '/etc/ironic/rootwrap.conf':
    root_helper = 'sudo ironic-rootwrap %s' % CONF.rootwrap_config
    CONF.set_default('root_helper', root_helper, 'ironic_lib')

LOG = logging.getLogger(__name__)

VALID_ROOT_DEVICE_HINTS = set(('size', 'model', 'wwn', 'serial', 'vendor',
                               'wwn_with_extension', 'wwn_vendor_extension',
                               'name'))

SUPPORTED_CAPABILITIES = {
    'boot_option': ('local', 'netboot'),
    'boot_mode': ('bios', 'uefi'),
    'secure_boot': ('true', 'false'),
    'trusted_boot': ('true', 'false'),
    'disk_label': ('msdos', 'gpt'),
}

DISK_LAYOUT_PARAMS = ('root_gb', 'swap_mb', 'ephemeral_gb')

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
    total_checks = CONF.disk_utils.iscsi_verify_attempts
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

    for attempt in range(CONF.disk_utils.iscsi_verify_attempts):
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
                   "total": CONF.disk_utils.iscsi_verify_attempts})
    else:
        msg = _("iSCSI connection did not become active after attempting to "
                "verify %d times.") % CONF.disk_utils.iscsi_verify_attempts
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

    if boot_mode == 'uefi' and not CONF.pxe.ipxe_enabled:
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


def deploy_partition_image(
        address, port, iqn, lun, image_path,
        root_mb, swap_mb, ephemeral_mb, ephemeral_format, node_uuid,
        preserve_ephemeral=False, configdrive=None,
        boot_option="netboot", boot_mode="bios", disk_label=None):
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
    :param disk_label: The disk label to be used when creating the
        partition table. Valid values are: "msdos", "gpt" or None; If None
        Ironic will figure it out according to the boot_mode parameter.
    :raises: InstanceDeployFailure if image virtual size is bigger than root
        partition size.
    :returns: a dictionary containing the following keys:
        'root uuid': UUID of root partition
        'efi system partition uuid': UUID of the uefi system partition
                                     (if boot mode is uefi).
        NOTE: If key exists but value is None, it means partition doesn't
              exist.
    """
    image_mb = disk_utils.get_image_mb(image_path)
    if image_mb > root_mb:
        msg = (_('Root partition is too small for requested image. Image '
                 'virtual size: %(image_mb)d MB, Root size: %(root_mb)d MB')
               % {'image_mb': image_mb, 'root_mb': root_mb})
        raise exception.InstanceDeployFailure(msg)

    with _iscsi_setup_and_handle_errors(address, port, iqn, lun) as dev:
        uuid_dict_returned = disk_utils.work_on_disk(
            dev, root_mb, swap_mb, ephemeral_mb, ephemeral_format, image_path,
            node_uuid, preserve_ephemeral=preserve_ephemeral,
            configdrive=configdrive, boot_option=boot_option,
            boot_mode=boot_mode, disk_label=disk_label)

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
        disk_utils.populate_image(image_path, dev)
        disk_identifier = disk_utils.get_disk_identifier(dev)

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
    if not disk_utils.is_block_device(dev):
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

    if CONF.deploy.power_off_after_deploy_failure:
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
    """Get the list of cached clean steps from the agent.

    #TODO(JoshNang) move to BootInterface

    The clean steps cache is updated at the beginning of cleaning.

    :param task: a TaskManager object containing the node
    :param interface: The interface for which clean steps
        are to be returned. If this is not provided, it returns the
        clean steps for all interfaces.
    :param override_priorities: a dictionary with keys being step names and
        values being new priorities for them. If a step isn't in this
        dictionary, the step's original priority is used.
    :raises NodeCleaningFailure: if the clean steps are not yet cached,
        for example, when a node has just been enrolled and has not been
        cleaned yet.
    :returns: A list of clean step dictionaries
    """
    node = task.node
    try:
        all_steps = node.driver_internal_info['agent_cached_clean_steps']
    except KeyError:
        raise exception.NodeCleaningFailure(_('Cleaning steps are not yet '
                                              'available for node %(node)s')
                                            % {'node': node.uuid})

    if interface:
        steps = [step.copy() for step in all_steps.get(interface, [])]
    else:
        steps = [step.copy() for step_list in all_steps.values()
                 for step in step_list]

    if not steps or not override_priorities:
        return steps

    for step in steps:
        new_priority = override_priorities.get(step.get('step'))
        if new_priority is not None:
            step['priority'] = new_priority

    return steps


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
    for key, value in sorted(root_device.items()):
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


def get_disk_label(node):
    """Return the disk label requested for deploy, if any.

    :param node: a single Node.
    :raises: InvalidParameterValue if the capabilities string is not a
             dictionary or is malformed.
    :returns: the disk label or None if no disk label was specified.
    """
    capabilities = parse_instance_info_capabilities(node)
    return capabilities.get('disk_label')


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

        # TODO(rameshg87): Below code is to make sure that bash ramdisk
        # invokes pass_deploy_info vendor passthru when it is booted
        # for cleaning. Remove the below code once we stop supporting
        # bash ramdisk in Ironic. Do a late import to avoid circular
        # import.
        from ironic.drivers.modules import iscsi_deploy
        ramdisk_opts.update(
            iscsi_deploy.build_deploy_ramdisk_options(task.node))
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


def get_image_instance_info(node):
    """Gets the image information from the node.

    Get image information for the given node instance from its
    'instance_info' property.

    :param node: a single Node.
    :returns: A dict with required image properties retrieved from
        node's 'instance_info'.
    :raises: MissingParameterValue, if image_source is missing in node's
        instance_info. Also raises same exception if kernel/ramdisk is
        missing in instance_info for non-glance images.
    """
    info = {}
    info['image_source'] = node.instance_info.get('image_source')

    is_whole_disk_image = node.driver_internal_info.get('is_whole_disk_image')
    if not is_whole_disk_image:
        if not service_utils.is_glance_image(info['image_source']):
            info['kernel'] = node.instance_info.get('kernel')
            info['ramdisk'] = node.instance_info.get('ramdisk')

    error_msg = (_("Cannot validate image information for node %s because one "
                   "or more parameters are missing from its instance_info.")
                 % node.uuid)
    check_for_missing_params(info, error_msg)

    return info


def parse_instance_info(node):
    """Gets the instance specific Node deployment info.

    This method validates whether the 'instance_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the instance_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """

    info = node.instance_info
    i_info = {}
    i_info['image_source'] = info.get('image_source')
    iwdi = node.driver_internal_info.get('is_whole_disk_image')
    if not iwdi:
        if (i_info['image_source'] and
                not service_utils.is_glance_image(
                    i_info['image_source'])):
            i_info['kernel'] = info.get('kernel')
            i_info['ramdisk'] = info.get('ramdisk')
    i_info['root_gb'] = info.get('root_gb')

    error_msg = _("Cannot validate driver deploy. Some parameters were missing"
                  " in node's instance_info")
    check_for_missing_params(i_info, error_msg)

    # Internal use only
    i_info['deploy_key'] = info.get('deploy_key')
    i_info['swap_mb'] = int(info.get('swap_mb', 0))
    i_info['ephemeral_gb'] = info.get('ephemeral_gb', 0)
    err_msg_invalid = _("Cannot validate parameter for driver deploy. "
                        "Invalid parameter %(param)s. Reason: %(reason)s")
    for param in DISK_LAYOUT_PARAMS:
        try:
            int(i_info[param])
        except ValueError:
            reason = _("%s is not an integer value.") % i_info[param]
            raise exception.InvalidParameterValue(err_msg_invalid %
                                                  {'param': param,
                                                   'reason': reason})

    i_info['root_mb'] = 1024 * int(info.get('root_gb'))

    if iwdi:
        if int(i_info['swap_mb']) > 0 or int(i_info['ephemeral_gb']) > 0:
            err_msg_invalid = _("Cannot deploy whole disk image with "
                                "swap or ephemeral size set")
            raise exception.InvalidParameterValue(err_msg_invalid)
    i_info['ephemeral_format'] = info.get('ephemeral_format')
    i_info['configdrive'] = info.get('configdrive')

    if i_info['ephemeral_gb'] and not i_info['ephemeral_format']:
        i_info['ephemeral_format'] = CONF.pxe.default_ephemeral_format

    preserve_ephemeral = info.get('preserve_ephemeral', False)
    try:
        i_info['preserve_ephemeral'] = (
            strutils.bool_from_string(preserve_ephemeral, strict=True))
    except ValueError as e:
        raise exception.InvalidParameterValue(
            err_msg_invalid % {'param': 'preserve_ephemeral', 'reason': e})

    # NOTE(Zhenguo): If rebuilding with preserve_ephemeral option, check
    # that the disk layout is unchanged.
    if i_info['preserve_ephemeral']:
        _check_disk_layout_unchanged(node, i_info)

    return i_info


def _check_disk_layout_unchanged(node, i_info):
    """Check whether disk layout is unchanged.

    If the node has already been deployed to, this checks whether the disk
    layout for the node is the same as when it had been deployed to.

    :param node: the node of interest
    :param i_info: instance information (a dictionary) for the node, containing
                   disk layout information
    :raises: InvalidParameterValue if the disk layout changed
    """
    # If a node has been deployed to, this is the instance information
    # used for that deployment.
    driver_internal_info = node.driver_internal_info
    if 'instance' not in driver_internal_info:
        return

    error_msg = ''
    for param in DISK_LAYOUT_PARAMS:
        param_value = int(driver_internal_info['instance'][param])
        if param_value != int(i_info[param]):
            error_msg += (_(' Deployed value of %(param)s was %(param_value)s '
                            'but requested value is %(request_value)s.') %
                          {'param': param, 'param_value': param_value,
                           'request_value': i_info[param]})

    if error_msg:
        err_msg_invalid = _("The following parameters have different values "
                            "from previous deployment:%(error_msg)s")
        raise exception.InvalidParameterValue(err_msg_invalid %
                                              {'error_msg': error_msg})
