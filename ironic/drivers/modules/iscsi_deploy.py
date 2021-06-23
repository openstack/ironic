# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
import glob
import os
import time
from urllib import parse as urlparse

from ironic_lib import disk_utils
from ironic_lib import metrics_utils
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

DISK_LAYOUT_PARAMS = ('root_gb', 'swap_mb', 'ephemeral_gb')


def _save_disk_layout(node, i_info):
    """Saves the disk layout.

    The disk layout used for deployment of the node, is saved.

    :param node: the node of interest
    :param i_info: instance information (a dictionary) for the node, containing
                   disk layout information
    """
    driver_internal_info = node.driver_internal_info
    driver_internal_info['instance'] = {}

    for param in DISK_LAYOUT_PARAMS:
        driver_internal_info['instance'][param] = i_info[param]

    node.driver_internal_info = driver_internal_info
    node.save()


def discovery(portal_address, portal_port):
    """Do iSCSI discovery on portal."""
    utils.execute('iscsiadm',
                  '-m', 'discovery',
                  '-t', 'st',
                  '-p', '%s:%s' % (utils.wrap_ipv6(portal_address),
                                   portal_port),
                  run_as_root=True,
                  check_exit_code=[0],
                  attempts=5,
                  delay_on_retry=True)


def login_iscsi(portal_address, portal_port, target_iqn):
    """Login to an iSCSI target."""
    utils.execute('iscsiadm',
                  '-m', 'node',
                  '-p', '%s:%s' % (utils.wrap_ipv6(portal_address),
                                   portal_port),
                  '-T', target_iqn,
                  '--login',
                  run_as_root=True,
                  check_exit_code=[0],
                  attempts=5,
                  delay_on_retry=True)

    error_occurred = False
    try:
        # Ensure the login complete
        verify_iscsi_connection(target_iqn)
        # force iSCSI initiator to re-read luns
        force_iscsi_lun_update(target_iqn)
        # ensure file system sees the block device
        check_file_system_for_iscsi_device(portal_address,
                                           portal_port,
                                           target_iqn)
    except (exception.InstanceDeployFailure,
            processutils.ProcessExecutionError) as e:
        with excutils.save_and_reraise_exception():
            error_occurred = True
            LOG.error("Failed to login to an iSCSI target due to %s", e)
    finally:
        if error_occurred:
            try:
                logout_iscsi(portal_address, portal_port, target_iqn)
                delete_iscsi(portal_address, portal_port, target_iqn)
            except processutils.ProcessExecutionError as e:
                LOG.warning("An error occurred when trying to cleanup "
                            "failed ISCSI session error %s", e)


def check_file_system_for_iscsi_device(portal_address,
                                       portal_port,
                                       target_iqn):
    """Ensure the file system sees the iSCSI block device."""
    check_dir = "/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-1" % (portal_address,
                                                               portal_port,
                                                               target_iqn)
    total_checks = CONF.iscsi.verify_attempts
    for attempt in range(total_checks):
        if os.path.exists(check_dir):
            break
        time.sleep(1)
        if LOG.isEnabledFor(logging.DEBUG):
            existing_devs = ', '.join(glob.iglob('/dev/disk/by-path/*iscsi*'))
            LOG.debug("iSCSI connection not seen by file system. Rechecking. "
                      "Attempt %(attempt)d out of %(total)d. Available iSCSI "
                      "devices: %(devs)s.",
                      {"attempt": attempt + 1,
                       "total": total_checks,
                       "devs": existing_devs})
    else:
        msg = _("iSCSI connection was not seen by the file system after "
                "attempting to verify %d times.") % total_checks
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)


def verify_iscsi_connection(target_iqn):
    """Verify iscsi connection."""
    LOG.debug("Checking for iSCSI target to become active.")

    total_checks = CONF.iscsi.verify_attempts
    for attempt in range(total_checks):
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
                  {"attempt": attempt + 1, "total": total_checks})
    else:
        msg = _("iSCSI connection did not become active after attempting to "
                "verify %d times.") % total_checks
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
                  '-p', '%s:%s' % (utils.wrap_ipv6(portal_address),
                                   portal_port),
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
                  '-p', '%s:%s' % (utils.wrap_ipv6(portal_address),
                                   portal_port),
                  '-T', target_iqn,
                  '-o', 'delete',
                  run_as_root=True,
                  check_exit_code=[0, 21],
                  attempts=5,
                  delay_on_retry=True)


@contextlib.contextmanager
def _iscsi_setup_and_handle_errors(address, port, iqn, lun):
    """Function that yields an iSCSI target device to work on.

    :param address: The iSCSI IP address.
    :param port: The iSCSI port number.
    :param iqn: The iSCSI qualified name.
    :param lun: The iSCSI logical unit number.
    """
    dev = ("/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-%s"
           % (address, port, iqn, lun))
    discovery(address, port)
    login_iscsi(address, port, iqn)
    if not disk_utils.is_block_device(dev):
        raise exception.InstanceDeployFailure(_("Parent device '%s' not found")
                                              % dev)
    try:
        yield dev
    except processutils.ProcessExecutionError as err:
        with excutils.save_and_reraise_exception():
            LOG.error("Deploy to address %s failed.", address)
            LOG.error("Command: %s", err.cmd)
            LOG.error("StdOut: %r", err.stdout)
            LOG.error("StdErr: %r", err.stderr)
    except exception.InstanceDeployFailure as e:
        with excutils.save_and_reraise_exception():
            LOG.error("Deploy to address %s failed.", address)
            LOG.error(e)
    finally:
        logout_iscsi(address, port, iqn)
        delete_iscsi(address, port, iqn)


def deploy_partition_image(
        address, port, iqn, lun, image_path,
        root_mb, swap_mb, ephemeral_mb, ephemeral_format, node_uuid,
        preserve_ephemeral=False, configdrive=None,
        boot_option=None, boot_mode="bios", disk_label=None,
        cpu_arch=""):
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
                               ephemeral block device, preserving whatever
                               content it had (if the partition table has
                               not changed).
    :param configdrive: Optional. Base64 encoded Gzipped configdrive content
                        or configdrive HTTP URL.
    :param boot_option: Can be "local" or "netboot".
                        "netboot" by default.
    :param boot_mode: Can be "bios" or "uefi". "bios" by default.
    :param disk_label: The disk label to be used when creating the
                       partition table. Valid values are: "msdos",
                       "gpt" or None; If None ironic will figure it
                       out according to the boot_mode parameter.
    :param cpu_arch: Architecture of the node being deployed to.
    :raises: InstanceDeployFailure if image virtual size is bigger than root
             partition size.
    :returns: a dictionary containing the following keys:
              'root uuid': UUID of root partition
              'efi system partition uuid': UUID of the uefi system partition
              (if boot mode is uefi).
              NOTE: If key exists but value is None, it means partition doesn't
              exist.
    """
    # NOTE(dtantsur): CONF.default_boot_option is mutable, don't use it in
    # the function signature!
    boot_option = boot_option or deploy_utils.get_default_boot_option()
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
            boot_mode=boot_mode, disk_label=disk_label, cpu_arch=cpu_arch)

    return uuid_dict_returned


def deploy_disk_image(address, port, iqn, lun,
                      image_path, node_uuid, configdrive=None,
                      conv_flags=None):
    """All-in-one function to deploy a whole disk image to a node.

    :param address: The iSCSI IP address.
    :param port: The iSCSI port number.
    :param iqn: The iSCSI qualified name.
    :param lun: The iSCSI logical unit number.
    :param image_path: Path for the instance's disk image.
    :param node_uuid: node's uuid.
    :param configdrive: Optional. Base64 encoded Gzipped configdrive content
                        or configdrive HTTP URL.
    :param conv_flags: Optional. Add a flag that will modify the behaviour of
                       the image copy to disk.
    :returns: a dictionary containing the key 'disk identifier' to identify
        the disk which was used for deployment.
    """
    with _iscsi_setup_and_handle_errors(address, port, iqn,
                                        lun) as dev:
        disk_utils.populate_image(image_path, dev, conv_flags=conv_flags)

        if configdrive:
            disk_utils.create_config_drive_partition(node_uuid, dev,
                                                     configdrive)

        disk_identifier = disk_utils.get_disk_identifier(dev)

    return {'disk identifier': disk_identifier}


@METRICS.timer('check_image_size')
def check_image_size(task):
    """Check if the requested image is larger than the root partition size.

    Does nothing for whole-disk images.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InstanceDeployFailure if size of the image is greater than root
        partition.
    """
    if task.node.driver_internal_info['is_whole_disk_image']:
        # The root partition is already created and populated, no use
        # validating its size
        return

    i_info = deploy_utils.parse_instance_info(task.node)
    image_path = deploy_utils._get_image_file_path(task.node.uuid)
    image_mb = disk_utils.get_image_mb(image_path)
    root_mb = 1024 * int(i_info['root_gb'])
    if image_mb > root_mb:
        msg = (_('Root partition is too small for requested image. Image '
                 'virtual size: %(image_mb)d MB, Root size: %(root_mb)d MB')
               % {'image_mb': image_mb, 'root_mb': root_mb})
        raise exception.InstanceDeployFailure(msg)


@METRICS.timer('get_deploy_info')
def get_deploy_info(node, address, iqn, port=None, lun='1', conv_flags=None):
    """Returns the information required for doing iSCSI deploy in a dictionary.

    :param node: ironic node object
    :param address: iSCSI address
    :param iqn: iSCSI iqn for the target disk
    :param port: iSCSI port, defaults to one specified in the configuration
    :param lun: iSCSI lun, defaults to '1'
    :param conv_flags: flag that will modify the behaviour of the image copy
        to disk.
    :raises: MissingParameterValue, if some required parameters were not
        passed.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    i_info = deploy_utils.parse_instance_info(node)

    params = {
        'address': address,
        'port': port or CONF.iscsi.portal_port,
        'iqn': iqn,
        'lun': lun,
        'image_path': deploy_utils._get_image_file_path(node.uuid),
        'node_uuid': node.uuid}

    is_whole_disk_image = node.driver_internal_info['is_whole_disk_image']
    if not is_whole_disk_image:
        params.update({'root_mb': i_info['root_mb'],
                       'swap_mb': i_info['swap_mb'],
                       'ephemeral_mb': i_info['ephemeral_mb'],
                       'preserve_ephemeral': i_info['preserve_ephemeral'],
                       'boot_option': deploy_utils.get_boot_option(node),
                       'boot_mode': boot_mode_utils.get_boot_mode(node)})

        cpu_arch = node.properties.get('cpu_arch')
        if cpu_arch is not None:
            params['cpu_arch'] = cpu_arch

        # Append disk label if specified
        disk_label = deploy_utils.get_disk_label(node)
        if disk_label is not None:
            params['disk_label'] = disk_label

    missing = [key for key in params if params[key] is None]
    if missing:
        raise exception.MissingParameterValue(
            _("Parameters %s were not passed to ironic"
              " for deploy.") % missing)

    # configdrive is nullable
    params['configdrive'] = i_info.get('configdrive')
    if is_whole_disk_image:
        return params

    if conv_flags:
        params['conv_flags'] = conv_flags

    # ephemeral_format is nullable
    params['ephemeral_format'] = i_info.get('ephemeral_format')

    return params


@METRICS.timer('continue_deploy')
def continue_deploy(task, **kwargs):
    """Resume a deployment upon getting POST data from deploy ramdisk.

    This method raises no exceptions because it is intended to be
    invoked asynchronously as a callback from the deploy ramdisk.

    :param task: a TaskManager instance containing the node to act on.
    :param kwargs: the kwargs to be passed to deploy.
    :raises: InvalidState if the event is not allowed by the associated
             state machine.
    :returns: a dictionary containing the following keys:

              For partition image:

              * 'root uuid': UUID of root partition
              * 'efi system partition uuid': UUID of the uefi system partition
                (if boot mode is uefi).

                .. note:: If key exists but value is None, it means partition
                          doesn't exist.

              For whole disk image:

              * 'disk identifier': ID of the disk to which image was deployed.
    """
    node = task.node

    params = get_deploy_info(node, **kwargs)

    def _fail_deploy(task, msg, raise_exception=True):
        """Fail the deploy after logging and setting error states."""
        if isinstance(msg, Exception):
            msg = (_('Deploy failed for instance %(instance)s. '
                     'Error: %(error)s') %
                   {'instance': node.instance_uuid, 'error': msg})
        deploy_utils.set_failed_state(task, msg)
        deploy_utils.destroy_images(task.node.uuid)
        if raise_exception:
            raise exception.InstanceDeployFailure(msg)

    # NOTE(lucasagomes): Let's make sure we don't log the full content
    # of the config drive here because it can be up to 64MB in size,
    # so instead let's log "***" in case config drive is enabled.
    if LOG.isEnabledFor(logging.logging.DEBUG):
        log_params = {
            k: params[k] if k != 'configdrive' else '***'
            for k in params
        }
        LOG.debug('Continuing deployment for node %(node)s, params %(params)s',
                  {'node': node.uuid, 'params': log_params})

    uuid_dict_returned = {}
    try:
        if node.driver_internal_info['is_whole_disk_image']:
            uuid_dict_returned = deploy_disk_image(**params)
        else:
            uuid_dict_returned = deploy_partition_image(**params)
    except exception.IronicException as e:
        with excutils.save_and_reraise_exception():
            LOG.error('Deploy of instance %(instance)s on node %(node)s '
                      'failed: %(error)s', {'instance': node.instance_uuid,
                                            'node': node.uuid, 'error': e})
            _fail_deploy(task, e, raise_exception=False)
    except Exception as e:
        LOG.exception('Deploy of instance %(instance)s on node %(node)s '
                      'failed with exception',
                      {'instance': node.instance_uuid, 'node': node.uuid})
        _fail_deploy(task, e)

    root_uuid_or_disk_id = uuid_dict_returned.get(
        'root uuid', uuid_dict_returned.get('disk identifier'))
    if not root_uuid_or_disk_id:
        msg = (_("Couldn't determine the UUID of the root "
                 "partition or the disk identifier after deploying "
                 "node %s") % node.uuid)
        LOG.error(msg)
        _fail_deploy(task, msg)

    if params.get('preserve_ephemeral', False):
        # Save disk layout information, to check that they are unchanged
        # for any future rebuilds
        _save_disk_layout(node, deploy_utils.parse_instance_info(node))

    deploy_utils.destroy_images(node.uuid)
    return uuid_dict_returned


@METRICS.timer('do_agent_iscsi_deploy')
def do_agent_iscsi_deploy(task, agent_client):
    """Method invoked when deployed with the agent ramdisk.

    This method is invoked by drivers for doing iSCSI deploy
    using agent ramdisk.  This method assumes that the agent
    is booted up on the node and is heartbeating.

    :param task: a TaskManager object containing the node.
    :param agent_client: an instance of agent_client.AgentClient
                         which will be used during iscsi deploy
                         (for exposing node's target disk via iSCSI,
                         for install boot loader, etc).
    :returns: a dictionary containing the following keys:

              For partition image:

              * 'root uuid': UUID of root partition
              * 'efi system partition uuid': UUID of the uefi system partition
                (if boot mode is uefi).

                .. note:: If key exists but value is None, it means partition
                          doesn't exist.

              For whole disk image:

              * 'disk identifier': ID of the disk to which image was deployed.
    :raises: InstanceDeployFailure if it encounters some error
             during the deploy.
    """
    node = task.node
    i_info = deploy_utils.parse_instance_info(node)
    wipe_disk_metadata = not i_info['preserve_ephemeral']

    iqn = 'iqn.2008-10.org.openstack:%s' % node.uuid
    portal_port = CONF.iscsi.portal_port
    conv_flags = CONF.iscsi.conv_flags
    result = agent_client.start_iscsi_target(
        node, iqn,
        portal_port,
        wipe_disk_metadata=wipe_disk_metadata)
    if result['command_status'] == 'FAILED':
        msg = (_("Failed to start the iSCSI target to deploy the "
                 "node %(node)s. Error: %(error)s") %
               {'node': node.uuid, 'error': result['command_error']})
        deploy_utils.set_failed_state(task, msg)
        raise exception.InstanceDeployFailure(reason=msg)

    address = urlparse.urlparse(node.driver_internal_info['agent_url'])
    address = address.hostname

    uuid_dict_returned = continue_deploy(task, iqn=iqn, address=address,
                                         conv_flags=conv_flags)
    root_uuid_or_disk_id = uuid_dict_returned.get(
        'root uuid', uuid_dict_returned.get('disk identifier'))

    # TODO(lucasagomes): Move this bit saving the root_uuid to
    # continue_deploy()
    driver_internal_info = node.driver_internal_info
    driver_internal_info['root_uuid_or_disk_id'] = root_uuid_or_disk_id
    node.driver_internal_info = driver_internal_info
    node.save()

    return uuid_dict_returned


@METRICS.timer('validate')
def validate(task):
    """Validates the pre-requisites for iSCSI deploy.

    Validates whether node in the task provided has some ports enrolled.
    This method validates whether conductor url is available either from CONF
    file or from keystone.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InvalidParameterValue if the URL of the Ironic API service is not
             configured in config file and is not accessible via Keystone
             catalog.
    :raises: MissingParameterValue if no ports are enrolled for the given node.
    """
    # TODO(lucasagomes): Validate the format of the URL
    deploy_utils.get_ironic_api_url()
    # Validate the root device hints
    deploy_utils.get_root_device_for_deploy(task.node)
    deploy_utils.parse_instance_info(task.node)


class ISCSIDeploy(agent_base.AgentDeployMixin, agent_base.AgentBaseMixin,
                  base.DeployInterface):
    """iSCSI Deploy Interface for deploy-related actions."""

    has_decomposed_deploy_steps = True

    supported = False

    def get_properties(self):
        return agent_base.VENDOR_PROPERTIES

    @METRICS.timer('ISCSIDeploy.validate')
    def validate(self, task):
        """Validate the deployment information for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue.
        :raises: MissingParameterValue
        """
        task.driver.boot.validate(task)
        node = task.node

        # Check the boot_mode, boot_option and disk_label capabilities values.
        deploy_utils.validate_capabilities(node)

        # Edit early if we are not writing a volume as the validate
        # tasks evaluate root device hints.
        if not task.driver.storage.should_write_image(task):
            LOG.debug('Skipping complete deployment interface validation '
                      'for node %s as it is set to boot from a remote '
                      'volume.', node.uuid)
            return

        # TODO(rameshg87): iscsi_ilo driver used to call this function. Remove
        # and copy-paste it's contents here.
        validate(task)

    @METRICS.timer('ISCSIDeploy.deploy')
    @base.deploy_step(priority=100)
    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Start deployment of the task's node.

        Fetches instance image, updates the DHCP port options for next boot,
        and issues a reboot request to the power driver.
        This causes the node to boot into the deployment ramdisk and triggers
        the next phase of PXE-based deployment via agent heartbeats.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        """
        node = task.node
        if manager_utils.is_fast_track(task):
            # NOTE(mgoddard): For fast track we can mostly skip this step and
            # proceed to the next step (i.e. write_image).
            LOG.debug('Performing a fast track deployment for %(node)s.',
                      {'node': task.node.uuid})
            deploy_utils.cache_instance_image(task.context, node)
            check_image_size(task)
            # NOTE(dtantsur): while the node is up and heartbeating, we don't
            # necessary have the deploy steps cached. Force a refresh here.
            self.refresh_steps(task, 'deploy')
        elif task.driver.storage.should_write_image(task):
            # Standard deploy process
            deploy_utils.cache_instance_image(task.context, node)
            check_image_size(task)
            # Check if the driver has already performed a reboot in a previous
            # deploy step.
            if not task.node.driver_internal_info.get('deployment_reboot',
                                                      False):
                manager_utils.node_power_action(task, states.REBOOT)
            info = task.node.driver_internal_info
            info.pop('deployment_reboot', None)
            info.pop('deployment_uuids', None)
            task.node.driver_internal_info = info
            task.node.save()

            return states.DEPLOYWAIT

    @METRICS.timer('ISCSIDeploy.write_image')
    @base.deploy_step(priority=80)
    @task_manager.require_exclusive_lock
    def write_image(self, task):
        """Method invoked when deployed using iSCSI.

        This method is invoked during a heartbeat from an agent when
        the node is in wait-call-back state. This deploys the image on
        the node and then configures the node to boot according to the
        desired boot option (netboot or localboot).

        :param task: a TaskManager object containing the node.
        :param kwargs: the kwargs passed from the heartbeat method.
        :raises: InstanceDeployFailure, if it encounters some error during
            the deploy.
        """
        if not task.driver.storage.should_write_image(task):
            LOG.debug('Skipping write_image for node %s', task.node.uuid)
            return

        node = task.node
        LOG.debug('Continuing the deployment on node %s', node.uuid)

        client = agent_client.get_client(task)
        uuid_dict_returned = do_agent_iscsi_deploy(task, client)
        utils.set_node_nested_field(node, 'driver_internal_info',
                                    'deployment_uuids', uuid_dict_returned)
        node.save()

    @METRICS.timer('ISCSIDeploy.prepare_instance_boot')
    @base.deploy_step(priority=60)
    def prepare_instance_boot(self, task):
        if not task.driver.storage.should_write_image(task):
            task.driver.boot.prepare_instance(task)
            return

        node = task.node
        try:
            uuid_dict_returned = node.driver_internal_info['deployment_uuids']
        except KeyError:
            raise exception.InstanceDeployFailure(
                _('Invalid internal state: the write_image deploy step has '
                  'not been called before prepare_instance_boot'))
        root_uuid = uuid_dict_returned.get('root uuid')
        efi_sys_uuid = uuid_dict_returned.get('efi system partition uuid')
        prep_boot_part_uuid = uuid_dict_returned.get(
            'PrEP Boot partition uuid')

        self.prepare_instance_to_boot(task, root_uuid, efi_sys_uuid,
                                      prep_boot_part_uuid=prep_boot_part_uuid)

    @METRICS.timer('ISCSIDeploy.prepare')
    @task_manager.require_exclusive_lock
    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        Generates the TFTP configuration for PXE-booting both the deployment
        and user images, fetches the TFTP image from Glance and add it to the
        local cache.

        :param task: a TaskManager instance containing the node to act on.
        :raises: NetworkError: if the previous cleaning ports cannot be removed
            or if new cleaning ports cannot be created.
        :raises: InvalidParameterValue when the wrong power state is specified
            or the wrong driver info is specified for power management.
        :raises: StorageError If the storage driver is unable to attach the
            configured volumes.
        :raises: other exceptions by the node's power driver if something
            wrong occurred during the power action.
        :raises: any boot interface's prepare_ramdisk exceptions.
        """
        node = task.node
        deploy_utils.populate_storage_driver_internal_info(task)
        if node.provision_state in [states.ACTIVE, states.ADOPTING]:
            task.driver.boot.prepare_instance(task)
        else:
            if node.provision_state == states.DEPLOYING:
                fast_track_deploy = manager_utils.is_fast_track(task)
                if fast_track_deploy:
                    # The agent has already recently checked in and we are
                    # configured to take that as an indicator that we can
                    # skip ahead.
                    LOG.debug('The agent for node %(node)s has recently '
                              'checked in, and the node power will remain '
                              'unmodified.',
                              {'node': task.node.uuid})
                else:
                    # Adding the node to provisioning network so that the dhcp
                    # options get added for the provisioning port.
                    manager_utils.node_power_action(task, states.POWER_OFF)
                # NOTE(vdrok): in case of rebuild, we have tenant network
                # already configured, unbind tenant ports if present
                if task.driver.storage.should_write_image(task):
                    if not fast_track_deploy:
                        power_state_to_restore = (
                            manager_utils.power_on_node_if_needed(task))
                    task.driver.network.unconfigure_tenant_networks(task)
                    task.driver.network.add_provisioning_network(task)
                    if not fast_track_deploy:
                        manager_utils.restore_power_state_if_needed(
                            task, power_state_to_restore)
                task.driver.storage.attach_volumes(task)
                if (not task.driver.storage.should_write_image(task)
                    or fast_track_deploy):
                    # We have nothing else to do as this is handled in the
                    # backend storage system, and we can return to the caller
                    # as we do not need to boot the agent to deploy.
                    # Alternatively, we are in a fast track deployment
                    # and have nothing else to do.
                    return

            deploy_opts = deploy_utils.build_agent_options(node)
            task.driver.boot.prepare_ramdisk(task, deploy_opts)

    @METRICS.timer('ISCSIDeploy.clean_up')
    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Unlinks TFTP and instance images and triggers image cache cleanup.
        Removes the TFTP configuration files for this node.

        :param task: a TaskManager instance containing the node to act on.
        """
        deploy_utils.destroy_images(task.node.uuid)
        super(ISCSIDeploy, self).clean_up(task)
        if utils.pop_node_nested_field(task.node, 'driver_internal_info',
                                       'deployment_uuids'):
            task.node.save()
