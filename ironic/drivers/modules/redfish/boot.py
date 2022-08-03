# Copyright 2019 Red Hat, Inc.
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

from oslo_log import log
from oslo_utils import importutils
import tenacity

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.drivers import utils as driver_utils

LOG = log.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'deploy_kernel': _("URL or Glance UUID of the deployment kernel. "
                       "Required if deploy_iso is not set."),
    'deploy_ramdisk': _("URL or Glance UUID of the ramdisk that is mounted at "
                        "boot time. Required if deploy_iso is not set."),
    'deploy_iso': _("URL or Glance UUID of the deployment ISO to use. "
                    "Required if deploy_kernel/deploy_ramdisk are not set.")
}

OPTIONAL_PROPERTIES = {
    'config_via_removable': _("Boolean value to indicate whether or not the "
                              "driver should use virtual media USB or floppy "
                              "device for passing configuration information "
                              "to the ramdisk. Defaults to False. Optional."),
    'kernel_append_params': _("Additional kernel parameters to pass down to "
                              "instance kernel. These parameters can be "
                              "consumed by the kernel or by the applications "
                              "by reading /proc/cmdline. Mind severe cmdline "
                              "size limit. Overrides "
                              "[redfish]/kernel_append_params ironic "
                              "option."),
    'bootloader': _("URL or Glance UUID  of the EFI system partition "
                    "image containing EFI boot loader. This image will be "
                    "used by ironic when building UEFI-bootable ISO "
                    "out of kernel and ramdisk. Required for UEFI "
                    "when deploy_iso is not provided."),

}

RESCUE_PROPERTIES = {
    'rescue_kernel': _('URL or Glance UUID of the rescue kernel. Required for '
                       'rescue mode if rescue_iso is not set.'),
    'rescue_ramdisk': _('URL or Glance UUID of the rescue ramdisk with agent '
                        'that is used at node rescue time. Required for '
                        'rescue mode if rescue_iso is not set.'),
    'rescue_iso': _("URL or Glance UUID of the rescue ISO to use. Required "
                    "for rescue mode if rescue_kernel/rescue_ramdisk are "
                    "not set.")
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(driver_utils.OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(RESCUE_PROPERTIES)

IMAGE_SUBDIR = 'redfish'

sushy = importutils.try_import('sushy')


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
    mode = deploy_utils.rescue_or_deploy_mode(node)
    if not deploy_utils.needs_agent_ramdisk(node, mode=mode):
        # Ramdisk deploy does not need an agent, nor does it support any other
        # options. Skipping.
        return {'can_provide_config': False}

    d_info = node.driver_info

    iso_param = f'{mode}_iso'
    iso_ref = driver_utils.get_agent_iso(node, deprecated_prefix='redfish',
                                         mode=mode)
    if iso_ref is not None:
        deploy_info = {iso_param: iso_ref}
        can_config = False
    else:
        # There was never a deprecated prefix for kernel/ramdisk
        deploy_info = driver_utils.get_agent_kernel_ramdisk(node, mode)

        error_msg = _("Error validating Redfish virtual media. Some "
                      "parameters were missing in node's driver_info")

        deploy_utils.check_for_missing_params(deploy_info, error_msg)
        can_config = True

    deploy_info.update(
        {option: d_info.get(option, getattr(CONF.conductor, option, None))
         for option in OPTIONAL_PROPERTIES})

    if (d_info.get('config_via_removable') is None
            and d_info.get('config_via_floppy') is not None):
        LOG.warning('The config_via_floppy driver_info option is deprecated, '
                    'use config_via_removable for node %s', node.uuid)
        deploy_info['config_via_removable'] = d_info['config_via_floppy']

    deploy_info.update(redfish_utils.parse_driver_info(node))
    # Configuration can be provided in one of two cases:
    # 1) A removable disk is requested.
    # 2) An ISO is built from a kernel/initramfs pair.
    deploy_info['can_provide_config'] = \
        deploy_info.get('config_via_removable') or can_config

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
    deploy_info = node.instance_info.copy()

    # NOTE(etingof): this method is currently no-op, here for completeness
    return deploy_info


def _test_retry(exception):
    if isinstance(exception, sushy.exceptions.ServerSideError):
        # On some Dell hw, the eject media may still be in progress
        # https://storyboard.openstack.org/#!/story/2008504
        LOG.warning("Boot media insert failed for node %(node)s, "
                    "will retry after 3 seconds",
                    {'node': exception.node_uuid})
        return True
    return False


@tenacity.retry(retry=tenacity.retry_if_exception(_test_retry),
                stop=tenacity.stop_after_attempt(3),
                wait=tenacity.wait_fixed(3),
                reraise=True)
def _insert_vmedia(task, managers, boot_url, boot_device):
    """Insert bootable ISO image into virtual CD or DVD

    :param task: A task from TaskManager.
    :param managers: A list of System managers.
    :param boot_url: URL to a bootable ISO image
    :param boot_device: sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
        `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY`
    :raises: InvalidParameterValue, if no suitable virtual CD or DVD is
        found on the node.
    """
    for manager in managers:
        for v_media in manager.virtual_media.get_members():
            if boot_device not in v_media.media_types:
                continue

            if v_media.inserted:
                if v_media.image == boot_url:
                    LOG.debug("Boot media %(boot_url)s is already "
                              "inserted into %(boot_device)s for node "
                              "%(node)s", {'node': task.node.uuid,
                                           'boot_url': boot_url,
                                           'boot_device': boot_device})
                    return

                continue

            try:
                v_media.insert_media(boot_url, inserted=True,
                                     write_protected=True)
            except sushy.exceptions.ServerSideError as e:
                e.node_uuid = task.node.uuid
                raise

            LOG.info("Inserted boot media %(boot_url)s into "
                     "%(boot_device)s for node "
                     "%(node)s", {'node': task.node.uuid,
                                  'boot_url': boot_url,
                                  'boot_device': boot_device})
            return

    raise exception.InvalidParameterValue(
        _('No suitable virtual media device found'))


def _eject_vmedia(task, managers, boot_device=None):
    """Eject virtual CDs and DVDs

    :param task: A task from TaskManager.
    :param managers: A list of System managers.
    :param boot_device: sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
        `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY` or `None` to
        eject everything (default).
    :return: True if any device was ejected, else False
    :raises: InvalidParameterValue, if no suitable virtual CD or DVD is
        found on the node.
    """
    found = False
    for manager in managers:
        for v_media in manager.virtual_media.get_members():
            if boot_device and boot_device not in v_media.media_types:
                continue

            inserted = v_media.inserted

            if inserted:
                v_media.eject_media()
                found = True

            LOG.info("Boot media is%(already)s ejected from "
                     "%(boot_device)s for node %(node)s"
                     "", {'node': task.node.uuid,
                          'already': '' if inserted else ' already',
                          'boot_device': v_media.name})
    return found


def eject_vmedia(task, boot_device=None):
    """Eject virtual CDs and DVDs

    :param task: A task from TaskManager.
    :param boot_device: sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
        `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY` or `None` to
        eject everything (default).
    :raises: InvalidParameterValue, if no suitable virtual CD or DVD is
        found on the node.
    """
    system = redfish_utils.get_system(task.node)
    if _eject_vmedia(task, system.managers, boot_device=boot_device):
        LOG.debug('Cleaning up unused files after ejecting %(dev)s for node '
                  '%(node)s', {'dev': boot_device or 'all devices',
                               'node': task.node.uuid})
        if (boot_device is None
                or boot_device == sushy.VIRTUAL_MEDIA_USBSTICK):
            image_utils.cleanup_disk_image(task, prefix='configdrive')
        if boot_device is None or boot_device == sushy.VIRTUAL_MEDIA_CD:
            image_utils.cleanup_iso_image(task)


def _has_vmedia_device(managers, boot_device, inserted=None):
    """Indicate if device exists at any of the managers

    :param managers: A list of System managers.
    :param boot_device: One or more sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
        `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY`. Several devices are
        checked in the given order.
    :param inserted: If not None, only return a device with a matching
        inserted status.
    :return: The device that could be found or False.
    """
    if isinstance(boot_device, str):
        boot_device = [boot_device]

    for dev in boot_device:
        for manager in managers:
            for v_media in manager.virtual_media.get_members():
                if dev not in v_media.media_types:
                    continue
                if (inserted is not None
                        and bool(v_media.inserted) is not inserted):
                    continue
                return dev
    return False


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


class RedfishVirtualMediaBoot(base.BootInterface):
    """Virtual media boot interface over Redfish.

    Virtual Media allows booting the system from the "virtual"
    CD/DVD drive containing the user image that BMC "inserts"
    into the drive.

    The CD/DVD images must be in ISO format and (depending on
    BMC implementation) could be pulled over HTTP, served as
    iSCSI targets or NFS volumes.

    The baseline boot workflow looks like this:

    1. Pull kernel, ramdisk and ESP (FAT partition image with EFI boot
       loader) images (ESP is only needed for UEFI boot)
    2. Create bootable ISO out of images (#1), push it to Glance and
       pass to the BMC as Swift temporary URL
    3. Optionally create floppy image with desired system configuration data,
       push it to Glance and pass to the BMC as Swift temporary URL
    4. Insert CD/DVD and (optionally) floppy images and set proper boot mode

    For building deploy or rescue ISO, redfish boot interface uses
    `deploy_kernel`/`deploy_ramdisk` or `rescue_kernel`/`rescue_ramdisk`
    properties from `[instance_info]` or `[driver_info]`.

    For building boot (user) ISO, redfish boot interface seeks `kernel_id`
    and `ramdisk_id` properties in the Glance image metadata found in
    `[instance_info]image_source` node property.
    """

    capabilities = ['iscsi_volume_boot', 'ramdisk_boot',
                    'ramdisk_boot_configdrive']

    def __init__(self):
        """Initialize the Redfish virtual media boot interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(RedfishVirtualMediaBoot, self).__init__()
        if not sushy:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_('Unable to import the sushy library'))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return REQUIRED_PROPERTIES

    def _validate_driver_info(self, task):
        """Validate the prerequisites for virtual media based boot.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any parameters are incorrect
        :raises: MissingParameterValue if some mandatory information
            is missing on the node
        """
        node = task.node

        _parse_driver_info(node)
        # Issue the deprecation warning if needed
        driver_utils.get_agent_iso(node, deprecated_prefix='redfish')

    def _validate_instance_info(self, task):
        """Validate instance image information for the task's node.

        This method validates whether the 'instance_info' property of the
        supplied node contains the required information for this driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any parameters are incorrect
        :raises: MissingParameterValue if some mandatory information
            is missing on the node
        """
        node = task.node

        # NOTE(dtantsur): if we're are writing an image with local boot
        # the boot interface does not care about image parameters and
        # must not validate them.
        if (not task.driver.storage.should_write_image(task)
                or deploy_utils.get_boot_option(node) == 'local'):
            return

        d_info = _parse_deploy_info(node)
        deploy_utils.validate_image_properties(task, d_info)

    def _validate_vendor(self, task, managers):
        """Validates vendor specific requirements for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param managers: Redfish managers for Redfish system associated
            with node.
        :raises: InvalidParameterValue if vendor not supported
        """
        vendor = task.node.properties.get('vendor')
        if not vendor:
            return

        if 'Dell' in vendor.split():
            # Check if iDRAC fw >= 6.00.00.00 that supports virtual media boot
            bmc_manager = [m for m in managers
                           if m.manager_type == sushy.MANAGER_TYPE_BMC]
            if bmc_manager:
                fwv = bmc_manager[0].firmware_version.split('.')
                if int(fwv[0]) >= 6:
                    return
            raise exception.InvalidParameterValue(
                _("The %(iface)s boot interface is not suitable for node "
                  "%(node)s with vendor %(vendor)s and BMC version %(fwv)s, "
                  "upgrade to 6.00.00.00 or newer or use "
                  "idrac-redfish-virtual-media instead")
                % {'iface': task.node.boot_interface,
                   'node': task.node.uuid, 'vendor': vendor,
                   'fwv': bmc_manager[0].firmware_version})

    def validate(self, task):
        """Validate the deployment information for the task's node.

        This method validates whether the 'driver_info' and/or 'instance_info'
        properties of the task's node contains the required information for
        this interface to function.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        self._validate_driver_info(task)
        self._validate_instance_info(task)

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

    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of deploy or rescue ramdisk over virtual media.

        This method prepares the boot of the deploy or rescue ramdisk after
        reading relevant information from the node's driver_info and
        instance_info.

        :param task: A task from TaskManager.
        :param ramdisk_params: the parameters to be passed to the ramdisk.
        :returns: None
        :raises: MissingParameterValue, if some information is missing in
            node's driver_info or instance_info.
        :raises: InvalidParameterValue, if some information provided is
            invalid.
        :raises: IronicException, if some power or set boot boot device
            operation failed on the node.
        """
        node = task.node
        if not driver_utils.need_prepare_ramdisk(node):
            return

        d_info = _parse_driver_info(node)
        managers = redfish_utils.get_system(task.node).managers

        self._validate_vendor(task, managers)

        if manager_utils.is_fast_track(task):
            if _has_vmedia_device(managers, sushy.VIRTUAL_MEDIA_CD,
                                  inserted=True):
                LOG.debug('Fast track operation for node %s, not inserting '
                          'any devices', node.uuid)
                return
            else:
                LOG.warning('Fast track is possible for node %s, but no ISO '
                            'is currently inserted! Proceeding with '
                            'normal operation.', node.uuid)

        # NOTE(TheJulia): Since we're deploying, cleaning, or rescuing,
        # with virtual media boot, we should generate a token!
        # However, we don't have a way to inject it with a pre-built ISO
        # if a removable disk is not used.
        can_config = d_info.pop('can_provide_config', True)
        if can_config:
            manager_utils.add_secret_token(node, pregenerated=True)
            node.save()
            ramdisk_params['ipa-agent-token'] = \
                node.driver_internal_info['agent_secret_token']

        manager_utils.node_power_action(task, states.POWER_OFF)

        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        if deploy_nic_mac is not None:
            ramdisk_params['BOOTIF'] = deploy_nic_mac
        if CONF.debug and 'ipa-debug' not in ramdisk_params:
            ramdisk_params['ipa-debug'] = '1'

        # NOTE(TheJulia): This is a mandatory setting for virtual media
        # based deployment operations.
        ramdisk_params['boot_method'] = 'vmedia'

        config_via_removable = d_info.get('config_via_removable')
        if config_via_removable:

            removable = _has_vmedia_device(
                managers,
                # Prefer USB devices since floppies are outdated
                [sushy.VIRTUAL_MEDIA_USBSTICK, sushy.VIRTUAL_MEDIA_FLOPPY])
            if removable:
                floppy_ref = image_utils.prepare_floppy_image(
                    task, params=ramdisk_params)

                _eject_vmedia(task, managers, removable)
                _insert_vmedia(task, managers, floppy_ref, removable)

                LOG.info('Inserted virtual %(type)s device with configuration'
                         ' for node %(node)s',
                         {'node': task.node.uuid, 'type': removable})

            else:
                LOG.warning('Config via a removable device is requested, but '
                            'virtual USB and floppy devices are not '
                            'available on node %(node)s',
                            {'node': task.node.uuid})

        mode = deploy_utils.rescue_or_deploy_mode(node)

        iso_ref = image_utils.prepare_deploy_iso(task, ramdisk_params,
                                                 mode, d_info)

        _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_CD)
        _insert_vmedia(task, managers, iso_ref, sushy.VIRTUAL_MEDIA_CD)

        del managers

        boot_mode_utils.sync_boot_mode(task)

        self._set_boot_device(task, boot_devices.CDROM)

        LOG.debug("Node %(node)s is set to one time boot from "
                  "%(device)s", {'node': task.node.uuid,
                                 'device': boot_devices.CDROM})

    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up the environment that was setup for booting the
        deploy ramdisk.

        :param task: A task from TaskManager.
        :returns: None
        """
        if manager_utils.is_fast_track(task):
            LOG.debug('Fast track operation for node %s, not ejecting '
                      'any devices', task.node.uuid)
            return

        LOG.debug("Cleaning up deploy boot for "
                  "%(node)s", {'node': task.node.uuid})
        self._eject_all(task)

    def prepare_instance(self, task):
        """Prepares the boot of instance over virtual media.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info.

        The internal logic is as follows:

        - If `boot_option` requested for this deploy is 'local', then set the
          node to boot from disk.
        - Unless `boot_option` requested for this deploy is 'ramdisk', pass
          root disk/partition ID to virtual media boot image
        - Otherwise build boot image, insert it into virtual media device
          and set node to boot from CD.

        :param task: a task from TaskManager.
        :returns: None
        :raises: InstanceDeployFailure, if its try to boot iSCSI volume in
                 'BIOS' boot mode.
        """
        node = task.node

        self._eject_all(task)

        boot_mode_utils.sync_boot_mode(task)
        boot_mode_utils.configure_secure_boot_if_needed(task)

        boot_option = deploy_utils.get_boot_option(node)
        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        if boot_option == "local" or iwdi:
            self._set_boot_device(task, boot_devices.DISK, persistent=True)

            LOG.debug("Node %(node)s is set to permanently boot from local "
                      "%(device)s", {'node': task.node.uuid,
                                     'device': boot_devices.DISK})
            return

        params = {}

        if boot_option != 'ramdisk':
            root_uuid = node.driver_internal_info.get('root_uuid_or_disk_id')
            if not root_uuid and task.driver.storage.should_write_image(task):
                LOG.warning(
                    "The UUID of the root partition could not be found for "
                    "node %s. Booting instance from disk anyway.", node.uuid)

                self._set_boot_device(task, boot_devices.DISK, persistent=True)

                return

            params.update(root_uuid=root_uuid)

        managers = redfish_utils.get_system(task.node).managers

        deploy_info = _parse_deploy_info(node)
        iso_ref = image_utils.prepare_boot_iso(task, deploy_info, **params)
        _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_CD)
        _insert_vmedia(task, managers, iso_ref, sushy.VIRTUAL_MEDIA_CD)

        if boot_option == 'ramdisk':
            self._attach_configdrive(task, managers)

        del managers

        persistent = True
        if node.driver_info.get('force_persistent_boot_device',
                                'Default') == 'Never':
            persistent = False
        self._set_boot_device(task, boot_devices.CDROM, persistent=persistent)

        LOG.debug("Node %(node)s is set to permanently boot from "
                  "%(device)s", {'node': task.node.uuid,
                                 'device': boot_devices.CDROM})

    def _attach_configdrive(self, task, managers):
        configdrive = manager_utils.get_configdrive_image(task.node)
        if not configdrive:
            return

        _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK)
        cd_ref = image_utils.prepare_configdrive_image(task, configdrive)
        try:
            _insert_vmedia(task, managers, cd_ref,
                           sushy.VIRTUAL_MEDIA_USBSTICK)
        except exception.InvalidParameterValue:
            raise exception.InstanceDeployFailure(
                _('Cannot attach configdrive for node %s: no suitable '
                  'virtual USB slot has been found') % task.node.uuid)

    def _eject_all(self, task):
        managers = redfish_utils.get_system(task.node).managers

        _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_CD)
        config_via_removable = (
            task.node.driver_info.get('config_via_removable')
            or task.node.driver_info.get('config_via_floppy')
        )
        if config_via_removable:
            _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK)
            _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_FLOPPY)

            image_utils.cleanup_floppy_image(task)

        boot_option = deploy_utils.get_boot_option(task.node)
        if (boot_option == 'ramdisk'
                and task.node.instance_info.get('configdrive') is not None):
            _eject_vmedia(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK)
            image_utils.cleanup_disk_image(task, prefix='configdrive')

        image_utils.cleanup_iso_image(task)

    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the environment that was setup for booting
        the instance.

        :param task: A task from TaskManager.
        :returns: None
        """
        LOG.debug("Cleaning up instance boot for "
                  "%(node)s", {'node': task.node.uuid})
        self._eject_all(task)
        boot_mode_utils.deconfigure_secure_boot_if_needed(task)

    @classmethod
    def _set_boot_device(cls, task, device, persistent=False):
        """Set the boot device for a node.

        This is a hook to allow other boot interfaces, inheriting from standard
        `redfish` boot interface, implement their own weird ways of setting
        boot device.

        :param task: a TaskManager instance.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Whether to set next-boot, or make the change
            permanent. Default: False.
        :raises: InvalidParameterValue if the validation of the
            ManagementInterface fails.
        """
        manager_utils.node_set_boot_device(task, device, persistent)
