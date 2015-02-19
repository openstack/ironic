# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
PXE Driver and supporting meta-classes.
"""

import os
import shutil

from oslo_config import cfg
from six.moves.urllib import parse as urlparse

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import image_service as service
from ironic.common import keystone
from ironic.common import paths
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import log as logging


pxe_opts = [
    cfg.StrOpt('pxe_config_template',
               default=paths.basedir_def(
                    'drivers/modules/pxe_config.template'),
               help='Template file for PXE configuration.'),
    cfg.StrOpt('uefi_pxe_config_template',
               default=paths.basedir_def(
                    'drivers/modules/elilo_efi_pxe_config.template'),
               help='Template file for PXE configuration for UEFI boot'
                    ' loader.'),
    cfg.StrOpt('tftp_server',
               default='$my_ip',
               help='IP address of Ironic compute node\'s tftp server.'),
    cfg.StrOpt('tftp_root',
               default='/tftpboot',
               help='Ironic compute node\'s tftp root path.'),
    cfg.StrOpt('tftp_master_path',
               default='/tftpboot/master_images',
               help='Directory where master tftp images are stored on disk.'),
    # NOTE(dekehn): Additional boot files options may be created in the event
    #  other architectures require different boot files.
    cfg.StrOpt('pxe_bootfile_name',
               default='pxelinux.0',
               help='Bootfile DHCP parameter.'),
    cfg.StrOpt('uefi_pxe_bootfile_name',
               default='elilo.efi',
               help='Bootfile DHCP parameter for UEFI boot mode.'),
    cfg.StrOpt('http_url',
                help='Ironic compute node\'s HTTP server URL. '
                     'Example: http://192.1.2.3:8080'),
    cfg.StrOpt('http_root',
                default='/httpboot',
                help='Ironic compute node\'s HTTP root path.'),
    cfg.BoolOpt('ipxe_enabled',
                default=False,
                help='Enable iPXE boot.'),
    cfg.StrOpt('ipxe_boot_script',
               default=paths.basedir_def(
                    'drivers/modules/boot.ipxe'),
               help='The path to the main iPXE script file.'),
    ]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(pxe_opts, group='pxe')
CONF.import_opt('deploy_callback_timeout', 'ironic.conductor.manager',
                group='conductor')


REQUIRED_PROPERTIES = {
    'pxe_deploy_kernel': _("UUID (from Glance) of the deployment kernel. "
                           "Required."),
    'pxe_deploy_ramdisk': _("UUID (from Glance) of the ramdisk that is "
                            "mounted at boot time. Required."),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES


def _parse_driver_info(node):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the driver_info values.
    :raises: MissingParameterValue
    """
    info = node.driver_info
    d_info = {}
    d_info['deploy_kernel'] = info.get('pxe_deploy_kernel')
    d_info['deploy_ramdisk'] = info.get('pxe_deploy_ramdisk')

    error_msg = _("Cannot validate PXE bootloader. Some parameters were"
                  " missing in node's driver_info")
    deploy_utils.check_for_missing_params(d_info, error_msg, 'pxe_')

    return d_info


def _parse_deploy_info(node):
    """Gets the instance and driver specific Node deployment info.

    This method validates whether the 'instance_info' and 'driver_info'
    property of the supplied node contains the required information for
    this driver to deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the instance_info and driver_info values.
    :raises: MissingParameterValue
    :raises: InvalidParameterValue
    """
    info = {}
    info.update(iscsi_deploy.parse_instance_info(node))
    info.update(_parse_driver_info(node))
    return info


def _build_pxe_config_options(node, pxe_info, ctx):
    """Build the PXE config options for a node

    This method builds the PXE boot options for a node,
    given all the required parameters.

    The options should then be passed to pxe_utils.create_pxe_config to
    create the actual config files.

    :param node: a single Node.
    :param pxe_info: a dict of values to set on the configuration file
    :param ctx: security context
    :returns: A dictionary of pxe options to be used in the pxe bootfile
        template.
    """
    if CONF.pxe.ipxe_enabled:
        deploy_kernel = '/'.join([CONF.pxe.http_url, node.uuid,
                                  'deploy_kernel'])
        deploy_ramdisk = '/'.join([CONF.pxe.http_url, node.uuid,
                                   'deploy_ramdisk'])
        kernel = '/'.join([CONF.pxe.http_url, node.uuid, 'kernel'])
        ramdisk = '/'.join([CONF.pxe.http_url, node.uuid, 'ramdisk'])
    else:
        deploy_kernel = pxe_info['deploy_kernel'][1]
        deploy_ramdisk = pxe_info['deploy_ramdisk'][1]
        kernel = pxe_info['kernel'][1]
        ramdisk = pxe_info['ramdisk'][1]

    pxe_options = {
        'deployment_aki_path': deploy_kernel,
        'deployment_ari_path': deploy_ramdisk,
        'aki_path': kernel,
        'ari_path': ramdisk,
        'pxe_append_params': CONF.pxe.pxe_append_params,
        'tftp_server': CONF.pxe.tftp_server
    }

    deploy_ramdisk_options = iscsi_deploy.build_deploy_ramdisk_options(node)
    pxe_options.update(deploy_ramdisk_options)

    # NOTE(lucasagomes): We are going to extend the normal PXE config
    # to also contain the agent options so it could be used for both the
    # DIB ramdisk and the IPA ramdisk
    agent_opts = agent.build_agent_options(node)
    pxe_options.update(agent_opts)

    return pxe_options


def _get_token_file_path(node_uuid):
    """Generate the path for PKI token file."""
    return os.path.join(CONF.pxe.tftp_root, 'token-' + node_uuid)


@image_cache.cleanup(priority=25)
class TFTPImageCache(image_cache.ImageCache):
    def __init__(self, image_service=None):
        super(TFTPImageCache, self).__init__(
            CONF.pxe.tftp_master_path,
            # MiB -> B
            cache_size=CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            cache_ttl=CONF.pxe.image_cache_ttl * 60,
            image_service=image_service)


def _cache_ramdisk_kernel(ctx, node, pxe_info):
    """Fetch the necessary kernels and ramdisks for the instance."""
    fileutils.ensure_tree(
        os.path.join(pxe_utils.get_root_dir(), node.uuid))
    LOG.debug("Fetching kernel and ramdisk for node %s",
              node.uuid)
    deploy_utils.fetch_images(ctx, TFTPImageCache(), pxe_info.values(),
                              CONF.force_raw_images)


def _get_image_info(node, ctx):
    """Generate the paths for tftp files for this instance

    Raises IronicException if
    - instance does not contain kernel_id or ramdisk_id
    - deploy_kernel_id or deploy_ramdisk_id can not be read from
      driver_info and defaults are not set

    """
    d_info = _parse_deploy_info(node)
    image_info = {}
    root_dir = pxe_utils.get_root_dir()

    image_info.update(pxe_utils.get_deploy_kr_info(node.uuid, d_info))

    i_info = node.instance_info
    labels = ('kernel', 'ramdisk')
    if not (i_info.get('kernel') and i_info.get('ramdisk')):
        glance_service = service.Service(version=1, context=ctx)
        iproperties = glance_service.show(d_info['image_source'])['properties']
        for label in labels:
            i_info[label] = str(iproperties[label + '_id'])
        node.instance_info = i_info
        node.save()

    for label in labels:
        image_info[label] = (
            i_info[label],
            os.path.join(root_dir, node.uuid, label)
        )

    return image_info


def _create_token_file(task):
    """Save PKI token to file."""
    token_file_path = _get_token_file_path(task.node.uuid)
    token = task.context.auth_token
    if token:
        timeout = CONF.conductor.deploy_callback_timeout
        if timeout and keystone.token_expires_soon(token, timeout):
            token = keystone.get_admin_auth_token()
        utils.write_to_file(token_file_path, token)
    else:
        utils.unlink_without_raise(token_file_path)


def _destroy_token_file(node):
    """Delete PKI token file."""
    token_file_path = _get_token_file_path(node['uuid'])
    utils.unlink_without_raise(token_file_path)


def try_set_boot_device(task, device, persistent=True):
    # NOTE(faizan): Under UEFI boot mode, setting of boot device may differ
    # between different machines. IPMI does not work for setting boot
    # devices in UEFI mode for certain machines.
    # Expected IPMI failure for uefi boot mode. Logging a message to
    # set the boot device manually and continue with deploy.
    try:
        manager_utils.node_set_boot_device(task, device, persistent=persistent)
    except exception.IPMIFailure:
        if driver_utils.get_node_capability(task.node,
                                            'boot_mode') == 'uefi':
            LOG.warning(_LW("ipmitool is unable to set boot device while "
                            "the node %s is in UEFI boot mode. Please set "
                            "the boot device manually.") % task.node.uuid)
        else:
            raise


class PXEDeploy(base.DeployInterface):
    """PXE Deploy Interface for deploy-related actions."""

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the deployment information for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue.
        :raises: MissingParameterValue
        """
        node = task.node

        # Check the boot_mode and boot_option capabilities values.
        driver_utils.validate_boot_mode_capability(node)
        driver_utils.validate_boot_option_capability(node)

        boot_mode = driver_utils.get_node_capability(node, 'boot_mode')
        boot_option = driver_utils.get_node_capability(node, 'boot_option')

        # NOTE(lucasagomes): We don't support UEFI + localboot because
        # we do not support creating an EFI boot partition, including the
        # EFI modules and managing the bootloader variables via efibootmgr.
        if boot_mode == 'uefi' and boot_option == 'local':
            error_msg = (_("Local boot is requested, but can't be "
                           "used with node %s because it's configured "
                           "to use UEFI boot") % node.uuid)
            LOG.error(error_msg)
            raise exception.InvalidParameterValue(error_msg)

        if CONF.pxe.ipxe_enabled:
            if not CONF.pxe.http_url or not CONF.pxe.http_root:
                raise exception.MissingParameterValue(_(
                    "iPXE boot is enabled but no HTTP URL or HTTP "
                    "root was specified."))
            # iPXE and UEFI should not be configured together.
            if boot_mode == 'uefi':
                LOG.error(_LE("UEFI boot mode is not supported with "
                              "iPXE boot enabled."))
                raise exception.InvalidParameterValue(_(
                    "Conflict: iPXE is enabled, but cannot be used with node"
                    "%(node_uuid)s configured to use UEFI boot") %
                    {'node_uuid': node.uuid})

        d_info = _parse_deploy_info(node)

        iscsi_deploy.validate(task)

        props = ['kernel_id', 'ramdisk_id']
        iscsi_deploy.validate_glance_image_properties(task.context, d_info,
                                                      props)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Start deployment of the task's node'.

        Fetches instance image, creates a temporary keystone token file,
        updates the DHCP port options for next boot, and issues a reboot
        request to the power driver.
        This causes the node to boot into the deployment ramdisk and triggers
        the next phase of PXE-based deployment via
        VendorPassthru._continue_deploy().

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        """
        iscsi_deploy.cache_instance_image(task.context, task.node)
        iscsi_deploy.check_image_size(task)

        # TODO(yuriyz): more secure way needed for pass auth token
        #               to deploy ramdisk
        _create_token_file(task)
        dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
        provider = dhcp_factory.DHCPFactory()
        provider.update_dhcp(task, dhcp_opts)

        try_set_boot_device(task, boot_devices.PXE)
        manager_utils.node_power_action(task, states.REBOOT)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Power off the node. All actual clean-up is done in the clean_up()
        method which should be called separately.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        Generates the TFTP configuration for PXE-booting both the deployment
        and user images, fetches the TFTP image from Glance and add it to the
        local cache.

        :param task: a TaskManager instance containing the node to act on.
        """
        # TODO(deva): optimize this if rerun on existing files
        if CONF.pxe.ipxe_enabled:
            # Copy the iPXE boot script to HTTP root directory
            bootfile_path = os.path.join(CONF.pxe.http_root,
                                   os.path.basename(CONF.pxe.ipxe_boot_script))
            shutil.copyfile(CONF.pxe.ipxe_boot_script, bootfile_path)
        pxe_info = _get_image_info(task.node, task.context)
        pxe_options = _build_pxe_config_options(task.node, pxe_info,
                                                task.context)

        if driver_utils.get_node_capability(task.node, 'boot_mode') == 'uefi':
            pxe_config_template = CONF.pxe.uefi_pxe_config_template
        else:
            pxe_config_template = CONF.pxe.pxe_config_template

        pxe_utils.create_pxe_config(task, pxe_options,
                                    pxe_config_template)

        # FIXME(lucasagomes): If it's local boot we should not cache
        # the image kernel and ramdisk (Or even require it).
        _cache_ramdisk_kernel(task.context, task.node, pxe_info)

        # NOTE(deva): prepare may be called from conductor._do_takeover
        # in which case, it may need to regenerate the PXE config file for an
        # already-active deployment.
        if task.node.provision_state == states.ACTIVE:
            try:
                # this should have been stashed when the deploy was done
                # but let's guard, just in case it's missing
                root_uuid = task.node.driver_internal_info['root_uuid']
            except KeyError:
                LOG.warn(_LW("The UUID for the root partition can't be found, "
                         "unable to switch the pxe config from deployment "
                         "mode to service (boot) mode for node %(node)s"),
                         {"node": task.node.uuid})
            else:
                pxe_config_path = pxe_utils.get_pxe_config_file_path(
                    task.node.uuid)
                deploy_utils.switch_pxe_config(
                    pxe_config_path, root_uuid,
                    driver_utils.get_node_capability(task.node, 'boot_mode'))

    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Unlinks TFTP and instance images and triggers image cache cleanup.
        Removes the TFTP configuration files for this node. As a precaution,
        this method also ensures the keystone auth token file was removed.

        :param task: a TaskManager instance containing the node to act on.
        """
        node = task.node
        try:
            pxe_info = _get_image_info(node, task.context)
        except exception.MissingParameterValue as e:
            LOG.warning(_LW('Could not get image info to clean up images '
                            'for node %(node)s: %(err)s'),
                        {'node': node.uuid, 'err': e})
        else:
            for label in pxe_info:
                path = pxe_info[label][1]
                utils.unlink_without_raise(path)

        TFTPImageCache().clean_up()

        pxe_utils.clean_up_pxe_config(task)

        iscsi_deploy.destroy_images(node.uuid)
        _destroy_token_file(node)

    def take_over(self, task):
        if not iscsi_deploy.get_boot_option(task.node) == "local":
            # If it's going to PXE boot we need to update the DHCP server
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            provider = dhcp_factory.DHCPFactory()
            provider.update_dhcp(task, dhcp_opts)
        else:
            # If it's going to boot from the local disk, we don't need
            # PXE config files. They still need to be generated as part
            # of the prepare() because the deployment does PXE boot the
            # deploy ramdisk
            pxe_utils.clean_up_pxe_config(task)


class VendorPassthru(agent_base_vendor.BaseAgentVendor):
    """Interface to mix IPMI and PXE vendor-specific interfaces."""

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task, method, **kwargs):
        """Validates the inputs for a vendor passthru.

        If invalid, raises an exception; otherwise returns None.

        Valid methods:
        * pass_deploy_info

        :param task: a TaskManager instance containing the node to act on.
        :param method: method to be validated.
        :param kwargs: kwargs containins the method's parameters.
        :raises: InvalidParameterValue if any parameters is invalid.
        """
        if method == 'pass_deploy_info':
            driver_utils.validate_boot_option_capability(task.node)
            iscsi_deploy.get_deploy_info(task.node, **kwargs)

    @base.passthru(['POST'], method='pass_deploy_info')
    @task_manager.require_exclusive_lock
    def _continue_deploy(self, task, **kwargs):
        """Continues the deployment of baremetal node over iSCSI.

        This method continues the deployment of the baremetal node over iSCSI
        from where the deployment ramdisk has left off.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: kwargs for performing iscsi deployment.
        :raises: InvalidState
        """
        node = task.node
        task.process_event('resume')

        _destroy_token_file(node)

        root_uuid = iscsi_deploy.continue_deploy(task, **kwargs)

        if not root_uuid:
            return

        # save the node's root disk UUID so that another conductor could
        # rebuild the PXE config file. Due to a shortcoming in Nova objects,
        # we have to assign to node.driver_internal_info so the node knows it
        # has changed.
        driver_internal_info = node.driver_internal_info
        driver_internal_info['root_uuid'] = root_uuid
        node.driver_internal_info = driver_internal_info
        node.save()

        try:
            if iscsi_deploy.get_boot_option(node) == "local":
                try_set_boot_device(task, boot_devices.DISK)
                # If it's going to boot from the local disk, get rid of
                # the PXE configuration files used for the deployment
                pxe_utils.clean_up_pxe_config(task)
            else:
                pxe_config_path = pxe_utils.get_pxe_config_file_path(node.uuid)
                deploy_utils.switch_pxe_config(pxe_config_path, root_uuid,
                    driver_utils.get_node_capability(node, 'boot_mode'))

            deploy_utils.notify_deploy_complete(kwargs['address'])
            LOG.info(_LI('Deployment to node %s done'), node.uuid)
            task.process_event('done')
        except Exception as e:
            LOG.error(_LE('Deploy failed for instance %(instance)s. '
                          'Error: %(error)s'),
                      {'instance': node.instance_uuid, 'error': e})
            msg = _('Failed to continue iSCSI deployment.')
            deploy_utils.set_failed_state(task, msg)

    def _log_and_raise_deployment_error(self, task, msg):
        LOG.error(msg)
        deploy_utils.set_failed_state(task, msg)
        raise exception.InstanceDeployFailure(msg)

    @task_manager.require_exclusive_lock
    def continue_deploy(self, task, **kwargs):
        """Method invoked when deployed with the IPA ramdisk."""
        node = task.node
        LOG.debug('Continuing the deployment on node %s', node.uuid)

        task.process_event('resume')

        pxe_info = _get_image_info(node, task.context)
        pxe_options = _build_pxe_config_options(task.node, pxe_info,
                                                task.context)

        iqn = pxe_options['iscsi_target_iqn']
        result = self._client.start_iscsi_target(node, iqn)
        if result['command_status'] == 'FAILED':
            msg = (_("Failed to start the iSCSI target to deploy the "
                     "node %(node)s. Error: %(error)s") %
                   {'node': node.uuid, 'error': result['command_error']})
            self._log_and_raise_deployment_error(task, msg)

        address = urlparse.urlparse(node.driver_internal_info['agent_url'])
        address = address.hostname

        # TODO(lucasagomes): The 'error' and 'key' parameters in the
        # dictionary below are just being passed because it's needed for
        # the iscsi_deploy.continue_deploy() method, we are fooling it
        # for now. The agent driver doesn't use/need those. So we need to
        # refactor this bits here later.
        iscsi_params = {'error': result['command_error'],
                        'iqn': iqn,
                        'key': pxe_options['deployment_key'],
                        'address': address}

        # NOTE(lucasagomes): We don't use the token file with the agent,
        # but as it's created as part of deploy() we are going to remove
        # it here.
        _destroy_token_file(node)

        root_uuid = iscsi_deploy.continue_deploy(task, **iscsi_params)
        if not root_uuid:
            msg = (_("Couldn't determine the UUID of the root partition "
                     "when deploying node %s") % node.uuid)
            self._log_and_raise_deployment_error(task, msg)

        # TODO(lucasagomes): Move this bit saving the root_uuid to
        # iscsi_deploy.continue_deploy()
        driver_internal_info = node.driver_internal_info
        driver_internal_info['root_uuid'] = root_uuid
        node.driver_internal_info = driver_internal_info
        node.save()

        if iscsi_deploy.get_boot_option(node) == "local":
            # Install the boot loader
            result = self._client.install_bootloader(node, root_uuid)
            if result['command_status'] == 'FAILED':
                msg = (_("Failed to install a bootloader when "
                         "deploying node %(node)s. Error: %(error)s") %
                       {'node': node.uuid,
                        'error': result['command_error']})
                self._log_and_raise_deployment_error(task, msg)

            try:
                try_set_boot_device(task, boot_devices.DISK)
            except Exception as e:
                msg = (_("Failed to change the boot device to %(boot_dev)s "
                         "when deploying node %(node)s. Error: %(error)s") %
                       {'boot_dev': boot_devices.DISK, 'node': node.uuid,
                        'error': e})
                self._log_and_raise_deployment_error(task, msg)

            # If it's going to boot from the local disk, get rid of
            # the PXE configuration files used for the deployment
            pxe_utils.clean_up_pxe_config(task)
        else:
            pxe_config_path = pxe_utils.get_pxe_config_file_path(node.uuid)
            deploy_utils.switch_pxe_config(pxe_config_path, root_uuid,
                    driver_utils.get_node_capability(node, 'boot_mode'))

        try:
            manager_utils.node_power_action(task, states.REBOOT)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s. Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            self._log_and_raise_deployment_error(task, msg)

        task.process_event('done')
        LOG.info(_LI('Deployment to node %s done'), node.uuid)
