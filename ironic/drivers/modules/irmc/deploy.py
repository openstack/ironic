# Copyright 2015 FUJITSU LIMITED
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
iRMC Deploy Driver
"""

import os
import shutil
import tempfile

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import images
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules import iscsi_deploy

scci = importutils.try_import('scciclient.irmc.scci')

CONF = cfg.CONF

try:
    if CONF.debug:
        scci.DEBUG = True
except Exception:
    pass

opts = [
    cfg.StrOpt('remote_image_share_root',
               default='/remote_image_share_root',
               help='Ironic conductor node\'s "NFS" or "CIFS" root path'),
    cfg.StrOpt('remote_image_server',
               help='IP of remote image server'),
    cfg.StrOpt('remote_image_share_type',
               default='CIFS',
               help='Share type of virtual media, either "NFS" or "CIFS"'),
    cfg.StrOpt('remote_image_share_name',
               default='share',
               help='share name of remote_image_server'),
    cfg.StrOpt('remote_image_user_name',
               help='User name of remote_image_server'),
    cfg.StrOpt('remote_image_user_password', secret=True,
               help='Password of remote_image_user_name'),
    cfg.StrOpt('remote_image_user_domain',
               default='',
               help='Domain name of remote_image_user_name'),
]

CONF.register_opts(opts, group='irmc')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'irmc_deploy_iso': _("Deployment ISO image file name. "
                         "Required."),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES

CONF.import_opt('pxe_append_params', 'ironic.drivers.modules.iscsi_deploy',
                group='pxe')

SUPPORTED_SHARE_TYPES = ('nfs', 'cifs')


def _parse_config_option():
    """Parse config file options.

    This method checks config file options validity.

    :raises: InvalidParameterValue, if config option has invalid value.
    """
    error_msgs = []
    if not os.path.isdir(CONF.irmc.remote_image_share_root):
        error_msgs.append(
            _("Value '%s' for remote_image_share_root isn't a directory "
              "or doesn't exist.") %
            CONF.irmc.remote_image_share_root)
    if CONF.irmc.remote_image_share_type.lower() not in SUPPORTED_SHARE_TYPES:
        error_msgs.append(
            _("Value '%s' for remote_image_share_type is not supported "
              "value either 'NFS' or 'CIFS'.") %
            CONF.irmc.remote_image_share_type)
    if error_msgs:
        msg = (_("The following errors were encountered while parsing "
                 "config file:%s") % error_msgs)
        raise exception.InvalidParameterValue(msg)


def _parse_driver_info(node):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required or optional information properly
    for this driver to deploy images to the node.

    :param node: a target node of the deployment
    :returns: the driver_info values of the node.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    d_info = node.driver_info
    deploy_info = {}

    deploy_info['irmc_deploy_iso'] = d_info.get('irmc_deploy_iso')
    error_msg = _("Error validating iRMC virtual media deploy. Some parameters"
                  " were missing in node's driver_info")
    deploy_utils.check_for_missing_params(deploy_info, error_msg)

    if service_utils.is_image_href_ordinary_file_name(
            deploy_info['irmc_deploy_iso']):
        deploy_iso = os.path.join(CONF.irmc.remote_image_share_root,
                                  deploy_info['irmc_deploy_iso'])
        if not os.path.isfile(deploy_iso):
            msg = (_("Deploy ISO file, %(deploy_iso)s, "
                     "not found for node: %(node)s.") %
                   {'deploy_iso': deploy_iso, 'node': node.uuid})
            raise exception.InvalidParameterValue(msg)

    return deploy_info


def _parse_instance_info(node):
    """Gets the instance specific Node deployment info.

    This method validates whether the 'instance_info' property of the
    supplied node contains the required or optional information properly
    for this driver to deploy images to the node.

    :param node: a target node of the deployment
    :returns:  the instance_info values of the node.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    i_info = node.instance_info
    deploy_info = {}

    if i_info.get('irmc_boot_iso'):
        deploy_info['irmc_boot_iso'] = i_info['irmc_boot_iso']

        if service_utils.is_image_href_ordinary_file_name(
                deploy_info['irmc_boot_iso']):
            boot_iso = os.path.join(CONF.irmc.remote_image_share_root,
                                    deploy_info['irmc_boot_iso'])

            if not os.path.isfile(boot_iso):
                msg = (_("Boot ISO file, %(boot_iso)s, "
                         "not found for node: %(node)s.") %
                       {'boot_iso': boot_iso, 'node': node.uuid})
                raise exception.InvalidParameterValue(msg)

    return deploy_info


def _parse_deploy_info(node):
    """Gets the instance and driver specific Node deployment info.

    This method validates whether the 'instance_info' and 'driver_info'
    property of the supplied node contains the required information for
    this driver to deploy images to the node.

    :param node: a target node of the deployment
    :returns: a dict with the instance_info and driver_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    deploy_info = {}
    deploy_info.update(iscsi_deploy.parse_instance_info(node))
    deploy_info.update(_parse_driver_info(node))
    deploy_info.update(_parse_instance_info(node))

    return deploy_info


def _reboot_into_deploy_iso(task, ramdisk_options):
    """Reboots the node into a given deploy ISO.

    This method attaches the given deploy ISO as virtual media, prepares the
    arguments for ramdisk in virtual media floppy, and then reboots the node.

    :param task: a TaskManager instance containing the node to act on.
    :param ramdisk_options: the options to be passed to the ramdisk in virtual
        media floppy.
    :raises: ImageRefValidationFailed if no image service can handle specified
       href.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: IRMCOperationError, if some operation on iRMC failed.
    :raises: InvalidParameterValue if the validation of the
        PowerInterface or ManagementInterface fails.
    """
    d_info = task.node.driver_info

    deploy_iso_href = d_info['irmc_deploy_iso']
    if service_utils.is_image_href_ordinary_file_name(deploy_iso_href):
        deploy_iso_file = deploy_iso_href
    else:
        deploy_iso_file = _get_deploy_iso_name(task.node)
        deploy_iso_fullpathname = os.path.join(
            CONF.irmc.remote_image_share_root, deploy_iso_file)
        images.fetch(task.context, deploy_iso_href, deploy_iso_fullpathname)

    setup_vmedia_for_boot(task, deploy_iso_file, ramdisk_options)
    manager_utils.node_set_boot_device(task, boot_devices.CDROM)
    manager_utils.node_power_action(task, states.REBOOT)


def _get_deploy_iso_name(node):
    """Returns the deploy ISO file name for a given node.

    :param node: the node for which ISO file name is to be provided.
    """
    return "deploy-%s.iso" % node.uuid


def _get_boot_iso_name(node):
    """Returns the boot ISO file name for a given node.

    :param node: the node for which ISO file name is to be provided.
    """
    return "boot-%s.iso" % node.uuid


def _prepare_boot_iso(task, root_uuid):
    """Prepare a boot ISO to boot the node.

    :param task: a TaskManager instance containing the node to act on.
    :param root_uuid: the uuid of the root partition.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    :raises: ImageCreationFailed, if creating boot ISO
       for BIOS boot_mode failed.
    """
    deploy_info = _parse_deploy_info(task.node)
    driver_internal_info = task.node.driver_internal_info

    # fetch boot iso
    if deploy_info.get('irmc_boot_iso'):
        boot_iso_href = deploy_info['irmc_boot_iso']
        if service_utils.is_image_href_ordinary_file_name(boot_iso_href):
            driver_internal_info['irmc_boot_iso'] = boot_iso_href
        else:
            boot_iso_filename = _get_boot_iso_name(task.node)
            boot_iso_fullpathname = os.path.join(
                CONF.irmc.remote_image_share_root, boot_iso_filename)
            images.fetch(task.context, boot_iso_href, boot_iso_fullpathname)

            driver_internal_info['irmc_boot_iso'] = boot_iso_filename

    # create boot iso
    else:
        image_href = deploy_info['image_source']
        image_props = ['kernel_id', 'ramdisk_id']
        image_properties = images.get_image_properties(
            task.context, image_href, image_props)
        kernel_href = (task.node.instance_info.get('kernel') or
                       image_properties['kernel_id'])
        ramdisk_href = (task.node.instance_info.get('ramdisk') or
                        image_properties['ramdisk_id'])

        deploy_iso_filename = _get_deploy_iso_name(task.node)
        deploy_iso = ('file://' + os.path.join(
            CONF.irmc.remote_image_share_root, deploy_iso_filename))
        boot_mode = deploy_utils.get_boot_mode_for_deploy(task.node)
        kernel_params = CONF.pxe.pxe_append_params

        boot_iso_filename = _get_boot_iso_name(task.node)
        boot_iso_fullpathname = os.path.join(
            CONF.irmc.remote_image_share_root, boot_iso_filename)

        images.create_boot_iso(task.context, boot_iso_fullpathname,
                               kernel_href, ramdisk_href,
                               deploy_iso, root_uuid,
                               kernel_params, boot_mode)

        driver_internal_info['irmc_boot_iso'] = boot_iso_filename

    # save driver_internal_info['irmc_boot_iso']
    task.node.driver_internal_info = driver_internal_info
    task.node.save()


def _get_floppy_image_name(node):
    """Returns the floppy image name for a given node.

    :param node: the node for which image name is to be provided.
    """
    return "image-%s.img" % node.uuid


def _prepare_floppy_image(task, params):
    """Prepares the floppy image for passing the parameters.

    This method prepares a temporary vfat filesystem image, which
    contains the parameters to be passed to the ramdisk.
    Then it uploads the file NFS or CIFS server.

    :param task: a TaskManager instance containing the node to act on.
    :param params: a dictionary containing 'parameter name'->'value' mapping
        to be passed to the deploy ramdisk via the floppy image.
    :returns: floppy image filename
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: IRMCOperationError, if copying floppy image file failed.
    """
    floppy_filename = _get_floppy_image_name(task.node)
    floppy_fullpathname = os.path.join(
        CONF.irmc.remote_image_share_root, floppy_filename)

    with tempfile.NamedTemporaryFile() as vfat_image_tmpfile_obj:
        images.create_vfat_image(vfat_image_tmpfile_obj.name,
                                 parameters=params)
        try:
            shutil.copyfile(vfat_image_tmpfile_obj.name,
                            floppy_fullpathname)
        except IOError as e:
            operation = _("Copying floppy image file")
            raise exception.IRMCOperationError(
                operation=operation, error=e)

    return floppy_filename


def setup_vmedia_for_boot(task, bootable_iso_filename, parameters=None):
    """Sets up the node to boot from the boot ISO image.

    This method attaches a boot_iso on the node and passes
    the required parameters to it via a virtual floppy image.

    :param task: a TaskManager instance containing the node to act on.
    :param bootable_iso_filename: a bootable ISO image to attach to.
        The iso file should be present in NFS/CIFS server.
    :param parameters: the parameters to pass in a virtual floppy image
        in a dictionary.  This is optional.
    :raises: ImageCreationFailed, if it failed while creating a floppy image.
    :raises: IRMCOperationError, if attaching a virtual media failed.
    """
    LOG.info(_LI("Setting up node %s to boot from virtual media"),
             task.node.uuid)

    _detach_virtual_cd(task.node)
    _detach_virtual_fd(task.node)

    if parameters:
        floppy_image_filename = _prepare_floppy_image(task, parameters)
        _attach_virtual_fd(task.node, floppy_image_filename)

    _attach_virtual_cd(task.node, bootable_iso_filename)


def _cleanup_vmedia_boot(task):
    """Cleans a node after a virtual media boot.

    This method cleans up a node after a virtual media boot.
    It deletes a floppy image if it exists in NFS/CIFS server.
    It also ejects both the virtual media cdrom and the virtual media floppy.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IRMCOperationError if ejecting virtual media failed.
    """
    LOG.debug("Cleaning up node %s after virtual media boot", task.node.uuid)

    node = task.node
    _detach_virtual_cd(node)
    _detach_virtual_fd(node)

    _remove_share_file(_get_floppy_image_name(node))
    _remove_share_file(_get_deploy_iso_name(node))


def _remove_share_file(share_filename):
    """remove a file in the share file system.

    :param share_filename: a file name to be removed.
    """
    share_fullpathname = os.path.join(
        CONF.irmc.remote_image_share_name, share_filename)
    utils.unlink_without_raise(share_fullpathname)


def _attach_virtual_cd(node, bootable_iso_filename):
    """Attaches the given url as virtual media on the node.

    :param node: an ironic node object.
    :param bootable_iso_filename: a bootable ISO image to attach to.
        The iso file should be present in NFS/CIFS server.
    :raises: IRMCOperationError if attaching virtual media failed.
    """
    try:
        irmc_client = irmc_common.get_irmc_client(node)

        cd_set_params = scci.get_virtual_cd_set_params_cmd(
            CONF.irmc.remote_image_server,
            CONF.irmc.remote_image_user_domain,
            scci.get_share_type(CONF.irmc.remote_image_share_type),
            CONF.irmc.remote_image_share_name,
            bootable_iso_filename,
            CONF.irmc.remote_image_user_name,
            CONF.irmc.remote_image_user_password)

        irmc_client(cd_set_params, async=False)
        irmc_client(scci.MOUNT_CD, async=False)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception(_LE("Error while inserting virtual cdrom "
                          "from node %(uuid)s. Error: %(error)s"),
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Inserting virtual cdrom")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info(_LI("Attached virtual cdrom successfully"
                 " for node %s"), node.uuid)


def _detach_virtual_cd(node):
    """Detaches virtual cdrom on the node.

    :param node: an ironic node object.
    :raises: IRMCOperationError if eject virtual cdrom failed.
    """
    try:
        irmc_client = irmc_common.get_irmc_client(node)

        irmc_client(scci.UNMOUNT_CD)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception(_LE("Error while ejecting virtual cdrom "
                          "from node %(uuid)s. Error: %(error)s"),
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Ejecting virtual cdrom")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info(_LI("Detached virtual cdrom successfully"
                 " for node %s"), node.uuid)


def _attach_virtual_fd(node, floppy_image_filename):
    """Attaches virtual floppy on the node.

    :param node: an ironic node object.
    :raises: IRMCOperationError if insert virtual floppy failed.
    """
    try:
        irmc_client = irmc_common.get_irmc_client(node)

        fd_set_params = scci.get_virtual_fd_set_params_cmd(
            CONF.irmc.remote_image_server,
            CONF.irmc.remote_image_user_domain,
            scci.get_share_type(CONF.irmc.remote_image_share_type),
            CONF.irmc.remote_image_share_name,
            floppy_image_filename,
            CONF.irmc.remote_image_user_name,
            CONF.irmc.remote_image_user_password)

        irmc_client(fd_set_params, async=False)
        irmc_client(scci.MOUNT_FD, async=False)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception(_LE("Error while inserting virtual floppy "
                          "from node %(uuid)s. Error: %(error)s"),
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Inserting virtual floppy")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info(_LI("Attached virtual floppy successfully"
                 " for node %s"), node.uuid)


def _detach_virtual_fd(node):
    """Detaches virtual media on the node.

    :param node: an ironic node object.
    :raises: IRMCOperationError if eject virtual media failed.
    """
    try:
        irmc_client = irmc_common.get_irmc_client(node)

        irmc_client(scci.UNMOUNT_FD)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception(_LE("Error while ejecting virtual floppy "
                          "from node %(uuid)s. Error: %(error)s"),
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Ejecting virtual floppy")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info(_LI("Detached virtual floppy successfully"
                 " for node %s"), node.uuid)


def _check_share_fs_mounted():
    """Check if Share File System (NFS or CIFS) is mounted.

    :raises: InvalidParameterValue, if config option has invalid value.
    :raises: IRMCSharedFileSystemNotMounted, if shared file system is
        not mounted.
    """
    _parse_config_option()
    if not os.path.ismount(CONF.irmc.remote_image_share_root):
        raise exception.IRMCSharedFileSystemNotMounted(
            share=CONF.irmc.remote_image_share_root)


class IRMCVirtualMediaIscsiDeploy(base.DeployInterface):
    """Interface for iSCSI deploy-related actions."""

    def __init__(self):
        """Constructor of IRMCVirtualMediaIscsiDeploy.

        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if config option has invalid value.
        """
        _check_share_fs_mounted()
        super(IRMCVirtualMediaIscsiDeploy, self).__init__()

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the deployment information for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue, if config option has invalid value.
        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if some information is invalid.
        :raises: MissingParameterValue if 'kernel_id' and 'ramdisk_id' are
            missing in the Glance image, or if 'kernel' and 'ramdisk' are
            missing in the Non Glance image.
        """
        _check_share_fs_mounted()
        iscsi_deploy.validate(task)

        d_info = _parse_deploy_info(task.node)
        if task.node.driver_internal_info.get('is_whole_disk_image'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        deploy_utils.validate_image_properties(task.context, d_info,
                                               props)
        deploy_utils.validate_capabilities(task.node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Start deployment of the task's node.

        Fetches the instance image, prepares the options for the deployment
        ramdisk, sets the node to boot from virtual media cdrom, and reboots
        the given node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        :raises: InstanceDeployFailure, if image size if greater than root
            partition.
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: IRMCOperationError, if some operation on iRMC fails.
        """
        node = task.node
        manager_utils.node_power_action(task, states.POWER_OFF)

        iscsi_deploy.cache_instance_image(task.context, node)
        iscsi_deploy.check_image_size(task)

        deploy_ramdisk_opts = iscsi_deploy.build_deploy_ramdisk_options(node)
        agent_opts = deploy_utils.build_agent_options(node)
        deploy_ramdisk_opts.update(agent_opts)
        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        deploy_ramdisk_opts['BOOTIF'] = deploy_nic_mac

        _reboot_into_deploy_iso(task, deploy_ramdisk_opts)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Power off the node. All actual clean-up is done in the clean_up()
        method which should be called separately.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        """
        _remove_share_file(_get_boot_iso_name(task.node))
        driver_internal_info = task.node.driver_internal_info
        driver_internal_info.pop('irmc_boot_iso', None)
        task.node.driver_internal_info = driver_internal_info
        task.node.save()
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for the task's node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `deploy`.

        :param task: a TaskManager instance containing the node to act on.
        """
        pass

    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Unlinks instance image and triggers image cache cleanup.

        :param task: a TaskManager instance containing the node to act on.
        """
        _cleanup_vmedia_boot(task)
        iscsi_deploy.destroy_images(task.node.uuid)

    def take_over(self, task):
        pass


class IRMCVirtualMediaAgentDeploy(base.DeployInterface):

    def __init__(self):
        """Constructor of IRMCVirtualMediaAgentDeploy.

        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if config option has invalid value.
        """
        _check_share_fs_mounted()
        super(IRMCVirtualMediaAgentDeploy, self).__init__()

    """Interface for Agent deploy-related actions."""
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        :param task: a TaskManager instance
        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if config option has invalid value.
        :raises: MissingParameterValue if some parameters are missing.
        """
        _check_share_fs_mounted()
        _parse_driver_info(task.node)
        deploy_utils.validate_capabilities(task.node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Prepares the options for the agent ramdisk and sets the node to boot
        from virtual media cdrom.

        :param task: a TaskManager instance.
        :returns: states.DEPLOYWAIT
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: IRMCOperationError, if some operation on iRMC fails.
        """
        deploy_ramdisk_opts = deploy_utils.build_agent_options(task.node)
        _reboot_into_deploy_iso(task, deploy_ramdisk_opts)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: states.DELETED
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        node = task.node
        node.instance_info = agent.build_instance_info_for_deploy(task)
        node.save()

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        Ejects the attached virtual media from the iRMC and also removes
        the floppy image from the share file system, if it exists.

        :param task: a TaskManager instance.
        """
        _cleanup_vmedia_boot(task)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        :param task: a TaskManager instance.
        """
        pass


class VendorPassthru(agent_base_vendor.BaseAgentVendor):
    """Vendor-specific interfaces for iRMC deploy drivers."""

    def get_properties(self):
        return COMMON_PROPERTIES

    def validate(self, task, method, **kwargs):
        """Validate vendor-specific actions.

        Checks if a valid vendor passthru method was passed and validates
        the parameters for the vendor passthru method.

        :param task: a TaskManager instance containing the node to act on.
        :param method: method to be validated.
        :param kwargs: kwargs containing the vendor passthru method's
            parameters.
        :raises: MissingParameterValue, if some required parameters were not
            passed.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        if method == 'pass_deploy_info':
            iscsi_deploy.get_deploy_info(task.node, **kwargs)
        elif method == 'pass_bootloader_install_info':
            iscsi_deploy.validate_pass_bootloader_info_input(task, kwargs)

    def _configure_vmedia_boot(self, task, root_uuid_or_disk_id):
        """Configure vmedia boot for the node."""
        node = task.node
        _prepare_boot_iso(task, root_uuid_or_disk_id)
        setup_vmedia_for_boot(
            task, node.driver_internal_info['irmc_boot_iso'])
        manager_utils.node_set_boot_device(task, boot_devices.CDROM,
                                           persistent=True)

    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def pass_bootloader_install_info(self, task, **kwargs):
        """Accepts the results of bootloader installation.

        This method acts as a vendor passthru and accepts the result of
        bootloader installation. If the bootloader installation was
        successful, then it notifies the baremetal to proceed to reboot
        and makes the instance active. If bootloader installation failed,
        then it sets provisioning as failed and powers off the node.

        :param task: A TaskManager object.
        :param kwargs: The arguments sent with vendor passthru.  The expected
            kwargs are::

                'key': The deploy key for authorization
                'status': 'SUCCEEDED' or 'FAILED'
                'error': The error message if status == 'FAILED'
                'address': The IP address of the ramdisk
        """
        LOG.warning(_LW("The node %s is using the bash deploy ramdisk for "
                        "its deployment. This deploy ramdisk has been "
                        "deprecated. Please use the ironic-python-agent "
                        "(IPA) ramdisk instead."), task.node.uuid)
        task.process_event('resume')
        iscsi_deploy.validate_bootloader_install_status(task, kwargs)
        iscsi_deploy.finish_deploy(task, kwargs['address'])

    @base.passthru(['POST'])
    @task_manager.require_exclusive_lock
    def pass_deploy_info(self, task, **kwargs):
        """Continues the iSCSI deployment from where ramdisk left off.

        This method continues the iSCSI deployment from the conductor node
        and writes the deploy image to the bare metal's disk.  After that,
        it does the following depending on boot_option for deploy:

        - If the boot_option requested for this deploy is 'local', then it
          sets the node to boot from disk (ramdisk installs the boot loader
          present within the image to the bare metal's disk).
        - If the boot_option requested is 'netboot' or no boot_option is
          requested, it finds/creates the boot ISO to boot the instance
          image, attaches the boot ISO to the bare metal and then sets
          the node to boot from CDROM.

        :param task: a TaskManager instance containing the node to act on.
        :param kwargs: kwargs containing parameters for iSCSI deployment.
        :raises: InvalidState
        """
        node = task.node
        LOG.warning(_LW("The node %s is using the bash deploy ramdisk for "
                        "its deployment. This deploy ramdisk has been "
                        "deprecated. Please use the ironic-python-agent "
                        "(IPA) ramdisk instead."), node.uuid)
        task.process_event('resume')

        LOG.debug('Continuing iSCSI virtual media deployment on node %s',
                  node.uuid)

        is_whole_disk_image = node.driver_internal_info.get(
            'is_whole_disk_image')
        uuid_dict = iscsi_deploy.continue_deploy(task, **kwargs)
        root_uuid_or_disk_id = uuid_dict.get(
            'root uuid', uuid_dict.get('disk identifier'))

        try:
            _cleanup_vmedia_boot(task)
            if (deploy_utils.get_boot_option(node) == "local" or
                is_whole_disk_image):
                manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                                   persistent=True)

                # Ask the ramdisk to install bootloader and
                # wait for the call-back through the vendor passthru
                # 'pass_bootloader_install_info', if it's not a whole
                # disk image.
                if not is_whole_disk_image:
                    deploy_utils.notify_ramdisk_to_proceed(kwargs['address'])
                    task.process_event('wait')
                    return

            else:
                self._configure_vmedia_boot(task, root_uuid_or_disk_id)

        except Exception as e:
            LOG.exception(_LE('Deploy failed for instance %(instance)s. '
                              'Error: %(error)s'),
                          {'instance': node.instance_uuid, 'error': e})
            msg = _('Failed to continue iSCSI deployment.')
            deploy_utils.set_failed_state(task, msg)
        else:
            iscsi_deploy.finish_deploy(task, kwargs.get('address'))

    @task_manager.require_exclusive_lock
    def continue_deploy(self, task, **kwargs):
        """Method invoked when deployed with the IPA ramdisk.

        This method is invoked during a heartbeat from an agent when
        the node is in wait-call-back state. This deploys the image on
        the node and then configures the node to boot according to the
        desired boot option (netboot or localboot).

        :param task: a TaskManager object containing the node.
        :param kwargs: the kwargs passed from the heartbeat method.
        :raises: InstanceDeployFailure, if it encounters some error during
            the deploy.
        """
        node = task.node
        task.process_event('resume')

        LOG.debug('Continuing IPA deployment on node %s', node.uuid)

        is_whole_disk_image = node.driver_internal_info.get(
            'is_whole_disk_image')
        _cleanup_vmedia_boot(task)
        uuid_dict = iscsi_deploy.do_agent_iscsi_deploy(task, self._client)
        root_uuid = uuid_dict.get('root uuid')

        if (deploy_utils.get_boot_option(node) == "local" or
            is_whole_disk_image):
            efi_system_part_uuid = uuid_dict.get(
                'efi system partition uuid')
            self.configure_local_boot(
                task, root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid)
        else:
            self._configure_vmedia_boot(task, root_uuid)

        self.reboot_and_finish_deploy(task)


class IRMCVirtualMediaAgentVendorInterface(agent.AgentVendorInterface):
    """Interface for vendor passthru related actions."""

    def reboot_to_instance(self, task, **kwargs):
        node = task.node
        LOG.debug('Preparing to reboot to instance for node %s',
                  node.uuid)

        _cleanup_vmedia_boot(task)

        super(IRMCVirtualMediaAgentVendorInterface,
              self).reboot_to_instance(task, **kwargs)
