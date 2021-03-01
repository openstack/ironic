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
iRMC Boot Driver
"""

import os
import shutil
import tempfile
from urllib import parse as urlparse

from ironic_lib import metrics_utils
from ironic_lib import utils as ironic_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import images
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils


scci = importutils.try_import('scciclient.irmc.scci')
viom = importutils.try_import('scciclient.irmc.viom.client')

try:
    if CONF.debug:
        scci.DEBUG = True
except Exception:
    pass

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

REQUIRED_PROPERTIES = {
    'irmc_deploy_iso': _("Deployment ISO image file name. "
                         "Required."),
}

RESCUE_PROPERTIES = {
    'irmc_rescue_iso': _("UUID (from Glance) of the rescue ISO. Only "
                         "required if rescue mode is being used and ironic "
                         "is managing booting the rescue ramdisk.")
}

OPTIONAL_PROPERTIES = {
    'irmc_pci_physical_ids':
        _("Physical IDs of PCI cards. A dictionary of pairs of resource UUID "
          "and its physical ID like '<UUID>:<Physical ID>,...'. The resources "
          "are Ports and Volume connectors. The Physical ID consists of card "
          "type, slot No, and port No. The format is "
          "{LAN|FC|CNA}<slot-No>-<Port-No>. This parameter is necessary for "
          "booting a node from a remote volume. Optional."),
    'irmc_storage_network_size':
        _("Size of the network for iSCSI storage network. This is the size of "
          "the IPv4 subnet mask that the storage network is configured to "
          "utilize, in a range between 1 and 31 inclusive. This is necessary "
          "for booting a node from a remote iSCSI volume. Optional."),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(driver_utils.OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def _is_image_href_ordinary_file_name(image_href):
    """Check if image_href is an ordinary file name.

    This method judges if image_href is an ordinary file name or not,
    which is a file supposed to be stored in share file system.
    The ordinary file name is neither glance image href
    nor image service href.

    :returns: True if image_href is ordinary file name, False otherwise.
    """
    return not (service_utils.is_glance_image(image_href)
                or urlparse.urlparse(image_href).scheme.lower() in
                image_service.protocol_mapping)


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
    if error_msgs:
        msg = (_("The following errors were encountered while parsing "
                 "config file:%s") % error_msgs)
        raise exception.InvalidParameterValue(msg)


def _parse_driver_info(node, mode='deploy'):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required or optional information properly
    for this driver to deploy images to the node.

    :param node: a target node of the deployment
    :param mode: Label indicating a deploy or rescue operation being
                 carried out on the node. Supported values are
                 'deploy' and 'rescue'. Defaults to 'deploy'.
    :returns: the driver_info values of the node.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    d_info = node.driver_info
    deploy_info = {}

    if mode == 'deploy':
        image_iso = d_info.get('irmc_deploy_iso')
        deploy_info['irmc_deploy_iso'] = image_iso
    else:
        image_iso = d_info.get('irmc_rescue_iso')
        deploy_info['irmc_rescue_iso'] = image_iso

    error_msg = (_("Error validating iRMC virtual media for %s. Some "
                   "parameters were missing in node's driver_info") % mode)
    deploy_utils.check_for_missing_params(deploy_info, error_msg)

    if _is_image_href_ordinary_file_name(image_iso):
        image_iso_file = os.path.join(CONF.irmc.remote_image_share_root,
                                      image_iso)
        if not os.path.isfile(image_iso_file):
            msg = (_("%(mode)s ISO file, %(iso_file)s, "
                     "not found for node: %(node)s.") %
                   {'mode': mode.capitalize(),
                    'iso_file': image_iso_file,
                    'node': node.uuid})
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

        if _is_image_href_ordinary_file_name(
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
    deploy_info.update(deploy_utils.get_image_instance_info(node))
    deploy_info.update(_parse_driver_info(node))
    deploy_info.update(_parse_instance_info(node))

    return deploy_info


def _setup_vmedia(task, mode, ramdisk_options):
    """Attaches virtual media and sets it as boot device.

    This method attaches the deploy or rescue ISO as virtual media, prepares
    the arguments for ramdisk in virtual media floppy.

    :param task: a TaskManager instance containing the node to act on.
    :param mode: Label indicating a deploy or rescue operation being
                 carried out on the node. Supported values are
                 'deploy' and 'rescue'.
    :param ramdisk_options: the options to be passed to the ramdisk in virtual
        media floppy.
    :raises: ImageRefValidationFailed if no image service can handle specified
       href.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: IRMCOperationError, if some operation on iRMC failed.
    :raises: InvalidParameterValue if the validation of the
        PowerInterface or ManagementInterface fails.
    """

    if mode == 'rescue':
        iso = task.node.driver_info['irmc_rescue_iso']
    else:
        iso = task.node.driver_info['irmc_deploy_iso']

    if _is_image_href_ordinary_file_name(iso):
        iso_file = iso
    else:
        iso_file = _get_iso_name(task.node, label=mode)
        iso_fullpathname = os.path.join(
            CONF.irmc.remote_image_share_root, iso_file)
        images.fetch(task.context, iso, iso_fullpathname)

    _setup_vmedia_for_boot(task, iso_file, ramdisk_options)
    manager_utils.node_set_boot_device(task, boot_devices.CDROM)


def _get_iso_name(node, label):
    """Returns the ISO file name for a given node.

    :param node: the node for which ISO file name is to be provided.
    :param label: a string used as a base name for the ISO file.
    """
    return "%s-%s.iso" % (label, node.uuid)


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
        if _is_image_href_ordinary_file_name(boot_iso_href):
            driver_internal_info['irmc_boot_iso'] = boot_iso_href
        else:
            boot_iso_filename = _get_iso_name(task.node, label='boot')
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
        kernel_href = (task.node.instance_info.get('kernel')
                       or image_properties['kernel_id'])
        ramdisk_href = (task.node.instance_info.get('ramdisk')
                        or image_properties['ramdisk_id'])

        deploy_iso_href = deploy_info['irmc_deploy_iso']
        boot_mode = boot_mode_utils.get_boot_mode(task.node)
        kernel_params = CONF.pxe.pxe_append_params

        boot_iso_filename = _get_iso_name(task.node, label='boot')
        boot_iso_fullpathname = os.path.join(
            CONF.irmc.remote_image_share_root, boot_iso_filename)

        images.create_boot_iso(task.context, boot_iso_fullpathname,
                               kernel_href, ramdisk_href,
                               deploy_iso_href=deploy_iso_href,
                               root_uuid=root_uuid,
                               kernel_params=kernel_params,
                               boot_mode=boot_mode)

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


def attach_boot_iso_if_needed(task):
    """Attaches boot ISO for a deployed node if it exists.

    This method checks the instance info of the bare metal node for a
    boot ISO. If the instance info has a value of key 'irmc_boot_iso',
    it indicates that 'boot_option' is 'netboot'. Threfore it attaches
    the boot ISO on the bare metal node and then sets the node to boot from
    virtual media cdrom.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IRMCOperationError if attaching virtual media failed.
    :raises: InvalidParameterValue if the validation of the
        ManagementInterface fails.
    """
    d_info = task.node.driver_internal_info
    node_state = task.node.provision_state

    if 'irmc_boot_iso' in d_info and node_state == states.ACTIVE:
        _setup_vmedia_for_boot(task, d_info['irmc_boot_iso'])
        manager_utils.node_set_boot_device(task, boot_devices.CDROM)


def _setup_vmedia_for_boot(task, bootable_iso_filename, parameters=None):
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
    LOG.info("Setting up node %s to boot from virtual media",
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
    It deletes floppy and cdrom images if they exist in NFS/CIFS server.
    It also ejects both the virtual media cdrom and the virtual media floppy.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IRMCOperationError if ejecting virtual media failed.
    """
    LOG.debug("Cleaning up node %s after virtual media boot", task.node.uuid)

    node = task.node
    _detach_virtual_cd(node)
    _detach_virtual_fd(node)

    _remove_share_file(_get_floppy_image_name(node))
    _remove_share_file(_get_iso_name(node, label='deploy'))
    _remove_share_file(_get_iso_name(node, label='rescue'))


def _remove_share_file(share_filename):
    """Remove given file from the share file system.

    :param share_filename: a file name to be removed.
    """
    share_fullpathname = os.path.join(
        CONF.irmc.remote_image_share_root, share_filename)
    ironic_utils.unlink_without_raise(share_fullpathname)


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

        irmc_client(cd_set_params, do_async=False)
        irmc_client(scci.MOUNT_CD, do_async=False)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception("Error while inserting virtual cdrom "
                      "into node %(uuid)s. Error: %(error)s",
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Inserting virtual cdrom")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info("Attached virtual cdrom successfully"
             " for node %s", node.uuid)


def _detach_virtual_cd(node):
    """Detaches virtual cdrom on the node.

    :param node: an ironic node object.
    :raises: IRMCOperationError if eject virtual cdrom failed.
    """
    try:
        irmc_client = irmc_common.get_irmc_client(node)

        irmc_client(scci.UNMOUNT_CD)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception("Error while ejecting virtual cdrom "
                      "from node %(uuid)s. Error: %(error)s",
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Ejecting virtual cdrom")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info("Detached virtual cdrom successfully"
             " for node %s", node.uuid)


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

        irmc_client(fd_set_params, do_async=False)
        irmc_client(scci.MOUNT_FD, do_async=False)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception("Error while inserting virtual floppy "
                      "into node %(uuid)s. Error: %(error)s",
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Inserting virtual floppy")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info("Attached virtual floppy successfully"
             " for node %s", node.uuid)


def _detach_virtual_fd(node):
    """Detaches virtual media floppy on the node.

    :param node: an ironic node object.
    :raises: IRMCOperationError if eject virtual media floppy failed.
    """
    try:
        irmc_client = irmc_common.get_irmc_client(node)

        irmc_client(scci.UNMOUNT_FD)

    except scci.SCCIClientError as irmc_exception:
        LOG.exception("Error while ejecting virtual floppy "
                      "from node %(uuid)s. Error: %(error)s",
                      {'uuid': node.uuid, 'error': irmc_exception})
        operation = _("Ejecting virtual floppy")
        raise exception.IRMCOperationError(operation=operation,
                                           error=irmc_exception)

    LOG.info("Detached virtual floppy successfully"
             " for node %s", node.uuid)


def check_share_fs_mounted():
    """Check if Share File System (NFS or CIFS) is mounted.

    :raises: InvalidParameterValue, if config option has invalid value.
    :raises: IRMCSharedFileSystemNotMounted, if shared file system is
        not mounted.
    """
    _parse_config_option()
    if not os.path.ismount(CONF.irmc.remote_image_share_root):
        raise exception.IRMCSharedFileSystemNotMounted(
            share=CONF.irmc.remote_image_share_root)


class IRMCVolumeBootMixIn(object):
    """Mix-in class for volume boot configuration to iRMC

    iRMC has a feature to set up remote boot to a server. This feature can be
    used by VIOM (Virtual I/O Manager) library of SCCI client.
    """

    def _validate_volume_boot(self, task):
        """Validate information for volume boot with this interface.

        This interface requires physical information of connectors to
        configure remote boot to iRMC. Physical information of LAN ports
        is also required since VIOM feature manages all adapters.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue: If invalid value is set to resources.
        :raises: MissingParameterValue: If some value is not set to resources.
        """

        if not deploy_utils.get_remote_boot_volume(task):
            # No boot volume. Nothing to validate.
            return

        irmc_common.parse_driver_info(task.node)

        for port in task.ports:
            self._validate_lan_port(task.node, port)

        for vt in task.volume_targets:
            if vt.volume_type == 'iscsi':
                self._validate_iscsi_connectors(task)
            elif vt.volume_type == 'fibre_channel':
                self._validate_fc_connectors(task)
            # Unknown volume type is filtered in storage interface validation.

    def _get_connector_physical_id(self, task, types):
        """Get physical ID of volume connector.

        A physical ID of volume connector required by iRMC is registered in
        "irmc_pci_physical_ids" of a Node's driver_info as a pair of resource
        UUID and its physical ID. This method gets this ID from the parameter.

        :param task: a TaskManager instance containing the node to act on.
        :param types: a list of types of volume connectors required for the
            target volume. One of connectors must have a physical ID.
        :raises InvalidParameterValue if a physical ID is invalid.
        :returns: A physical ID of a volume connector, or None if not set.
        """
        for vc in task.volume_connectors:
            if vc.type not in types:
                continue
            pid = task.node.driver_info['irmc_pci_physical_ids'].get(vc.uuid)
            if not pid:
                continue
            try:
                viom.validate_physical_port_id(pid)
            except scci.SCCIInvalidInputError as e:
                raise exception.InvalidParameterValue(
                    _('Physical port information of volume connector '
                      '%(connector)s is invalid: %(error)s') %
                    {'connector': vc.uuid, 'error': e})
            return pid
        return None

    def _validate_iscsi_connectors(self, task):
        """Validate if volume connectors are properly registered for iSCSI.

        For connecting a node to an iSCSI volume, volume connectors containing
        an IQN and an IP address are necessary. One of connectors must have
        a physical ID of the PCI card. Network size of a storage network is
        also required by iRMC. which should be registered in the node's
        driver_info.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if a volume connector with a required
            type is not registered.
        :raises: InvalidParameterValue if a physical ID is not registered in
            any volume connectors.
        :raises: InvalidParameterValue if a physical ID is invalid.
        """
        vc_dict = self._get_volume_connectors_by_type(task)
        node = task.node
        missing_types = []
        for vc_type in ('iqn', 'ip'):
            vc = vc_dict.get(vc_type)
            if not vc:
                missing_types.append(vc_type)

        if missing_types:
            raise exception.MissingParameterValue(
                _('Failed to validate for node %(node)s because of missing '
                  'volume connector(s) with type(s) %(types)s') %
                {'node': node.uuid,
                 'types': ', '.join(missing_types)})

        if not self._get_connector_physical_id(task, ['iqn', 'ip']):
            raise exception.MissingParameterValue(
                _('Failed to validate for node %(node)s because of missing '
                  'physical port information for iSCSI connector. This '
                  'information must be set in "pci_physical_ids" parameter of '
                  'node\'s driver_info as <connector uuid>:<physical id>.') %
                {'node': node.uuid})
        self._get_network_size(node)

    def _validate_fc_connectors(self, task):
        """Validate if volume connectors are properly registered for FC.

        For connecting a node to a FC volume, one of connectors representing
        wwnn and wwpn must have a physical ID of the PCI card.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if a physical ID is not registered in
            any volume connectors.
        :raises: InvalidParameterValue if a physical ID is invalid.
        """
        node = task.node
        if not self._get_connector_physical_id(task, ['wwnn', 'wwpn']):
            raise exception.MissingParameterValue(
                _('Failed to validate for node %(node)s because of missing '
                  'physical port information for FC connector. This '
                  'information must be set in "pci_physical_ids" parameter of '
                  'node\'s driver_info as <connector uuid>:<physical id>.') %
                {'node': node.uuid})

    def _validate_lan_port(self, node, port):
        """Validate ports for VIOM configuration.

        Physical information of LAN ports must be registered to VIOM
        configuration to activate them under VIOM management. The information
        has to be set to "irmc_pci_physical_id" parameter in a nodes
        driver_info.

        :param node: an ironic node object
        :param port: a port to be validated
        :raises: MissingParameterValue if a physical ID of the port is not set.
        :raises: InvalidParameterValue if a physical ID is invalid.
        """
        physical_id = node.driver_info['irmc_pci_physical_ids'].get(port.uuid)
        if not physical_id:
            raise exception.MissingParameterValue(
                _('Failed to validate for node %(node)s because of '
                  'missing physical port information of port %(port)s. '
                  'This information should be contained in '
                  '"pci_physical_ids" parameter of node\'s driver_info.') %
                {'node': node.uuid,
                 'port': port.uuid})
        try:
            viom.validate_physical_port_id(physical_id)
        except scci.SCCIInvalidInputError as e:
            raise exception.InvalidParameterValue(
                _('Failed to validate for node %(node)s because '
                  'the physical port ID for port %(port)s in node\'s'
                  ' driver_info is invalid: %(reason)s') %
                {'node': node.uuid,
                 'port': port.uuid,
                 'reason': e})

    def _get_network_size(self, node):
        """Get network size of a storage network.

        The network size of iSCSI network is required by iRMC for connecting
        a node to an iSCSI volume. This network size is set to node's
        driver_info as "irmc_storage_network_size" parameter in the form of
        positive integer.

        :param node: an ironic node object.
        :raises: MissingParameterValue if the network size parameter is not
            set.
        :raises: InvalidParameterValue the network size is invalid.
        """
        network_size = node.driver_info.get('irmc_storage_network_size')
        if network_size is None:
            raise exception.MissingParameterValue(
                _('Failed to validate for node %(node)s because of '
                  'missing "irmc_storage_network_size" parameter in the '
                  'node\'s driver_info. This should be a positive integer '
                  'smaller than 32.') %
                {'node': node.uuid})
        try:
            network_size = int(network_size)
        except (ValueError, TypeError):
            raise exception.InvalidParameterValue(
                _('Failed to validate for node %(node)s because '
                  '"irmc_storage_network_size" parameter in the node\'s '
                  'driver_info is invalid. This should be a '
                  'positive integer smaller than 32.') %
                {'node': node.uuid})

        if network_size not in range(1, 32):
            raise exception.InvalidParameterValue(
                _('Failed to validate for node %(node)s because '
                  '"irmc_storage_network_size" parameter in the node\'s '
                  'driver_info is invalid. This should be a '
                  'positive integer smaller than 32.') %
                {'node': node.uuid})

        return network_size

    def _get_volume_connectors_by_type(self, task):
        """Create a dictionary of volume connectors by types.

        :param task: a TaskManager.
        :returns: a volume connector dictionary whose key is a connector type.
        """
        connectors = {}
        for vc in task.volume_connectors:
            if vc.type in ('ip', 'iqn', 'wwnn', 'wwpn'):
                connectors[vc.type] = vc
            else:
                LOG.warning('Node %(node)s has a volume_connector (%(uuid)s) '
                            'defined with an unsupported type: %(type)s.',
                            {'node': task.node.uuid,
                             'uuid': vc.uuid,
                             'type': vc.type})
        return connectors

    def _register_lan_ports(self, viom_conf, task):
        """Register ports to VIOM configuration.

        LAN ports information must be registered for VIOM configuration to
        activate them under VIOM management.

        :param viom_conf: a configurator for iRMC
        :param task: a TaskManager instance containing the node to act on.
        """
        for port in task.ports:
            viom_conf.set_lan_port(
                task.node.driver_info['irmc_pci_physical_ids'].get(port.uuid))

    def _configure_boot_from_volume(self, task):
        """Set information for booting from a remote volume to iRMC.

        :param task: a TaskManager instance containing the node to act on.
        :raises: IRMCOperationError if iRMC operation failed
        """

        irmc_info = irmc_common.parse_driver_info(task.node)
        viom_conf = viom.VIOMConfiguration(irmc_info,
                                           identification=task.node.uuid)

        self._register_lan_ports(viom_conf, task)

        for vt in task.volume_targets:
            if vt.volume_type == 'iscsi':
                self._set_iscsi_target(task, viom_conf, vt)
            elif vt.volume_type == 'fibre_channel':
                self._set_fc_target(task, viom_conf, vt)

        try:
            LOG.debug('Set VIOM configuration for node %(node)s: %(table)s',
                      {'node': task.node.uuid,
                       'table': viom_conf.dump_json()})
            viom_conf.apply()
        except scci.SCCIError as e:
            LOG.error('iRMC failed to set VIOM configuration for node '
                      '%(node)s: %(error)s',
                      {'node': task.node.uuid,
                       'error': e})
            raise exception.IRMCOperationError(
                operation='Configure VIOM', error=e)

    def _set_iscsi_target(self, task, viom_conf, target):
        """Set information for iSCSI boot to VIOM configuration."""
        connectors = self._get_volume_connectors_by_type(task)
        target_portal = target.properties['target_portal']
        if ':' in target_portal:
            target_host, target_port = target_portal.split(':')
        else:
            target_host = target_portal
            target_port = None
        if target.properties.get('auth_method') == 'CHAP':
            chap_user = target.properties.get('auth_username')
            chap_secret = target.properties.get('auth_password')
        else:
            chap_user = None
            chap_secret = None

        viom_conf.set_iscsi_volume(
            self._get_connector_physical_id(task, ['iqn', 'ip']),
            connectors['iqn'].connector_id,
            initiator_ip=connectors['ip'].connector_id,
            initiator_netmask=self._get_network_size(task.node),
            target_iqn=target.properties['target_iqn'],
            target_ip=target_host,
            target_port=target_port,
            target_lun=target.properties.get('target_lun'),
            # Boot priority starts from 1 in the library.
            boot_prio=target.boot_index + 1,
            chap_user=chap_user,
            chap_secret=chap_secret)

    def _set_fc_target(self, task, viom_conf, target):
        """Set information for FC boot to VIOM configuration."""
        wwn = target.properties['target_wwn']
        if isinstance(wwn, list):
            wwn = wwn[0]
        viom_conf.set_fc_volume(
            self._get_connector_physical_id(task, ['wwnn', 'wwpn']),
            wwn,
            target.properties['target_lun'],
            # Boot priority starts from 1 in the library.
            boot_prio=target.boot_index + 1)

    def _cleanup_boot_from_volume(self, task, reboot=False):
        """Clear remote boot configuration.

        :param task: a task from TaskManager.
        :param reboot: True if reboot node soon
        :raises: IRMCOperationError if iRMC operation failed
        """
        irmc_info = irmc_common.parse_driver_info(task.node)
        try:
            viom_conf = viom.VIOMConfiguration(irmc_info, task.node.uuid)
            viom_conf.terminate(reboot=reboot)
        except scci.SCCIError as e:
            LOG.error('iRMC failed to terminate VIOM configuration from '
                      'node %(node)s: %(error)s', {'node': task.node.uuid,
                                                   'error': e})
            raise exception.IRMCOperationError(operation='Terminate VIOM',
                                               error=e)


class IRMCVirtualMediaBoot(base.BootInterface, IRMCVolumeBootMixIn):
    """iRMC Virtual Media boot-related actions."""

    capabilities = ['iscsi_volume_boot', 'fibre_channel_volume_boot']

    def __init__(self):
        """Constructor of IRMCVirtualMediaBoot.

        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if config option has invalid value.
        """
        check_share_fs_mounted()
        super(IRMCVirtualMediaBoot, self).__init__()

    def get_properties(self):
        # TODO(tiendc): COMMON_PROPERTIES should also include rescue
        # related properties (RESCUE_PROPERTIES). We can add them in Rocky,
        # when classic drivers get removed.
        return COMMON_PROPERTIES

    @METRICS.timer('IRMCVirtualMediaBoot.validate')
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
        check_share_fs_mounted()

        self._validate_volume_boot(task)
        if not task.driver.storage.should_write_image(task):
            LOG.debug('Node %(node)s skips image validation because of '
                      'booting from a remote volume.',
                      {'node': task.node.uuid})
            return

        d_info = _parse_deploy_info(task.node)
        if task.node.driver_internal_info.get('is_whole_disk_image'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        deploy_utils.validate_image_properties(task.context, d_info,
                                               props)

    @METRICS.timer('IRMCVirtualMediaBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the deploy or rescue ramdisk using virtual media.

        Prepares the options for the deploy or rescue ramdisk, sets the node
        to boot from virtual media cdrom.

        :param task: a TaskManager instance containing the node to act on.
        :param ramdisk_params: the options to be passed to the ramdisk.
        :raises: ImageRefValidationFailed if no image service can handle
                 specified href.
        :raises: ImageCreationFailed, if it failed while creating the floppy
                 image.
        :raises: InvalidParameterValue if the validation of the
                 PowerInterface or ManagementInterface fails.
        :raises: IRMCOperationError, if some operation on iRMC fails.
        """

        # NOTE(TheJulia): If this method is being called by something
        # aside from deployment, clean and rescue, such as conductor takeover,
        # we should treat this as a no-op and move on otherwise we would
        # modify the state of the node due to virtual media operations.
        if task.node.provision_state not in (states.DEPLOYING,
                                             states.CLEANING,
                                             states.RESCUING):
            return

        # NOTE(tiendc): Before deploying, we need to backup BIOS config
        # as the data will be used later when cleaning.
        if task.node.provision_state == states.DEPLOYING:
            irmc_management.backup_bios_config(task)

            if not task.driver.storage.should_write_image(task):
                LOG.debug('Node %(node)s skips ramdisk preparation because of '
                          'booting from a remote volume.',
                          {'node': task.node.uuid})
                return

        # NOTE(TheJulia): Since we're deploying, cleaning, or rescuing,
        # with virtual media boot, we should generate a token!
        manager_utils.add_secret_token(task.node, pregenerated=True)
        ramdisk_params['ipa-agent-token'] = \
            task.node.driver_internal_info['agent_secret_token']
        task.node.save()

        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        if deploy_nic_mac is not None:
            ramdisk_params['BOOTIF'] = deploy_nic_mac

        if task.node.provision_state == states.RESCUING:
            mode = 'rescue'
        else:
            mode = 'deploy'

        _setup_vmedia(task, mode, ramdisk_params)

    @METRICS.timer('IRMCVirtualMediaBoot.clean_up_ramdisk')
    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up the environment that was setup for booting the
        deploy or rescue ramdisk.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IRMCOperationError if iRMC operation failed.
        """
        _cleanup_vmedia_boot(task)

    @METRICS.timer('IRMCVirtualMediaBoot.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's database.

        :param task: a task from TaskManager.
        :returns: None
        """
        if task.node.driver_internal_info.get('boot_from_volume'):
            LOG.debug('Node %(node)s is configured for booting from a remote '
                      'volume.',
                      {'node': task.node.uuid})
            self._configure_boot_from_volume(task)
            return

        _cleanup_vmedia_boot(task)

        node = task.node
        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        if deploy_utils.get_boot_option(node) == "local" or iwdi:
            manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                               persistent=True)
        else:
            driver_internal_info = node.driver_internal_info
            root_uuid_or_disk_id = driver_internal_info['root_uuid_or_disk_id']
            self._configure_vmedia_boot(task, root_uuid_or_disk_id)

        # Enable secure boot, if being requested
        boot_mode_utils.configure_secure_boot_if_needed(task)

    @METRICS.timer('IRMCVirtualMediaBoot.clean_up_instance')
    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the environment that was setup for booting
        the instance.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IRMCOperationError if iRMC operation failed.
        """
        if task.node.driver_internal_info.get('boot_from_volume'):
            self._cleanup_boot_from_volume(task)
            return

        # Disable secure boot, if enabled secure boot
        boot_mode_utils.deconfigure_secure_boot_if_needed(task)

        _remove_share_file(_get_iso_name(task.node, label='boot'))
        driver_internal_info = task.node.driver_internal_info
        driver_internal_info.pop('irmc_boot_iso', None)

        task.node.driver_internal_info = driver_internal_info
        task.node.save()
        _cleanup_vmedia_boot(task)

    def _configure_vmedia_boot(self, task, root_uuid_or_disk_id):
        """Configure vmedia boot for the node."""
        node = task.node
        _prepare_boot_iso(task, root_uuid_or_disk_id)
        _setup_vmedia_for_boot(
            task, node.driver_internal_info['irmc_boot_iso'])
        manager_utils.node_set_boot_device(task, boot_devices.CDROM,
                                           persistent=True)

    @METRICS.timer('IRMCVirtualMediaBoot.validate_rescue')
    def validate_rescue(self, task):
        """Validate that the node has required properties for rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        _parse_driver_info(task.node, mode='rescue')


class IRMCPXEBoot(pxe.PXEBoot):
    """iRMC PXE boot."""

    @METRICS.timer('IRMCPXEBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of Ironic ramdisk using PXE.

        This method prepares the boot of the deploy kernel/ramdisk after
        reading relevant information from the node's driver_info and
        instance_info.

        :param task: a task from TaskManager.
        :param ramdisk_params: the parameters to be passed to the ramdisk.
            pxe driver passes these parameters as kernel command-line
            arguments.
        :returns: None
        :raises: MissingParameterValue, if some information is missing in
            node's driver_info or instance_info.
        :raises: InvalidParameterValue, if some information provided is
            invalid.
        :raises: IronicException, if some power or set boot device
            operation failed on the node.
        """
        # NOTE(tiendc): Before deploying, we need to backup BIOS config
        # as the data will be used later when cleaning.
        if task.node.provision_state == states.DEPLOYING:
            irmc_management.backup_bios_config(task)

        super(IRMCPXEBoot, self).prepare_ramdisk(task, ramdisk_params)
