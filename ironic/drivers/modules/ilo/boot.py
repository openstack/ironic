# Copyright 2015 Hewlett-Packard Development Company, L.P.
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
Boot Interface for iLO drivers and its supporting methods.
"""

import os
import tempfile

from ironic_lib import metrics_utils
from ironic_lib import utils as ironic_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import six.moves.urllib.parse as urlparse

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import images
from ironic.common import states
from ironic.common import swift
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import pxe

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

CONF = cfg.CONF

REQUIRED_PROPERTIES = {
    'ilo_deploy_iso': _("UUID (from Glance) of the deployment ISO. "
                        "Required.")
}
RESCUE_PROPERTIES = {
    'ilo_rescue_iso': _("UUID (from Glance) of the rescue ISO. Only "
                        "required if rescue mode is being used and ironic is "
                        "managing booting the rescue ramdisk.")
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES


def parse_driver_info(node, mode='deploy'):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node.
    :param mode: Label indicating a deploy or rescue operation being
                 carried out on the node. Supported values are
                 'deploy' and 'rescue'. Defaults to 'deploy', indicating
                 deploy operation is being carried out.
    :returns: A dict with the driver_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    """
    info = node.driver_info
    d_info = {}
    if mode == 'rescue':
        d_info['ilo_rescue_iso'] = info.get('ilo_rescue_iso')
    else:
        d_info['ilo_deploy_iso'] = info.get('ilo_deploy_iso')

    error_msg = (_("Error validating iLO virtual media for %s. Some "
                   "parameters were missing in node's driver_info") % mode)
    deploy_utils.check_for_missing_params(d_info, error_msg)

    return d_info


def _get_boot_iso_object_name(node):
    """Returns the boot iso object name for a given node.

    :param node: the node for which object name is to be provided.
    """
    return "boot-%s" % node.uuid


def _get_boot_iso(task, root_uuid):
    """This method returns a boot ISO to boot the node.

    It chooses one of the three options in the order as below:
    1. Does nothing if 'ilo_boot_iso' is present in node's instance_info and
       'boot_iso_created_in_web_server' is not set in 'driver_internal_info'.
    2. Image deployed has a meta-property 'boot_iso' in Glance. This should
       refer to the UUID of the boot_iso which exists in Glance.
    3. Generates a boot ISO on the fly using kernel and ramdisk mentioned in
       the image deployed. It uploads the generated boot ISO to Swift.

    :param task: a TaskManager instance containing the node to act on.
    :param root_uuid: the uuid of the root partition.
    :returns: boot ISO URL. Should be either of below:
        * A Swift object - It should be of format 'swift:<object-name>'. It is
          assumed that the image object is present in
          CONF.ilo.swift_ilo_container;
        * A Glance image - It should be format 'glance://<glance-image-uuid>'
          or just <glance-image-uuid>;
        * An HTTP URL.
        On error finding the boot iso, it returns None.
    :raises: MissingParameterValue, if any of the required parameters are
        missing in the node's driver_info or instance_info.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value in the node's driver_info or instance_info.
    :raises: SwiftOperationError, if operation with Swift fails.
    :raises: ImageCreationFailed, if creation of boot ISO failed.
    :raises: exception.ImageRefValidationFailed if ilo_boot_iso is not
        HTTP(S) URL.
    """
    LOG.debug("Trying to get a boot ISO to boot the baremetal node")

    # Option 1 - Check if user has provided ilo_boot_iso in node's
    # instance_info
    driver_internal_info = task.node.driver_internal_info
    boot_iso_created_in_web_server = (
        driver_internal_info.get('boot_iso_created_in_web_server'))

    if (task.node.instance_info.get('ilo_boot_iso')
            and not boot_iso_created_in_web_server):
        LOG.debug("Using ilo_boot_iso provided in node's instance_info")
        boot_iso = task.node.instance_info['ilo_boot_iso']
        if not service_utils.is_glance_image(boot_iso):
            try:
                image_service.HttpImageService().validate_href(boot_iso)
            except exception.ImageRefValidationFailed:
                with excutils.save_and_reraise_exception():
                    LOG.error("Virtual media deploy accepts only Glance "
                              "images or HTTP(S) URLs as "
                              "instance_info['ilo_boot_iso']. Either %s "
                              "is not a valid HTTP(S) URL or is "
                              "not reachable.", boot_iso)

        return task.node.instance_info['ilo_boot_iso']

    # Option 2 - Check if user has provided a boot_iso in Glance. If boot_iso
    # is a supported non-glance href execution will proceed to option 3.
    deploy_info = _parse_deploy_info(task.node)

    image_href = deploy_info['image_source']
    image_properties = (
        images.get_image_properties(
            task.context, image_href, ['boot_iso', 'kernel_id', 'ramdisk_id']))

    boot_iso_uuid = image_properties.get('boot_iso')
    kernel_href = (task.node.instance_info.get('kernel')
                   or image_properties.get('kernel_id'))
    ramdisk_href = (task.node.instance_info.get('ramdisk')
                    or image_properties.get('ramdisk_id'))

    if boot_iso_uuid:
        LOG.debug("Found boot_iso %s in Glance", boot_iso_uuid)
        return boot_iso_uuid

    if not kernel_href or not ramdisk_href:
        LOG.error("Unable to find kernel or ramdisk for "
                  "image %(image)s to generate boot ISO for %(node)s",
                  {'image': image_href, 'node': task.node.uuid})
        return

    # NOTE(rameshg87): Functionality to share the boot ISOs created for
    # similar instances (instances with same deployed image) is
    # not implemented as of now. Creation/Deletion of such a shared boot ISO
    # will require synchronisation across conductor nodes for the shared boot
    # ISO.  Such a synchronisation mechanism doesn't exist in ironic as of now.

    # Option 3 - Create boot_iso from kernel/ramdisk, upload to Swift
    # or web server and provide its name.
    deploy_iso_uuid = deploy_info['ilo_deploy_iso']
    boot_mode = boot_mode_utils.get_boot_mode(task.node)
    boot_iso_object_name = _get_boot_iso_object_name(task.node)
    kernel_params = ""
    if deploy_utils.get_boot_option(task.node) == "ramdisk":
        i_info = task.node.instance_info
        kernel_params = "root=/dev/ram0 text "
        kernel_params += i_info.get("ramdisk_kernel_arguments", "")
    else:
        kernel_params = CONF.pxe.pxe_append_params
    with tempfile.NamedTemporaryFile(dir=CONF.tempdir) as fileobj:
        boot_iso_tmp_file = fileobj.name
        images.create_boot_iso(task.context, boot_iso_tmp_file,
                               kernel_href, ramdisk_href,
                               deploy_iso_href=deploy_iso_uuid,
                               root_uuid=root_uuid,
                               kernel_params=kernel_params,
                               boot_mode=boot_mode)

        if CONF.ilo.use_web_server_for_images:
            boot_iso_url = (
                ilo_common.copy_image_to_web_server(boot_iso_tmp_file,
                                                    boot_iso_object_name))
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_iso_created_in_web_server'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            LOG.debug("Created boot_iso %(boot_iso)s for node %(node)s",
                      {'boot_iso': boot_iso_url, 'node': task.node.uuid})
            return boot_iso_url
        else:
            container = CONF.ilo.swift_ilo_container
            swift_api = swift.SwiftAPI()
            swift_api.create_object(container, boot_iso_object_name,
                                    boot_iso_tmp_file)

            LOG.debug("Created boot_iso %s in Swift", boot_iso_object_name)
            return 'swift:%s' % boot_iso_object_name


def _clean_up_boot_iso_for_instance(node):
    """Deletes the boot ISO if it was created for the instance.

    :param node: an ironic node object.
    """
    ilo_boot_iso = node.instance_info.get('ilo_boot_iso')
    if not ilo_boot_iso:
        return
    if ilo_boot_iso.startswith('swift'):
        swift_api = swift.SwiftAPI()
        container = CONF.ilo.swift_ilo_container
        boot_iso_object_name = _get_boot_iso_object_name(node)
        try:
            swift_api.delete_object(container, boot_iso_object_name)
        except exception.SwiftOperationError as e:
            LOG.exception("Failed to clean up boot ISO for node "
                          "%(node)s. Error: %(error)s.",
                          {'node': node.uuid, 'error': e})
    elif CONF.ilo.use_web_server_for_images:
        result = urlparse.urlparse(ilo_boot_iso)
        ilo_boot_iso_name = os.path.basename(result.path)
        boot_iso_path = os.path.join(
            CONF.deploy.http_root, ilo_boot_iso_name)
        ironic_utils.unlink_without_raise(boot_iso_path)


def _parse_deploy_info(node):
    """Gets the instance and driver specific Node deployment info.

    This method validates whether the 'instance_info' and 'driver_info'
    property of the supplied node contains the required information for
    this driver to deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the instance_info and driver_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    info = {}
    info.update(deploy_utils.get_image_instance_info(node))
    info.update(parse_driver_info(node))
    return info


def _validate_driver_info(task):
    """Validate the prerequisites for virtual media based boot.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InvalidParameterValue if any parameters are incorrect
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    node = task.node
    ilo_common.parse_driver_info(node)
    if 'ilo_deploy_iso' not in node.driver_info:
        raise exception.MissingParameterValue(_(
            "Missing 'ilo_deploy_iso' parameter in node's 'driver_info'."))
    deploy_iso = node.driver_info['ilo_deploy_iso']
    if not service_utils.is_glance_image(deploy_iso):
        try:
            image_service.HttpImageService().validate_href(deploy_iso)
        except exception.ImageRefValidationFailed:
            raise exception.InvalidParameterValue(_(
                "Virtual media boot accepts only Glance images or "
                "HTTP(S) as driver_info['ilo_deploy_iso']. Either '%s' "
                "is not a glance UUID or not a valid HTTP(S) URL or "
                "the given URL is not reachable.") % deploy_iso)


def _validate_instance_image_info(task):
    """Validate instance image information for the task's node.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InvalidParameterValue, if some information is invalid.
    :raises: MissingParameterValue if 'kernel_id' and 'ramdisk_id' are
        missing in the Glance image or 'kernel' and 'ramdisk' not provided
        in instance_info for non-Glance image.
    """

    node = task.node

    d_info = _parse_deploy_info(node)

    if node.driver_internal_info.get('is_whole_disk_image'):
        props = []
    elif service_utils.is_glance_image(d_info['image_source']):
        props = ['kernel_id', 'ramdisk_id']
    else:
        props = ['kernel', 'ramdisk']
    deploy_utils.validate_image_properties(task.context, d_info, props)


def _disable_secure_boot(task):
    """Disables secure boot on node, if secure boot is enabled on node.

    This method checks if secure boot is enabled on node. If enabled, it
    disables same and returns True.

    :param task: a TaskManager instance containing the node to act on.
    :returns: It returns True, if secure boot was successfully disabled on
              the node.
              It returns False, if secure boot on node is in disabled state
              or if secure boot feature is not supported by the node.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    cur_sec_state = False
    try:
        cur_sec_state = ilo_common.get_secure_boot_mode(task)
    except exception.IloOperationNotSupported:
        LOG.debug('Secure boot mode is not supported for node %s',
                  task.node.uuid)
        return False

    if cur_sec_state:
        LOG.debug('Disabling secure boot for node %s', task.node.uuid)
        ilo_common.set_secure_boot_mode(task, False)
        return True
    return False


def prepare_node_for_deploy(task):
    """Common preparatory steps for all iLO drivers.

    This method performs common preparatory steps required for all drivers.
    1. Power off node
    2. Disables secure boot, if it is in enabled state.
    3. Updates boot_mode capability to 'uefi' if secure boot is requested.
    4. Changes boot mode of the node if secure boot is disabled currently.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    manager_utils.node_power_action(task, states.POWER_OFF)

    # Boot mode can be changed only if secure boot is in disabled state.
    # secure boot and boot mode cannot be changed together.
    change_boot_mode = True

    # Disable secure boot on the node if it is in enabled state.
    if _disable_secure_boot(task):
        change_boot_mode = False

    if change_boot_mode:
        ilo_common.update_boot_mode(task)
    else:
        # Need to update boot mode that will be used during deploy, if one is
        # not provided.
        # Since secure boot was disabled, we are in 'uefi' boot mode.
        if boot_mode_utils.get_boot_mode_for_deploy(task.node) is None:
            instance_info = task.node.instance_info
            instance_info['deploy_boot_mode'] = 'uefi'
            task.node.instance_info = instance_info
            task.node.save()


def disable_secure_boot_if_supported(task):
    """Disables secure boot on node, does not throw if its not supported.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    try:
        ilo_common.update_secure_boot_mode(task, False)
    # We need to handle IloOperationNotSupported exception so that if
    # the user has incorrectly specified the Node capability
    # 'secure_boot' to a node that does not have that capability and
    # attempted deploy. Handling this exception here, will help the
    # user to tear down such a Node.
    except exception.IloOperationNotSupported:
        LOG.warning('Secure boot mode is not supported for node %s',
                    task.node.uuid)


class IloVirtualMediaBoot(base.BootInterface):

    capabilities = ['iscsi_volume_boot', 'ramdisk_boot']

    def get_properties(self):
        # TODO(stendulker): COMMON_PROPERTIES should also include rescue
        # related properties (RESCUE_PROPERTIES). We can add them in Rocky,
        # when classic drivers get removed.
        return COMMON_PROPERTIES

    @METRICS.timer('IloVirtualMediaBoot.validate')
    def validate(self, task):
        """Validate the deployment information for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue, if some information is invalid.
        :raises: MissingParameterValue if 'kernel_id' and 'ramdisk_id' are
            missing in the Glance image or 'kernel' and 'ramdisk' not provided
            in instance_info for non-Glance image.
        """
        node = task.node
        boot_option = deploy_utils.get_boot_option(node)
        boot_iso = node.instance_info.get('ilo_boot_iso')
        if (boot_option == "ramdisk" and boot_iso):
            if not service_utils.is_glance_image(boot_iso):
                try:
                    image_service.HttpImageService().validate_href(boot_iso)
                except exception.ImageRefValidationFailed:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Virtual media deploy with 'ramdisk' "
                                  "boot_option accepts only Glance images or "
                                  "HTTP(S) URLs as "
                                  "instance_info['ilo_boot_iso']. Either %s "
                                  "is not a valid HTTP(S) URL or is not "
                                  "reachable.", boot_iso)
            return

        _validate_driver_info(task)

        if not task.driver.storage.should_write_image(task):
            return
        else:
            _validate_instance_image_info(task)

    @METRICS.timer('IloVirtualMediaBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of deploy ramdisk using virtual media.

        This method prepares the boot of the deploy or rescue ramdisk after
        reading relevant information from the node's driver_info and
        instance_info.

        :param task: a task from TaskManager.
        :param ramdisk_params: the parameters to be passed to the ramdisk.
        :returns: None
        :raises: MissingParameterValue, if some information is missing in
            node's driver_info or instance_info.
        :raises: InvalidParameterValue, if some information provided is
            invalid.
        :raises: IronicException, if some power or set boot boot device
            operation failed on the node.
        :raises: IloOperationError, if some operation on iLO failed.
        """

        node = task.node
        # NOTE(TheJulia): If this method is being called by something
        # aside from deployment, clean and rescue, such as conductor takeover,
        # we should treat this as a no-op and move on otherwise we would
        # modify the state of the node due to virtual media operations.
        if node.provision_state not in (states.DEPLOYING,
                                        states.CLEANING,
                                        states.RESCUING):
            return

        prepare_node_for_deploy(task)

        # Clear ilo_boot_iso if it's a glance image to force recreate
        # another one again (or use existing one in glance).
        # This is mainly for rebuild and rescue scenario.
        if service_utils.is_glance_image(
                node.instance_info.get('image_source')):
            instance_info = node.instance_info
            instance_info.pop('ilo_boot_iso', None)
            node.instance_info = instance_info
            node.save()

        # Eject all virtual media devices, as we are going to use them
        # during boot.
        ilo_common.eject_vmedia_devices(task)

        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        ramdisk_params['BOOTIF'] = deploy_nic_mac
        if node.provision_state == states.RESCUING:
            iso = node.driver_info['ilo_rescue_iso']
        else:
            iso = node.driver_info['ilo_deploy_iso']

        ilo_common.setup_vmedia(task, iso, ramdisk_params)

    @METRICS.timer('IloVirtualMediaBoot.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info.
        It does the following depending on boot_option for deploy:

        - If the boot mode is 'uefi' and its booting from volume, then it
          sets the iSCSI target info and node to boot from 'UefiTarget'
          boot device.
        - If not 'boot from volume' and the boot_option requested for
          this deploy is 'local' or image is a whole disk image, then
          it sets the node to boot from disk.
        - Otherwise it finds/creates the boot ISO to boot the instance
          image, attaches the boot ISO to the bare metal and then sets
          the node to boot from CDROM.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        :raises: InstanceDeployFailure, if its try to boot iSCSI volume in
                 'BIOS' boot mode.
        """
        ilo_common.cleanup_vmedia_boot(task)

        boot_mode = boot_mode_utils.get_boot_mode(task.node)
        boot_option = deploy_utils.get_boot_option(task.node)

        if deploy_utils.is_iscsi_boot(task):
            # It will set iSCSI info onto iLO
            if boot_mode == 'uefi':
                # Need to set 'ilo_uefi_iscsi_boot' param for clean up
                driver_internal_info = task.node.driver_internal_info
                driver_internal_info['ilo_uefi_iscsi_boot'] = True
                task.node.driver_internal_info = driver_internal_info
                task.node.save()
                task.driver.management.set_iscsi_boot_target(task)
                manager_utils.node_set_boot_device(
                    task, boot_devices.ISCSIBOOT, persistent=True)
            else:
                msg = 'Virtual media can not boot volume in BIOS boot mode.'
                raise exception.InstanceDeployFailure(msg)
        elif boot_option == "ramdisk":
            boot_iso = _get_boot_iso(task, None)
            ilo_common.setup_vmedia_for_boot(task, boot_iso)
            manager_utils.node_set_boot_device(task,
                                               boot_devices.CDROM,
                                               persistent=True)
        else:
            # Boot from disk every time if the image deployed is
            # a whole disk image.
            node = task.node
            iwdi = node.driver_internal_info.get('is_whole_disk_image')
            if deploy_utils.get_boot_option(node) == "local" or iwdi:
                manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                                   persistent=True)
            else:
                drv_int_info = node.driver_internal_info
                root_uuid_or_disk_id = drv_int_info.get('root_uuid_or_disk_id')
                if root_uuid_or_disk_id:
                    self._configure_vmedia_boot(task, root_uuid_or_disk_id)
                else:
                    LOG.warning("The UUID for the root partition could not "
                                "be found for node %s", node.uuid)
        # Set boot mode
        ilo_common.update_boot_mode(task)
        # Need to enable secure boot, if being requested
        ilo_common.update_secure_boot_mode(task, True)

    @METRICS.timer('IloVirtualMediaBoot.clean_up_instance')
    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the environment that was setup for booting
        the instance. It ejects virtual media.
        In case of UEFI iSCSI booting, it cleans up iSCSI target information
        from the node.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """
        LOG.debug("Cleaning up the instance.")
        manager_utils.node_power_action(task, states.POWER_OFF)
        disable_secure_boot_if_supported(task)
        driver_internal_info = task.node.driver_internal_info

        if (deploy_utils.is_iscsi_boot(task)
            and task.node.driver_internal_info.get('ilo_uefi_iscsi_boot')):
            # It will clear iSCSI info from iLO
            task.driver.management.clear_iscsi_boot_target(task)
            driver_internal_info.pop('ilo_uefi_iscsi_boot', None)
        else:
            _clean_up_boot_iso_for_instance(task.node)
            driver_internal_info.pop('boot_iso_created_in_web_server', None)
            ilo_common.cleanup_vmedia_boot(task)
        task.node.driver_internal_info = driver_internal_info
        task.node.save()

    @METRICS.timer('IloVirtualMediaBoot.clean_up_ramdisk')
    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up virtual media devices setup for the deploy
        or rescue ramdisk.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """
        ilo_common.cleanup_vmedia_boot(task)

    def _configure_vmedia_boot(self, task, root_uuid):
        """Configure vmedia boot for the node.

        :param task: a task from TaskManager.
        :param root_uuid: uuid of the root partition
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """

        node = task.node
        boot_iso = _get_boot_iso(task, root_uuid)
        if not boot_iso:
            LOG.error("Cannot get boot ISO for node %s", node.uuid)
            return

        # Upon deploy complete, some distros cloud images reboot the system as
        # part of its configuration. Hence boot device should be persistent and
        # not one-time.
        ilo_common.setup_vmedia_for_boot(task, boot_iso)
        manager_utils.node_set_boot_device(task,
                                           boot_devices.CDROM,
                                           persistent=True)

        i_info = node.instance_info
        i_info['ilo_boot_iso'] = boot_iso
        node.instance_info = i_info
        node.save()

    @METRICS.timer('IloVirtualMediaBoot.validate_rescue')
    def validate_rescue(self, task):
        """Validate that the node has required properties for rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        """
        parse_driver_info(task.node, mode='rescue')


class IloPXEBoot(pxe.PXEBoot):

    @METRICS.timer('IloPXEBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of Ironic ramdisk using PXE.

        This method prepares the boot of the deploy or rescue ramdisk after
        reading relevant information from the node's driver_info and
        instance_info.

        :param task: a task from TaskManager.
        :param ramdisk_params: the parameters to be passed to the ramdisk.
        :returns: None
        :raises: MissingParameterValue, if some information is missing in
            node's driver_info or instance_info.
        :raises: InvalidParameterValue, if some information provided is
            invalid.
        :raises: IronicException, if some power or set boot boot device
            operation failed on the node.
        :raises: IloOperationError, if some operation on iLO failed.
        """

        if task.node.provision_state in (states.DEPLOYING, states.RESCUING,
                                         states.CLEANING):
            prepare_node_for_deploy(task)

        super(IloPXEBoot, self).prepare_ramdisk(task, ramdisk_params)

    @METRICS.timer('IloPXEBoot.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info. In case of netboot,
        it updates the dhcp entries and switches the PXE config. In case of
        localboot, it cleans up the PXE config.
        In case of 'boot from volume', it updates the iSCSI info onto iLO and
        sets the node to boot from 'UefiTarget' boot device.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """

        # Set boot mode
        ilo_common.update_boot_mode(task)
        # Need to enable secure boot, if being requested
        ilo_common.update_secure_boot_mode(task, True)

        boot_mode = boot_mode_utils.get_boot_mode(task.node)

        if deploy_utils.is_iscsi_boot(task) and boot_mode == 'uefi':
            # Need to set 'ilo_uefi_iscsi_boot' param for clean up
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            # It will set iSCSI info onto iLO
            task.driver.management.set_iscsi_boot_target(task)
            manager_utils.node_set_boot_device(task, boot_devices.ISCSIBOOT,
                                               persistent=True)
        else:
            # Volume boot in BIOS boot mode is handled using
            # PXE boot interface
            super(IloPXEBoot, self).prepare_instance(task)

    @METRICS.timer('IloPXEBoot.clean_up_instance')
    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the PXE environment that was setup for booting
        the instance. It unlinks the instance kernel/ramdisk in the node's
        directory in tftproot and removes it's PXE config.
        In case of UEFI iSCSI booting, it cleans up iSCSI target information
        from the node.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        disable_secure_boot_if_supported(task)
        driver_internal_info = task.node.driver_internal_info

        if (deploy_utils.is_iscsi_boot(task)
            and task.node.driver_internal_info.get('ilo_uefi_iscsi_boot')):
            # It will clear iSCSI info from iLO in case of booting from
            # volume in UEFI boot mode
            task.driver.management.clear_iscsi_boot_target(task)
            driver_internal_info.pop('ilo_uefi_iscsi_boot', None)
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
        else:
            # Volume boot in BIOS boot mode is handled using
            # PXE boot interface
            super(IloPXEBoot, self).clean_up_instance(task)


class IloiPXEBoot(ipxe.iPXEBoot):

    @METRICS.timer('IloiPXEBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of Ironic ramdisk using PXE.

        This method prepares the boot of the deploy or rescue ramdisk after
        reading relevant information from the node's driver_info and
        instance_info.

        :param task: a task from TaskManager.
        :param ramdisk_params: the parameters to be passed to the ramdisk.
        :returns: None
        :raises: MissingParameterValue, if some information is missing in
            node's driver_info or instance_info.
        :raises: InvalidParameterValue, if some information provided is
            invalid.
        :raises: IronicException, if some power or set boot boot device
            operation failed on the node.
        :raises: IloOperationError, if some operation on iLO failed.
        """

        if task.node.provision_state in (states.DEPLOYING, states.RESCUING,
                                         states.CLEANING):
            prepare_node_for_deploy(task)

        super(IloiPXEBoot, self).prepare_ramdisk(task, ramdisk_params)

    @METRICS.timer('IloiPXEBoot.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info. In case of netboot,
        it updates the dhcp entries and switches the PXE config. In case of
        localboot, it cleans up the PXE config.
        In case of 'boot from volume', it updates the iSCSI info onto iLO and
        sets the node to boot from 'UefiTarget' boot device.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """

        # Set boot mode
        ilo_common.update_boot_mode(task)
        # Need to enable secure boot, if being requested
        ilo_common.update_secure_boot_mode(task, True)

        boot_mode = boot_mode_utils.get_boot_mode(task.node)

        if deploy_utils.is_iscsi_boot(task) and boot_mode == 'uefi':
            # Need to set 'ilo_uefi_iscsi_boot' param for clean up
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            # It will set iSCSI info onto iLO
            task.driver.management.set_iscsi_boot_target(task)
            manager_utils.node_set_boot_device(task, boot_devices.ISCSIBOOT,
                                               persistent=True)
        else:
            # Volume boot in BIOS boot mode is handled using
            # PXE boot interface
            super(IloiPXEBoot, self).prepare_instance(task)

    @METRICS.timer('IloiPXEBoot.clean_up_instance')
    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the PXE environment that was setup for booting
        the instance. It unlinks the instance kernel/ramdisk in the node's
        directory in tftproot and removes it's PXE config.
        In case of UEFI iSCSI booting, it cleans up iSCSI target information
        from the node.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        disable_secure_boot_if_supported(task)
        driver_internal_info = task.node.driver_internal_info

        if (deploy_utils.is_iscsi_boot(task)
            and task.node.driver_internal_info.get('ilo_uefi_iscsi_boot')):
            # It will clear iSCSI info from iLO in case of booting from
            # volume in UEFI boot mode
            task.driver.management.clear_iscsi_boot_target(task)
            driver_internal_info.pop('ilo_uefi_iscsi_boot', None)
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
        else:
            # Volume boot in BIOS boot mode is handled using
            # PXE boot interface
            super(IloiPXEBoot, self).clean_up_instance(task)
