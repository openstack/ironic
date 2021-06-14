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

from ironic_lib import metrics_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import images
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import image_utils
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

CONF = cfg.CONF

REQUIRED_PROPERTIES = {
    'deploy_iso': _("UUID (from Glance) of the deployment ISO. Required.")
}
RESCUE_PROPERTIES = {
    'rescue_iso': _("UUID (from Glance) of the rescue ISO. Only "
                    "required if rescue mode is being used and ironic is "
                    "managing booting the rescue ramdisk.")
}
REQUIRED_PROPERTIES_UEFI_HTTPS_BOOT = {
    'deploy_kernel': _("URL or Glance UUID of the deployment kernel. "
                       "Required."),
    'deploy_ramdisk': _("URL or Glance UUID of the ramdisk that is "
                        "mounted at boot time. Required."),
}
RESCUE_PROPERTIES_UEFI_HTTPS_BOOT = {
    'rescue_kernel': _('URL or Glance UUID of the rescue kernel. This '
                       'value is required for rescue mode.'),
    'rescue_ramdisk': _('URL or Glance UUID of the rescue ramdisk with '
                        'agent that is used at node rescue time. '
                        'The value is required for rescue mode.'),
}
OPTIONAL_PROPERTIES = {
    'bootloader': _("URL or Glance UUID  of the EFI system partition "
                    "image containing EFI boot loader. This image will "
                    "be used by ironic when building UEFI-bootable ISO "
                    "out of kernel and ramdisk. Required for UEFI "
                    "boot from partition images."),
    'ilo_add_certificates': _("Boolean value that indicates whether the "
                              "certificates require to be added to the "
                              "iLO."),
    'kernel_append_params': _("Additional kernel parameters to pass down "
                              "to instance kernel. These parameters can "
                              "be consumed by the kernel or by the "
                              "applications by reading /proc/cmdline. "
                              "Mind severe cmdline size limit. Overrides "
                              "[ilo]/kernel_append_params ironic option.")
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
    d_info = {}
    iso_ref = driver_utils.get_agent_iso(node, mode, deprecated_prefix='ilo')
    if iso_ref:
        d_info[f'{mode}_iso'] = iso_ref
    else:
        d_info = driver_utils.get_agent_kernel_ramdisk(
            node, mode, deprecated_prefix='ilo')
        d_info['bootloader'] = driver_utils.get_field(node, 'bootloader',
                                                      deprecated_prefix='ilo',
                                                      use_conf=True)

    error_msg = (_("Error validating iLO boot for %s. Some "
                   "parameters were missing in node's driver_info") % mode)
    deploy_utils.check_for_missing_params(d_info, error_msg)
    d_info['kernel_append_params'] = node.driver_info.get(
        'kernel_append_params')

    return d_info


def _get_boot_iso(task, root_uuid):
    """This method returns a boot ISO to boot the node.

    It chooses one of the three options in the order as below:
    1. Does nothing if 'boot_iso' is present in node's instance_info.
    2. Image deployed has a meta-property 'boot_iso' in Glance. This should
       refer to the UUID of the boot_iso which exists in Glance.
    3. Returns a boot ISO created on the fly using kernel and ramdisk
       mentioned in the image deployed.

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
    :raises: exception.ImageRefValidationFailed if boot_iso is not
        HTTP(S) URL.
    """
    LOG.debug("Trying to get a boot ISO to boot the baremetal node")

    # Option 1 - Check if user has provided boot_iso in node's
    # instance_info
    boot_iso = driver_utils.get_field(task.node, 'boot_iso',
                                      deprecated_prefix='ilo',
                                      collection='instance_info')
    if boot_iso:
        LOG.debug("Using boot_iso provided in node's instance_info")
        if not service_utils.is_glance_image(boot_iso):
            try:
                image_service.HttpImageService().validate_href(boot_iso)
            except exception.ImageRefValidationFailed:
                with excutils.save_and_reraise_exception():
                    LOG.error("Virtual media deploy accepts only Glance "
                              "images or HTTP(S) URLs as "
                              "instance_info['boot_iso']. Either %s "
                              "is not a valid HTTP(S) URL or is "
                              "not reachable.", boot_iso)

        return boot_iso

    # Option 2 - Check if user has provided a boot_iso in Glance. If boot_iso
    # is a supported non-glance href execution will proceed to option 3.
    deploy_info = _parse_deploy_info(task.node)

    image_href = deploy_info['image_source']
    image_properties = (
        images.get_image_properties(
            task.context, image_href, ['boot_iso']))

    boot_iso_uuid = image_properties.get('boot_iso')

    if boot_iso_uuid:
        LOG.debug("Found boot_iso %s in Glance", boot_iso_uuid)
        return boot_iso_uuid

    # NOTE(rameshg87): Functionality to share the boot ISOs created for
    # similar instances (instances with same deployed image) is
    # not implemented as of now. Creation/Deletion of such a shared boot ISO
    # will require synchronisation across conductor nodes for the shared boot
    # ISO.  Such a synchronisation mechanism doesn't exist in ironic as of now.

    # Option 3 - Create boot_iso from kernel/ramdisk, upload to Swift
    # or web server and provide its name.
    return image_utils.prepare_boot_iso(task, deploy_info, root_uuid)


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
    parse_driver_info(node)


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
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['deploy_boot_mode'] = 'uefi'
            task.node.driver_internal_info = driver_internal_info
            task.node.save()


class IloVirtualMediaBoot(base.BootInterface):

    capabilities = ['iscsi_volume_boot', 'ramdisk_boot']

    def get_properties(self):
        # TODO(stendulker): COMMON_PROPERTIES should also include rescue
        # related properties (RESCUE_PROPERTIES). We can add them in Rocky,
        # when classic drivers get removed.
        return dict(driver_utils.OPTIONAL_PROPERTIES, **COMMON_PROPERTIES)

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
        boot_iso = driver_utils.get_field(node, 'boot_iso',
                                          deprecated_prefix='ilo',
                                          collection='instance_info')
        if boot_option == "ramdisk" and boot_iso:
            if not service_utils.is_glance_image(boot_iso):
                try:
                    image_service.HttpImageService().validate_href(boot_iso)
                except exception.ImageRefValidationFailed:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Virtual media deploy with 'ramdisk' "
                                  "boot_option accepts only Glance images or "
                                  "HTTP(S) URLs as "
                                  "instance_info['boot_iso']. Either %s "
                                  "is not a valid HTTP(S) URL or is not "
                                  "reachable.", boot_iso)
            return

        _validate_driver_info(task)

        if not task.driver.storage.should_write_image(task):
            return
        else:
            _validate_instance_image_info(task)

    def validate_inspection(self, task):
        """Validate that the node has required properties for inspection.

        :param task: A TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        :raises: UnsupportedDriverExtension
        """
        try:
            _validate_driver_info(task)
        except exception.MissingParameterValue:
            # Fall back to non-managed in-band inspection
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='inspection')

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
                                        states.RESCUING,
                                        states.INSPECTING):
            return

        prepare_node_for_deploy(task)

        # Clear boot_iso if it's a glance image to force recreate
        # another one again (or use existing one in glance).
        # This is mainly for rebuild and rescue scenario.
        if service_utils.is_glance_image(
                node.instance_info.get('image_source')):
            instance_info = node.instance_info
            instance_info.pop('boot_iso', None)
            instance_info.pop('ilo_boot_iso', None)
            node.instance_info = instance_info
            node.save()

        # Eject all virtual media devices, as we are going to use them
        # during boot.
        ilo_common.eject_vmedia_devices(task)

        # NOTE(TheJulia): Since we're deploying, cleaning, or rescuing,
        # with virtual media boot, we should generate a token!
        manager_utils.add_secret_token(task.node, pregenerated=True)
        ramdisk_params['ipa-agent-token'] = \
            task.node.driver_internal_info['agent_secret_token']
        task.node.save()

        ramdisk_params['boot_method'] = 'vmedia'

        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        if deploy_nic_mac is not None:
            ramdisk_params['BOOTIF'] = deploy_nic_mac

        mode = deploy_utils.rescue_or_deploy_mode(node)
        d_info = parse_driver_info(node, mode)
        if 'rescue_iso' in d_info:
            ilo_common.setup_vmedia(task, d_info['rescue_iso'], ramdisk_params)
        elif 'deploy_iso' in d_info:
            ilo_common.setup_vmedia(task, d_info['deploy_iso'], ramdisk_params)
        else:
            iso = image_utils.prepare_deploy_iso(task, ramdisk_params,
                                                 mode, d_info)
            ilo_common.setup_vmedia(task, iso)

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
        boot_mode_utils.configure_secure_boot_if_needed(task)

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
        boot_mode_utils.deconfigure_secure_boot_if_needed(task)

        if (deploy_utils.is_iscsi_boot(task)
            and task.node.driver_internal_info.get('ilo_uefi_iscsi_boot')):
            # It will clear iSCSI info from iLO
            task.driver.management.clear_iscsi_boot_target(task)
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info.pop('ilo_uefi_iscsi_boot', None)
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
        else:
            image_utils.cleanup_iso_image(task)
            ilo_common.cleanup_vmedia_boot(task)

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
        image_utils.cleanup_iso_image(task)

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
        i_info['boot_iso'] = boot_iso
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

        boot_mode = boot_mode_utils.get_boot_mode(task.node)

        if deploy_utils.is_iscsi_boot(task) and boot_mode == 'uefi':
            # Need to enable secure boot, if being requested
            boot_mode_utils.configure_secure_boot_if_needed(task)
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
        driver_internal_info = task.node.driver_internal_info

        if (deploy_utils.is_iscsi_boot(task)
                and task.node.driver_internal_info.get('ilo_uefi_iscsi_boot')):
            boot_mode_utils.deconfigure_secure_boot_if_needed(task)
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
        boot_mode = boot_mode_utils.get_boot_mode(task.node)

        if deploy_utils.is_iscsi_boot(task) and boot_mode == 'uefi':
            # Need to enable secure boot, if being requested
            boot_mode_utils.configure_secure_boot_if_needed(task)
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
        driver_internal_info = task.node.driver_internal_info

        if (deploy_utils.is_iscsi_boot(task)
                and task.node.driver_internal_info.get('ilo_uefi_iscsi_boot')):
            boot_mode_utils.deconfigure_secure_boot_if_needed(task)
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


class IloUefiHttpsBoot(base.BootInterface):

    capabilities = ['ramdisk_boot']

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return REQUIRED_PROPERTIES_UEFI_HTTPS_BOOT

    def _validate_hrefs(self, image_dict):
        """Validates if the given URLs are secured URLs.

        If the given URLs are not glance images then validates if the URLs
        are secured.

        :param image_dict: a dictionary containing property/URL pair.
        :returns: None
        :raises: InvalidParameterValue, if any of URLs provided are insecure.
        """
        insecure_props = []

        for prop in image_dict:
            image_ref = image_dict.get(prop)
            if image_ref is not None and image_ref.startswith('http://'):
                insecure_props.append(image_ref)

        if len(insecure_props) > 0:
            error = (_('Secure URLs exposed over HTTPS are expected. '
                       'Insecure URLs are provided for %s') % insecure_props)
            raise exception.InvalidParameterValue(error)

    def _parse_deploy_info(self, node):
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
        deploy_info.update(self._parse_driver_info(node))

        return deploy_info

    def _parse_driver_info(self, node, mode='deploy'):
        """Gets the node specific deploy/rescue info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        deploy images to the node.

        :param node: a single Node.
        :param mode: Label indicating a deploy or rescue operation being
            carried out on the node. Supported values are 'deploy' and
            'rescue'. Defaults to 'deploy', indicating deploy operation
            is being carried out.
        :returns: A dict with the driver_info values.
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the required parameters are
            invalid.
        """
        deploy_info = parse_driver_info(node, mode)

        should_add_certs = node.driver_info.get('ilo_add_certificates', True)

        if should_add_certs is not None:
            try:
                should_add_certs = strutils.bool_from_string(should_add_certs,
                                                             strict=True)
            except ValueError:
                raise exception.InvalidParameterValue(
                    _('Invalid value type set in driver_info/'
                      'ilo_add_certificates on node %(node)s. '
                      'The value should be a Boolean '
                      ' not "%(value)s"'
                      ) % {'value': should_add_certs, 'node': node.uuid})

        self._validate_hrefs(deploy_info)

        deploy_info.update(ilo_common.parse_driver_info(node))

        return deploy_info

    def _validate_driver_info(self, task):
        """Validates the prerequisites for ilo-uefi-https boot interface.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any parameters are incorrect
        :raises: MissingParameterValue if some mandatory information
            is missing on the node
        """
        node = task.node

        self._parse_driver_info(node)

    def _validate_instance_image_info(self, task):
        """Validate instance image information for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue, if some information is invalid.
        :raises: MissingParameterValue if 'kernel_id' and 'ramdisk_id' are
            missing in the Glance image or 'kernel' and 'ramdisk' not provided
            in instance_info for non-Glance image.
        """
        node = task.node

        d_info = deploy_utils.get_image_instance_info(node)

        self._validate_hrefs(d_info)

        if node.driver_internal_info.get('is_whole_disk_image'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        deploy_utils.validate_image_properties(task.context, d_info, props)

    @METRICS.timer('IloUefiHttpsBoot.validate')
    def validate(self, task):
        """Validate the deployment information for the task's node.

        This method validates whether the 'driver_info' and/or 'instance_info'
        properties of the task's node contains the required information for
        this interface to function.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        node = task.node
        boot_option = deploy_utils.get_boot_option(node)
        try:
            boot_mode = ilo_common.get_current_boot_mode(task.node)
        except exception.IloOperationError:
            error = _("Validation for 'ilo-uefi-https' boot interface failed. "
                      "Could not determine current boot mode for node "
                      "%(node)s.") % node.uuid
            raise exception.InvalidParameterValue(error)

        if boot_mode.lower() != 'uefi':
            error = _("Validation for 'ilo-uefi-https' boot interface failed. "
                      "The node is required to be in 'UEFI' boot mode.")
            raise exception.InvalidParameterValue(error)

        boot_iso = driver_utils.get_field(node, 'boot_iso',
                                          deprecated_prefix='ilo',
                                          collection='instance_info')
        if boot_option == "ramdisk" and boot_iso:
            if not service_utils.is_glance_image(boot_iso):
                try:
                    image_service.HttpImageService().validate_href(boot_iso)
                except exception.ImageRefValidationFailed:
                    with excutils.save_and_reraise_exception():
                        LOG.error("UEFI-HTTPS boot with 'ramdisk' "
                                  "boot_option accepts only Glance images or "
                                  "HTTPS URLs as "
                                  "instance_info['boot_iso']. Either %s "
                                  "is not a valid HTTPS URL or is not "
                                  "reachable.", boot_iso)
            return

        self._validate_driver_info(task)

        if task.driver.storage.should_write_image(task):
            self._validate_instance_image_info(task)

    def validate_inspection(self, task):
        """Validate that the node has required properties for inspection.

        :param task: A TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        :raises: UnsupportedDriverExtension
        """
        try:
            self._validate_driver_info(task)
        except exception.MissingParameterValue:
            # Fall back to non-managed in-band inspection
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='inspection')

    @METRICS.timer('IloUefiHttpsBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of deploy ramdisk using UEFI-HTTPS boot.

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
                                        states.RESCUING,
                                        states.INSPECTING):
            return

        prepare_node_for_deploy(task)

        # Clear boot_iso if it's a glance image to force recreate
        # another one again (or use existing one in glance).
        # This is mainly for rebuild and rescue scenario.
        if service_utils.is_glance_image(
                node.instance_info.get('image_source')):
            instance_info = node.instance_info
            instance_info.pop('boot_iso', None)
            instance_info.pop('ilo_boot_iso', None)
            node.instance_info = instance_info
            node.save()

        # NOTE(TheJulia): Since we're deploying, cleaning, or rescuing,
        # with virtual media boot, we should generate a token!
        manager_utils.add_secret_token(node, pregenerated=True)
        ramdisk_params['ipa-agent-token'] = \
            task.node.driver_internal_info['agent_secret_token']
        task.node.save()

        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        if deploy_nic_mac is not None:
            ramdisk_params['BOOTIF'] = deploy_nic_mac

        # Signal to IPA that this is a vmedia boot operation.
        ramdisk_params['boot_method'] = 'vmedia'

        mode = 'deploy'
        if node.provision_state == states.RESCUING:
            mode = 'rescue'

        d_info = self._parse_driver_info(node, mode)

        iso_ref = image_utils.prepare_deploy_iso(task, ramdisk_params,
                                                 mode, d_info)

        LOG.debug("Set 'UEFIHTTP' as one time boot option on the node "
                  "%(node)s to boot from URL %(iso_ref)s.",
                  {'node': node.uuid, 'iso_ref': iso_ref})

        ilo_common.add_certificates(task)
        ilo_common.setup_uefi_https(task, iso_ref)

    @METRICS.timer('IloUefiHttpsBoot.clean_up_ramdisk')
    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up the environment that was setup for booting the
        deploy ramdisk.

        :param task: A task from TaskManager.
        :returns: None
        """
        LOG.debug("Cleaning up deploy boot for "
                  "%(node)s", {'node': task.node.uuid})

        image_utils.cleanup_iso_image(task)

    @METRICS.timer('IloUefiHttpsBoot.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info.
        It does the following depending on boot_option for deploy:

        - If the boot_option requested for this deploy is 'local' or image is
          a whole disk image, then it sets the node to boot from disk.
        - Otherwise it finds/creates the boot ISO, sets the node boot option
          to UEFIHTTP and sets the URL as the boot ISO to boot the instance
          image.

        :param task: a task from TaskManager.
        :returns: None
        :raises: IloOperationError, if some operation on iLO failed.
        :raises: InstanceDeployFailure, if its try to boot iSCSI volume in
                 'BIOS' boot mode.
        """
        node = task.node
        image_utils.cleanup_iso_image(task)
        boot_option = deploy_utils.get_boot_option(task.node)

        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        if boot_option == "local" or iwdi:
            manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                               persistent=True)
            LOG.debug("Node %(node)s is set to permanently boot from local "
                      "%(device)s", {'node': task.node.uuid,
                                     'device': boot_devices.DISK})
            # Need to enable secure boot, if being requested
            boot_mode_utils.configure_secure_boot_if_needed(task)
            return

        params = {}

        if boot_option != 'ramdisk':
            root_uuid = node.driver_internal_info.get('root_uuid_or_disk_id')
            if not root_uuid and task.driver.storage.should_write_image(task):
                LOG.warning(
                    "The UUID of the root partition could not be found for "
                    "node %s. Booting instance from disk anyway.", node.uuid)
                manager_utils.node_set_boot_device(task, boot_devices.DISK,
                                                   persistent=True)
                # Need to enable secure boot, if being requested
                boot_mode_utils.configure_secure_boot_if_needed(task)

                return
            params.update(root_uuid=root_uuid)

        d_info = self._parse_deploy_info(node)
        iso_ref = image_utils.prepare_boot_iso(task, d_info, **params)

        if boot_option != 'ramdisk':
            i_info = node.instance_info
            i_info['boot_iso'] = iso_ref
            node.instance_info = i_info
            node.save()

        # Need to enable secure boot, if being requested
        boot_mode_utils.configure_secure_boot_if_needed(task)
        ilo_common.setup_uefi_https(task, iso_ref, persistent=True)

        LOG.debug("Node %(node)s is set to boot from UEFIHTTP "
                  "boot option", {'node': task.node.uuid})

    @METRICS.timer('IloUefiHttpsBoot.clean_up_instance')
    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the environment that was setup for booting
        the instance.

        :param task: A task from TaskManager.
        :returns: None
        """
        LOG.debug("Cleaning up instance boot for "
                  "%(node)s", {'node': task.node.uuid})

        image_utils.cleanup_iso_image(task)
        boot_mode_utils.deconfigure_secure_boot_if_needed(task)

    @METRICS.timer('IloUefiHttpsBoot.validate_rescue')
    def validate_rescue(self, task):
        """Validate that the node has required properties for rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        """
        self._parse_driver_info(task.node, mode='rescue')
