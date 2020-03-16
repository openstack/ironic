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

import os
import shutil
import tempfile
from urllib import parse as urlparse

from ironic_lib import utils as ironic_utils
from oslo_log import log
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import images
from ironic.common import states
from ironic.common import swift
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import utils as redfish_utils

LOG = log.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'deploy_kernel': _("URL or Glance UUID of the deployment kernel. "
                       "Required."),
    'deploy_ramdisk': _("URL or Glance UUID of the ramdisk that is "
                        "mounted at boot time. Required.")
}

OPTIONAL_PROPERTIES = {
    'config_via_floppy': _("Boolean value to indicate whether or not the "
                           "driver should use virtual media Floppy device "
                           "for passing configuration information to the "
                           "ramdisk. Defaults to False. Optional."),
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
                    "boot from partition images."),

}

RESCUE_PROPERTIES = {
    'rescue_kernel': _('URL or Glance UUID of the rescue kernel. This value '
                       'is required for rescue mode.'),
    'rescue_ramdisk': _('URL or Glance UUID of the rescue ramdisk with agent '
                        'that is used at node rescue time. This value is '
                        'required for rescue mode.'),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(RESCUE_PROPERTIES)

KERNEL_RAMDISK_LABELS = {
    'deploy': REQUIRED_PROPERTIES,
    'rescue': RESCUE_PROPERTIES
}

sushy = importutils.try_import('sushy')


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

    IMAGE_SUBDIR = 'redfish'

    capabilities = ['iscsi_volume_boot', 'ramdisk_boot']

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

    @staticmethod
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

        mode = deploy_utils.rescue_or_deploy_mode(node)
        params_to_check = KERNEL_RAMDISK_LABELS[mode]

        deploy_info = {option: d_info.get(option)
                       for option in params_to_check}

        if not any(deploy_info.values()):
            # NOTE(dtantsur): avoid situation when e.g. deploy_kernel comes
            # from driver_info but deploy_ramdisk comes from configuration,
            # since it's a sign of a potential operator's mistake.
            deploy_info = {k: getattr(CONF.conductor, k)
                           for k in params_to_check}

        error_msg = _("Error validating Redfish virtual media. Some "
                      "parameters were missing in node's driver_info")

        deploy_utils.check_for_missing_params(deploy_info, error_msg)

        deploy_info.update(
            {option: d_info.get(option, getattr(CONF.conductor, option, None))
             for option in OPTIONAL_PROPERTIES})

        deploy_info.update(redfish_utils.parse_driver_info(node))

        return deploy_info

    @staticmethod
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

    @classmethod
    def _parse_deploy_info(cls, node):
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
        deploy_info.update(cls._parse_driver_info(node))
        deploy_info.update(cls._parse_instance_info(node))

        return deploy_info

    @staticmethod
    def _append_filename_param(url, filename):
        """Append 'filename=<file>' parameter to given URL.

        Some BMCs seem to validate boot image URL requiring the URL to end
        with something resembling ISO image file name.

        This function tries to add, hopefully, meaningless 'filename'
        parameter to URL's query string in hope to make the entire boot image
        URL looking more convincing to the BMC.

        However, `url` with fragments might not get cured by this hack.

        :param url: a URL to work on
        :param filename: name of the file to append to the URL
        :returns: original URL with 'filename' parameter appended
        """
        parsed_url = urlparse.urlparse(url)
        parsed_qs = urlparse.parse_qsl(parsed_url.query)

        has_filename = [x for x in parsed_qs if x[0].lower() == 'filename']
        if has_filename:
            return url

        parsed_qs.append(('filename', filename))
        parsed_url = list(parsed_url)
        parsed_url[4] = urlparse.urlencode(parsed_qs)

        return urlparse.urlunparse(parsed_url)

    @classmethod
    def _publish_image(cls, image_file, object_name):
        """Make image file downloadable.

        Depending on ironic settings, pushes given file into Swift or copies
        it over to local HTTP server's document root and returns publicly
        accessible URL leading to the given file.

        :param image_file: path to file to publish
        :param object_name: name of the published file
        :return: a URL to download published file
        """

        if CONF.redfish.use_swift:
            container = CONF.redfish.swift_container
            timeout = CONF.redfish.swift_object_expiry_timeout

            object_headers = {'X-Delete-After': str(timeout)}

            swift_api = swift.SwiftAPI()

            swift_api.create_object(container, object_name, image_file,
                                    object_headers=object_headers)

            image_url = swift_api.get_temp_url(container, object_name, timeout)

        else:
            public_dir = os.path.join(CONF.deploy.http_root, cls.IMAGE_SUBDIR)

            if not os.path.exists(public_dir):
                os.mkdir(public_dir, 0x755)

            published_file = os.path.join(public_dir, object_name)

            try:
                os.link(image_file, published_file)

            except OSError as exc:
                LOG.debug(
                    "Could not hardlink image file %(image)s to public "
                    "location %(public)s (will copy it over): "
                    "%(error)s", {'image': image_file,
                                  'public': published_file,
                                  'error': exc})

                shutil.copyfile(image_file, published_file)

            image_url = os.path.join(
                CONF.deploy.http_url, cls.IMAGE_SUBDIR, object_name)

        image_url = cls._append_filename_param(
            image_url, os.path.basename(image_file))

        return image_url

    @classmethod
    def _unpublish_image(cls, object_name):
        """Withdraw the image previously made downloadable.

        Depending on ironic settings, removes previously published file
        from where it has been published - Swift or local HTTP server's
        document root.

        :param object_name: name of the published file (optional)
        """
        if CONF.redfish.use_swift:
            container = CONF.redfish.swift_container

            swift_api = swift.SwiftAPI()

            LOG.debug("Cleaning up image %(name)s from Swift container "
                      "%(container)s", {'name': object_name,
                                        'container': container})

            try:
                swift_api.delete_object(container, object_name)

            except exception.SwiftOperationError as exc:
                LOG.warning("Failed to clean up image %(image)s. Error: "
                            "%(error)s.", {'image': object_name,
                                           'error': exc})

        else:
            published_file = os.path.join(
                CONF.deploy.http_root, cls.IMAGE_SUBDIR, object_name)

            ironic_utils.unlink_without_raise(published_file)

    @staticmethod
    def _get_floppy_image_name(node):
        """Returns the floppy image name for a given node.

        :param node: the node for which image name is to be provided.
        """
        return "image-%s" % node.uuid

    @classmethod
    def _cleanup_floppy_image(cls, task):
        """Deletes the floppy image if it was created for the node.

        :param task: an ironic node object.
        """
        floppy_object_name = cls._get_floppy_image_name(task.node)

        cls._unpublish_image(floppy_object_name)

    @classmethod
    def _prepare_floppy_image(cls, task, params=None):
        """Prepares the floppy image for passing the parameters.

        This method prepares a temporary VFAT filesystem image and adds
        a file into the image which contains parameters to be passed to
        the ramdisk. Then this method uploads built image to Swift
        '[redfish]swift_container', setting it to auto expire after
        '[redfish]swift_object_expiry_timeout' seconds. Finally, a
        temporary Swift URL is returned addressing Swift object just
        created.

        :param task: a TaskManager instance containing the node to act on.
        :param params: a dictionary containing 'parameter name'->'value'
            mapping to be passed to deploy or rescue image via floppy image.
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: SwiftOperationError, if any operation with Swift fails.
        :returns: image URL for the floppy image.
        """
        object_name = cls._get_floppy_image_name(task.node)

        LOG.debug("Trying to create floppy image for node "
                  "%(node)s", {'node': task.node.uuid})

        with tempfile.NamedTemporaryFile(
                dir=CONF.tempdir, suffix='.img') as vfat_image_tmpfile_obj:

            vfat_image_tmpfile = vfat_image_tmpfile_obj.name
            images.create_vfat_image(vfat_image_tmpfile, parameters=params)

            image_url = cls._publish_image(vfat_image_tmpfile, object_name)

        LOG.debug("Created floppy image %(name)s in Swift for node %(node)s, "
                  "exposed as temporary URL "
                  "%(url)s", {'node': task.node.uuid,
                              'name': object_name,
                              'url': image_url})

        return image_url

    @staticmethod
    def _get_iso_image_name(node):
        """Returns the boot iso image name for a given node.

        :param node: the node for which image name is to be provided.
        """
        return "boot-%s" % node.uuid

    @classmethod
    def _cleanup_iso_image(cls, task):
        """Deletes the ISO if it was created for the instance.

        :param task: an ironic node object.
        """
        iso_object_name = cls._get_iso_image_name(task.node)

        cls._unpublish_image(iso_object_name)

    @classmethod
    def _prepare_iso_image(cls, task, kernel_href, ramdisk_href,
                           bootloader_href=None, root_uuid=None, params=None):
        """Prepare an ISO to boot the node.

        Build bootable ISO out of `kernel_href` and `ramdisk_href` (and
        `bootloader` if it's UEFI boot), then push built image up to Swift and
        return a temporary URL.

        :param task: a TaskManager instance containing the node to act on.
        :param kernel_href: URL or Glance UUID of the kernel to use
        :param ramdisk_href: URL or Glance UUID of the ramdisk to use
        :param bootloader_href: URL or Glance UUID of the EFI bootloader
             image to use when creating UEFI bootbable ISO
        :param root_uuid: optional uuid of the root partition.
        :param params: a dictionary containing 'parameter name'->'value'
            mapping to be passed to kernel command line.
        :returns: bootable ISO HTTP URL.
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        :raises: ImageCreationFailed, if creating ISO image failed.
        """
        if not kernel_href or not ramdisk_href:
            raise exception.InvalidParameterValue(_(
                "Unable to find kernel or ramdisk for "
                "building ISO for %(node)s") %
                {'node': task.node.uuid})

        i_info = task.node.instance_info

        if deploy_utils.get_boot_option(task.node) == "ramdisk":
            kernel_params = "root=/dev/ram0 text "
            kernel_params += i_info.get("ramdisk_kernel_arguments", "")

        else:
            kernel_params = i_info.get(
                'kernel_append_params', CONF.redfish.kernel_append_params)

        if params:
            kernel_params = ' '.join(
                (kernel_params, ' '.join(
                    '%s=%s' % kv for kv in params.items())))

        boot_mode = boot_mode_utils.get_boot_mode_for_deploy(task.node)

        LOG.debug("Trying to create %(boot_mode)s ISO image for node %(node)s "
                  "with kernel %(kernel_href)s, ramdisk %(ramdisk_href)s, "
                  "bootloader %(bootloader_href)s and kernel params %(params)s"
                  "", {'node': task.node.uuid,
                       'boot_mode': boot_mode,
                       'kernel_href': kernel_href,
                       'ramdisk_href': ramdisk_href,
                       'bootloader_href': bootloader_href,
                       'params': kernel_params})

        with tempfile.NamedTemporaryFile(
                dir=CONF.tempdir, suffix='.iso') as fileobj:
            boot_iso_tmp_file = fileobj.name
            images.create_boot_iso(
                task.context, boot_iso_tmp_file,
                kernel_href, ramdisk_href,
                esp_image_href=bootloader_href,
                root_uuid=root_uuid,
                kernel_params=kernel_params,
                boot_mode=boot_mode)

            iso_object_name = cls._get_iso_image_name(task.node)

            image_url = cls._publish_image(boot_iso_tmp_file, iso_object_name)

        LOG.debug("Created ISO %(name)s in Swift for node %(node)s, exposed "
                  "as temporary URL %(url)s", {'node': task.node.uuid,
                                               'name': iso_object_name,
                                               'url': image_url})

        return image_url

    @classmethod
    def _prepare_deploy_iso(cls, task, params, mode):
        """Prepare deploy or rescue ISO image

        Build bootable ISO out of
        `[driver_info]/deploy_kernel`/`[driver_info]/deploy_ramdisk` or
        `[driver_info]/rescue_kernel`/`[driver_info]/rescue_ramdisk`
        and `[driver_info]/bootloader`, then push built image up to Glance
        and return temporary Swift URL to the image.

        :param task: a TaskManager instance containing the node to act on.
        :param params: a dictionary containing 'parameter name'->'value'
            mapping to be passed to kernel command line.
        :param mode: either 'deploy' or 'rescue'.
        :returns: bootable ISO HTTP URL.
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        :raises: ImageCreationFailed, if creating ISO image failed.
        """
        node = task.node

        d_info = cls._parse_driver_info(node)

        kernel_href = d_info.get('%s_kernel' % mode)
        ramdisk_href = d_info.get('%s_ramdisk' % mode)
        bootloader_href = d_info.get('bootloader')

        return cls._prepare_iso_image(
            task, kernel_href, ramdisk_href, bootloader_href, params=params)

    @classmethod
    def _prepare_boot_iso(cls, task, root_uuid=None):
        """Prepare boot ISO image

        Build bootable ISO out of `[instance_info]/kernel`,
        `[instance_info]/ramdisk` and `[driver_info]/bootloader` if present.
        Otherwise, read `kernel_id` and `ramdisk_id` from
        `[instance_info]/image_source` Glance image metadata.

        Push produced ISO image up to Glance and return temporary Swift
        URL to the image.

        :param task: a TaskManager instance containing the node to act on.
        :returns: bootable ISO HTTP URL.
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        :raises: ImageCreationFailed, if creating ISO image failed.
        """
        node = task.node

        d_info = cls._parse_deploy_info(node)

        kernel_href = node.instance_info.get('kernel')
        ramdisk_href = node.instance_info.get('ramdisk')

        if not kernel_href or not ramdisk_href:

            image_href = d_info['image_source']

            image_properties = (
                images.get_image_properties(
                    task.context, image_href, ['kernel_id', 'ramdisk_id']))

            if not kernel_href:
                kernel_href = image_properties.get('kernel_id')

            if not ramdisk_href:
                ramdisk_href = image_properties.get('ramdisk_id')

        if not kernel_href or not ramdisk_href:
            raise exception.InvalidParameterValue(_(
                "Unable to find kernel or ramdisk for "
                "to generate boot ISO for %(node)s") %
                {'node': task.node.uuid})

        bootloader_href = d_info.get('bootloader')

        return cls._prepare_iso_image(
            task, kernel_href, ramdisk_href, bootloader_href,
            root_uuid=root_uuid)

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return REQUIRED_PROPERTIES

    @classmethod
    def _validate_driver_info(cls, task):
        """Validate the prerequisites for virtual media based boot.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any parameters are incorrect
        :raises: MissingParameterValue if some mandatory information
            is missing on the node
        """
        node = task.node

        cls._parse_driver_info(node)

    @classmethod
    def _validate_instance_info(cls, task):
        """Validate instance image information for the task's node.

        This method validates whether the 'instance_info' property of the
        supplied node contains the required information for this driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if any parameters are incorrect
        :raises: MissingParameterValue if some mandatory information
            is missing on the node
        """
        node = task.node

        d_info = cls._parse_deploy_info(node)

        if node.driver_internal_info.get('is_whole_disk_image'):
            props = []

        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']

        else:
            props = ['kernel', 'ramdisk']

        deploy_utils.validate_image_properties(task.context, d_info, props)

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

        if task.driver.storage.should_write_image(task):
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
        # NOTE(TheJulia): If this method is being called by something
        # aside from deployment, clean and rescue, such as conductor takeover,
        # we should treat this as a no-op and move on otherwise we would
        # modify the state of the node due to virtual media operations.
        if node.provision_state not in (states.DEPLOYING,
                                        states.CLEANING,
                                        states.RESCUING,
                                        states.INSPECTING):
            return

        # NOTE(TheJulia): Since we're deploying, cleaning, or rescuing,
        # with virtual media boot, we should generate a token!
        manager_utils.add_secret_token(node, pregenerated=True)
        node.save()
        ramdisk_params['ipa-agent-token'] = \
            node.driver_internal_info['agent_secret_token']

        manager_utils.node_power_action(task, states.POWER_OFF)

        d_info = self._parse_driver_info(node)

        config_via_floppy = d_info.get('config_via_floppy')

        deploy_nic_mac = deploy_utils.get_single_nic_with_vif_port_id(task)
        ramdisk_params['BOOTIF'] = deploy_nic_mac
        if CONF.debug and 'ipa-debug' not in ramdisk_params:
            ramdisk_params['ipa-debug'] = '1'

        if config_via_floppy:

            if self._has_vmedia_device(task, sushy.VIRTUAL_MEDIA_FLOPPY):
                # NOTE (etingof): IPA will read the diskette only if
                # we tell it to
                ramdisk_params['boot_method'] = 'vmedia'

                floppy_ref = self._prepare_floppy_image(
                    task, params=ramdisk_params)

                self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_FLOPPY)
                self._insert_vmedia(
                    task, floppy_ref, sushy.VIRTUAL_MEDIA_FLOPPY)

                LOG.debug('Inserted virtual floppy with configuration for '
                          'node %(node)s', {'node': task.node.uuid})

            else:
                LOG.warning('Config via floppy is requested, but '
                            'Floppy drive is not available on node '
                            '%(node)s', {'node': task.node.uuid})

        mode = deploy_utils.rescue_or_deploy_mode(node)

        iso_ref = self._prepare_deploy_iso(task, ramdisk_params, mode)

        self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)
        self._insert_vmedia(task, iso_ref, sushy.VIRTUAL_MEDIA_CD)

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
        node = task.node

        d_info = self._parse_driver_info(node)

        config_via_floppy = d_info.get('config_via_floppy')

        LOG.debug("Cleaning up deploy boot for "
                  "%(node)s", {'node': task.node.uuid})

        self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)
        self._cleanup_iso_image(task)

        if (config_via_floppy and
                self._has_vmedia_device(task, sushy.VIRTUAL_MEDIA_FLOPPY)):
            self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_FLOPPY)
            self._cleanup_floppy_image(task)

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

        boot_option = deploy_utils.get_boot_option(node)

        self.clean_up_instance(task)
        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        if boot_option == "local" or iwdi:
            self._set_boot_device(
                task, boot_devices.DISK, persistent=True)

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

                self._set_boot_device(
                    task, boot_devices.DISK, persistent=True)

                return

            params.update(root_uuid=root_uuid)

        iso_ref = self._prepare_boot_iso(task, **params)

        self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)
        self._insert_vmedia(task, iso_ref, sushy.VIRTUAL_MEDIA_CD)

        boot_mode_utils.sync_boot_mode(task)

        self._set_boot_device(
            task, boot_devices.CDROM, persistent=True)

        LOG.debug("Node %(node)s is set to permanently boot from "
                  "%(device)s", {'node': task.node.uuid,
                                 'device': boot_devices.CDROM})

    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the environment that was setup for booting
        the instance.

        :param task: A task from TaskManager.
        :returns: None
        """
        LOG.debug("Cleaning up instance boot for "
                  "%(node)s", {'node': task.node.uuid})

        self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)
        d_info = task.node.driver_info
        config_via_floppy = d_info.get('config_via_floppy')
        if config_via_floppy:
            self._eject_vmedia(task, sushy.VIRTUAL_MEDIA_FLOPPY)

        self._cleanup_iso_image(task)

    @staticmethod
    def _insert_vmedia(task, boot_url, boot_device):
        """Insert bootable ISO image into virtual CD or DVD

        :param task: A task from TaskManager.
        :param boot_url: URL to a bootable ISO image
        :param boot_device: sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
            `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY`
        :raises: InvalidParameterValue, if no suitable virtual CD or DVD is
            found on the node.
        """
        system = redfish_utils.get_system(task.node)

        for manager in system.managers:
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

                v_media.insert_media(boot_url, inserted=True,
                                     write_protected=True)

                LOG.info("Inserted boot media %(boot_url)s into "
                         "%(boot_device)s for node "
                         "%(node)s", {'node': task.node.uuid,
                                      'boot_url': boot_url,
                                      'boot_device': boot_device})
                return

        raise exception.InvalidParameterValue(
            _('No suitable virtual media device found'))

    @staticmethod
    def _eject_vmedia(task, boot_device=None):
        """Eject virtual CDs and DVDs

        :param task: A task from TaskManager.
        :param boot_device: sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
            `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY` or `None` to
            eject everything (default).
        :raises: InvalidParameterValue, if no suitable virtual CD or DVD is
            found on the node.
        """
        system = redfish_utils.get_system(task.node)

        for manager in system.managers:
            for v_media in manager.virtual_media.get_members():
                if boot_device and boot_device not in v_media.media_types:
                    continue

                inserted = v_media.inserted

                if inserted:
                    v_media.eject_media()

                LOG.info("Boot media is%(already)s ejected from "
                         "%(boot_device)s for node %(node)s"
                         "", {'node': task.node.uuid,
                              'already': '' if inserted else ' already',
                              'boot_device': v_media.name})

    @staticmethod
    def _has_vmedia_device(task, boot_device):
        """Indicate if device exists at any of the managers

        :param task: A task from TaskManager.
        :param boot_device: sushy boot device e.g. `VIRTUAL_MEDIA_CD`,
            `VIRTUAL_MEDIA_DVD` or `VIRTUAL_MEDIA_FLOPPY`.
        """
        system = redfish_utils.get_system(task.node)

        for manager in system.managers:
            for v_media in manager.virtual_media.get_members():
                if boot_device in v_media.media_types:
                    return True

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
