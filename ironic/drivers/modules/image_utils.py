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

import functools
import json
import os
import shutil
import tempfile
from urllib import parse as urlparse

from ironic_lib import utils as ironic_utils
from oslo_log import log
from oslo_serialization import base64

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import images
from ironic.common import swift
from ironic.conf import CONF
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils

LOG = log.getLogger(__name__)


class ImageHandler(object):

    _SWIFT_MAP = {
        "redfish": {
            "swift_enabled": CONF.redfish.use_swift,
            "container": CONF.redfish.swift_container,
            "timeout": CONF.redfish.swift_object_expiry_timeout,
            "image_subdir": "redfish",
            "file_permission": CONF.redfish.file_permission,
            "kernel_params": CONF.redfish.kernel_append_params
        },
        "idrac": {
            "swift_enabled": CONF.redfish.use_swift,
            "container": CONF.redfish.swift_container,
            "timeout": CONF.redfish.swift_object_expiry_timeout,
            "image_subdir": "redfish",
            "file_permission": CONF.redfish.file_permission,
            "kernel_params": CONF.redfish.kernel_append_params
        },
        "ilo5": {
            "swift_enabled": not CONF.ilo.use_web_server_for_images,
            "container": CONF.ilo.swift_ilo_container,
            "timeout": CONF.ilo.swift_object_expiry_timeout,
            "image_subdir": "ilo",
            "file_permission": CONF.ilo.file_permission,
            "kernel_params": CONF.pxe.pxe_append_params
        },
        "ilo": {
            "swift_enabled": not CONF.ilo.use_web_server_for_images,
            "container": CONF.ilo.swift_ilo_container,
            "timeout": CONF.ilo.swift_object_expiry_timeout,
            "image_subdir": "ilo",
            "file_permission": CONF.ilo.file_permission,
            "kernel_params": CONF.pxe.pxe_append_params
        },
    }

    def __init__(self, driver):
        self._driver = driver
        self._container = self._SWIFT_MAP[driver].get("container")
        self._timeout = self._SWIFT_MAP[driver].get("timeout")
        self._image_subdir = self._SWIFT_MAP[driver].get("image_subdir")
        self._file_permission = self._SWIFT_MAP[driver].get("file_permission")
        # To get the kernel parameters
        self.kernel_params = self._SWIFT_MAP[driver].get("kernel_params")

    def _is_swift_enabled(self):
        try:
            return self._SWIFT_MAP[self._driver].get("swift_enabled")
        except KeyError:
            return False

    def unpublish_image(self, object_name):
        """Withdraw the image previously made downloadable.

        Depending on ironic settings, removes previously published file
        from where it has been published - Swift or local HTTP server's
        document root.

        :param object_name: name of the published file (optional)
        """
        if self._is_swift_enabled():
            container = self._container

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
                CONF.deploy.http_root, self._image_subdir, object_name)

            ironic_utils.unlink_without_raise(published_file)

    def _append_filename_param(self, url, filename):
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

    def publish_image(self, image_file, object_name):
        """Make image file downloadable.

        Depending on ironic settings, pushes given file into Swift or copies
        it over to local HTTP server's document root and returns publicly
        accessible URL leading to the given file.

        :param image_file: path to file to publish
        :param object_name: name of the published file
        :return: a URL to download published file
        """

        if self._is_swift_enabled():
            container = self._container
            timeout = self._timeout

            object_headers = {'X-Delete-After': str(timeout)}

            swift_api = swift.SwiftAPI()

            swift_api.create_object(container, object_name, image_file,
                                    object_headers=object_headers)

            image_url = swift_api.get_temp_url(container, object_name, timeout)

        else:
            public_dir = os.path.join(CONF.deploy.http_root,
                                      self._image_subdir)

            if not os.path.exists(public_dir):
                os.mkdir(public_dir, 0o755)

            published_file = os.path.join(public_dir, object_name)

            try:
                os.link(image_file, published_file)
                os.chmod(image_file, self._file_permission)

            except OSError as exc:
                LOG.debug(
                    "Could not hardlink image file %(image)s to public "
                    "location %(public)s (will copy it over): "
                    "%(error)s", {'image': image_file,
                                  'public': published_file,
                                  'error': exc})

                shutil.copyfile(image_file, published_file)
                os.chmod(published_file, self._file_permission)

            image_url = os.path.join(
                CONF.deploy.http_url, self._image_subdir, object_name)

        image_url = self._append_filename_param(
            image_url, os.path.basename(image_file))

        return image_url


def _get_floppy_image_name(node):
    """Returns the floppy image name for a given node.

    :param node: the node for which image name is to be provided.
    """
    return "image-%s" % node.uuid


def _get_iso_image_name(node):
    """Returns the boot iso image name for a given node.

    :param node: the node for which image name is to be provided.
    """
    return "boot-%s.iso" % node.uuid


def cleanup_iso_image(task):
    """Deletes the ISO if it was created for the instance.

    :param task: A task from TaskManager.
    """
    iso_object_name = _get_iso_image_name(task.node)
    img_handler = ImageHandler(task.node.driver)

    img_handler.unpublish_image(iso_object_name)


def prepare_floppy_image(task, params=None):
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
    object_name = _get_floppy_image_name(task.node)

    LOG.debug("Trying to create floppy image for node "
              "%(node)s", {'node': task.node.uuid})

    with tempfile.NamedTemporaryFile(
            dir=CONF.tempdir, suffix='.img') as vfat_image_tmpfile_obj:

        vfat_image_tmpfile = vfat_image_tmpfile_obj.name
        images.create_vfat_image(vfat_image_tmpfile, parameters=params)

        img_handler = ImageHandler(task.node.driver)

        image_url = img_handler.publish_image(vfat_image_tmpfile, object_name)

    LOG.debug("Created floppy image %(name)s in Swift for node %(node)s, "
              "exposed as temporary URL "
              "%(url)s", {'node': task.node.uuid,
                          'name': object_name,
                          'url': image_url})

    return image_url


def cleanup_floppy_image(task):
    """Deletes the floppy image if it was created for the node.

    :param task: an ironic node object.
    """
    floppy_object_name = _get_floppy_image_name(task.node)

    img_handler = ImageHandler(task.node.driver)
    img_handler.unpublish_image(floppy_object_name)


def _prepare_iso_image(task, kernel_href, ramdisk_href,
                       bootloader_href=None, configdrive=None,
                       root_uuid=None, params=None, base_iso=None):
    """Prepare an ISO to boot the node.

    Build bootable ISO out of `kernel_href` and `ramdisk_href` (and
    `bootloader` if it's UEFI boot), then push built image up to Swift and
    return a temporary URL.

    If `configdrive` is specified it will be eventually written onto
    the boot ISO image.

    :param task: a TaskManager instance containing the node to act on.
    :param kernel_href: URL or Glance UUID of the kernel to use
    :param ramdisk_href: URL or Glance UUID of the ramdisk to use
    :param bootloader_href: URL or Glance UUID of the EFI bootloader
         image to use when creating UEFI bootbable ISO
    :param configdrive: URL to or a compressed blob of a ISO9660 or
        FAT-formatted OpenStack config drive image. This image will be
        written onto the built ISO image. Optional.
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
    if (not kernel_href or not ramdisk_href) and not base_iso:
        raise exception.InvalidParameterValue(_(
            "Unable to find kernel, ramdisk for "
            "building ISO, or explicit ISO for %(node)s") %
            {'node': task.node.uuid})

    img_handler = ImageHandler(task.node.driver)
    k_param = img_handler.kernel_params

    i_info = task.node.instance_info

    # NOTE(TheJulia): Until we support modifying a base iso, most of
    # this logic actually does nothing in the end. But it should!
    if deploy_utils.get_boot_option(task.node) == "ramdisk":
        if not base_iso:
            kernel_params = "root=/dev/ram0 text "
            kernel_params += i_info.get("ramdisk_kernel_arguments", "")
        else:
            kernel_params = None

    else:
        kernel_params = i_info.get('kernel_append_params', k_param)

    if params and not base_iso:
        kernel_params = ' '.join(
            (kernel_params, ' '.join(
                '%s=%s' % kv for kv in params.items())))

    boot_mode = boot_mode_utils.get_boot_mode(task.node)

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
            dir=CONF.tempdir, suffix='.iso') as boot_fileobj:

        with tempfile.NamedTemporaryFile(
                dir=CONF.tempdir, suffix='.img') as cfgdrv_fileobj:

            configdrive_href = configdrive

            # FIXME(TheJulia): This is treated as conditional with
            # a base_iso as the intent, eventually, is to support
            # injection into the supplied image.

            if configdrive and not base_iso:
                parsed_url = urlparse.urlparse(configdrive)
                if not parsed_url.scheme:
                    cfgdrv_blob = base64.decode_as_bytes(configdrive)

                    with open(cfgdrv_fileobj.name, 'wb') as f:
                        f.write(cfgdrv_blob)

                    configdrive_href = urlparse.urlunparse(
                        ('file', '', cfgdrv_fileobj.name, '', '', ''))

                LOG.debug("Built configdrive out of configdrive blob "
                          "for node %(node)s", {'node': task.node.uuid})

            boot_iso_tmp_file = boot_fileobj.name
            images.create_boot_iso(
                task.context, boot_iso_tmp_file,
                kernel_href, ramdisk_href,
                esp_image_href=bootloader_href,
                configdrive_href=configdrive_href,
                root_uuid=root_uuid,
                kernel_params=kernel_params,
                boot_mode=boot_mode,
                base_iso=base_iso)

            iso_object_name = _get_iso_image_name(task.node)

            image_url = img_handler.publish_image(
                boot_iso_tmp_file, iso_object_name)

    LOG.debug("Created ISO %(name)s in object store for node %(node)s, "
              "exposed as temporary URL "
              "%(url)s", {'node': task.node.uuid,
                          'name': iso_object_name,
                          'url': image_url})

    return image_url


def _find_param(param_str, param_dict):
    val = None
    for param_key in param_dict:
        if param_str in param_key:
            val = param_dict.get(param_key)
    return val


def prepare_deploy_iso(task, params, mode, d_info):
    """Prepare deploy or rescue ISO image

    Build bootable ISO out of
    `[driver_info]/deploy_kernel`/`[driver_info]/deploy_ramdisk` or
    `[driver_info]/rescue_kernel`/`[driver_info]/rescue_ramdisk`
    and `[driver_info]/bootloader`, then push built image up to Glance
    and return temporary Swift URL to the image.

    If network interface supplies network configuration (`network_data`),
    a new `configdrive` will be created with `network_data.json` inside,
    and eventually written down onto the boot ISO.

    :param task: a TaskManager instance containing the node to act on.
    :param params: a dictionary containing 'parameter name'->'value'
        mapping to be passed to kernel command line.
    :param mode: either 'deploy' or 'rescue'.
    :param d_info: Deployment information of the node
    :returns: bootable ISO HTTP URL.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    :raises: ImageCreationFailed, if creating ISO image failed.
    """

    kernel_str = '%s_kernel' % mode
    ramdisk_str = '%s_ramdisk' % mode
    bootloader_str = 'bootloader'

    kernel_href = _find_param(kernel_str, d_info)
    ramdisk_href = _find_param(ramdisk_str, d_info)
    bootloader_href = _find_param(bootloader_str, d_info)

    # TODO(TheJulia): At some point we should support something like
    # boot_iso for the deploy interface, perhaps when we support config
    # injection.
    prepare_iso_image = functools.partial(
        _prepare_iso_image, task, kernel_href, ramdisk_href,
        bootloader_href=bootloader_href, params=params)

    network_data = task.driver.network.get_node_network_data(task)
    if network_data:
        with tempfile.NamedTemporaryFile(dir=CONF.tempdir,
                                         suffix='.iso') as metadata_fileobj:

            with open(metadata_fileobj.name, 'w') as f:
                json.dump(network_data, f, indent=2)

            files_info = {
                metadata_fileobj.name: 'openstack/latest/meta'
                                       'data/network_data.json'
            }

            with tempfile.NamedTemporaryFile(
                    dir=CONF.tempdir, suffix='.img') as cfgdrv_fileobj:

                images.create_vfat_image(cfgdrv_fileobj.name, files_info)

                configdrive_href = urlparse.urlunparse(
                    ('file', '', cfgdrv_fileobj.name, '', '', ''))

                LOG.debug("Built configdrive %(name)s out of network data "
                          "for node %(node)s", {'name': configdrive_href,
                                                'node': task.node.uuid})

                return prepare_iso_image(configdrive=configdrive_href)

    return prepare_iso_image()


def prepare_boot_iso(task, d_info, root_uuid=None):
    """Prepare boot ISO image

    Build bootable ISO out of `[instance_info]/kernel`,
    `[instance_info]/ramdisk` and `[driver_info]/bootloader` if present.
    Otherwise, read `kernel_id` and `ramdisk_id` from
    `[instance_info]/image_source` Glance image metadata.

    Push produced ISO image up to Glance and return temporary Swift
    URL to the image.

    :param task: a TaskManager instance containing the node to act on.
    :param d_info: Deployment information of the node
    :param root_uuid: Root UUID
    :returns: bootable ISO HTTP URL.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    :raises: ImageCreationFailed, if creating ISO image failed.
    """
    node = task.node

    kernel_href = node.instance_info.get('kernel')
    ramdisk_href = node.instance_info.get('ramdisk')
    base_iso = node.instance_info.get('boot_iso')

    if (not kernel_href or not ramdisk_href) and not base_iso:

        image_href = d_info['image_source']

        image_properties = (
            images.get_image_properties(
                task.context, image_href, ['kernel_id', 'ramdisk_id']))

        if not kernel_href:
            kernel_href = image_properties.get('kernel_id')

        if not ramdisk_href:
            ramdisk_href = image_properties.get('ramdisk_id')

        if (not kernel_href or not ramdisk_href):
            raise exception.InvalidParameterValue(_(
                "Unable to find kernel or ramdisk for "
                "to generate boot ISO for %(node)s") %
                {'node': task.node.uuid})

    bootloader_str = 'bootloader'
    bootloader_href = _find_param(bootloader_str, d_info)

    return _prepare_iso_image(
        task, kernel_href, ramdisk_href, bootloader_href,
        root_uuid=root_uuid, base_iso=base_iso)
