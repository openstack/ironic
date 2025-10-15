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

import base64
import functools
import gzip
import json
import os
import shutil
import tempfile
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_publisher
from ironic.common import images
from ironic.common import states
from ironic.common import utils
from ironic.conf import CONF
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils

LOG = log.getLogger(__name__)


class ImageHandler(object):

    def __init__(self, driver):
        self.update_driver_config(driver)

    def update_driver_config(self, driver):
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
                "kernel_params": CONF.ilo.kernel_append_params
            },
            "ilo": {
                "swift_enabled": not CONF.ilo.use_web_server_for_images,
                "container": CONF.ilo.swift_ilo_container,
                "timeout": CONF.ilo.swift_object_expiry_timeout,
                "image_subdir": "ilo",
                "file_permission": CONF.ilo.file_permission,
                "kernel_params": CONF.ilo.kernel_append_params
            },
        }

        if driver not in _SWIFT_MAP:
            raise exception.UnsupportedDriverExtension(
                _("Publishing images is not supported for driver %s") % driver)

        if _SWIFT_MAP[driver].get("swift_enabled"):
            self._publisher = image_publisher.SwiftPublisher(
                container=_SWIFT_MAP[driver].get("container"),
                delete_after=_SWIFT_MAP[driver].get("timeout"))
        else:
            self._publisher = image_publisher.LocalPublisher(
                image_subdir=_SWIFT_MAP[driver].get("image_subdir"),
                file_permission=_SWIFT_MAP[driver].get("file_permission"))

        # To get the kernel parameters
        self.kernel_params = _SWIFT_MAP[driver].get("kernel_params")

    def unpublish_image(self, object_name):
        """Withdraw the image previously made downloadable.

        Depending on ironic settings, removes previously published file
        from where it has been published - Swift or local HTTP server's
        document root.

        :param object_name: name of the published file (optional)
        """
        self._publisher.unpublish(object_name)

    @classmethod
    def unpublish_image_for_node(cls, node, prefix='', suffix=''):
        """Withdraw the image previously made downloadable.

        Depending on ironic settings, removes previously published file
        from where it has been published - Swift or local HTTP server's
        document root.

        :param node: the node for which image was published.
        :param prefix: object name prefix.
        :param suffix: object name suffix.
        """
        name = _get_name(node, prefix=prefix, suffix=suffix)
        cls(node.driver).unpublish_image(name)
        LOG.debug('Removed image %(name)s for node %(node)s',
                  {'node': node.uuid, 'name': name})

    def publish_image(self, image_file, object_name, node_http_url=None):
        """Make image file downloadable.

        Depending on ironic settings, pushes given file into Swift or copies
        it over to local HTTP server's document root and returns publicly
        accessible URL leading to the given file.

        :param image_file: path to file to publish
        :param object_name: name of the published file
        :param node_http_url: a url to be used to publish the image. If set,
                              the values from external_http_url and http_url
                              from CONF.deploy won't be used.
        :return: a URL to download published file
        """
        if node_http_url:
            self._publisher.root_url = node_http_url
        return self._publisher.publish(image_file, object_name)


@image_cache.cleanup(priority=75)
class ISOImageCache(image_cache.ImageCache):

    def __init__(self):
        master_path = CONF.deploy.iso_master_path or None
        super(self.__class__, self).__init__(
            master_path,
            # MiB -> B
            cache_size=CONF.deploy.iso_cache_size * 1024 * 1024,
            # min -> sec
            cache_ttl=CONF.deploy.iso_cache_ttl * 60,
            # disable image format inspection and safety checks for ISO
            disable_validation=True, force_raw=False)


def _get_name(node, prefix='', suffix=''):
    """Get an object name for a given node.

    :param node: the node for which image name is to be provided.
    """
    if prefix:
        name = "%s-%s" % (prefix, node.uuid)
    else:
        name = node.uuid
    return name + suffix


def cleanup_iso_image(task):
    """Deletes the ISO if it was created for the instance.

    :param task: A task from TaskManager.
    """
    ImageHandler.unpublish_image_for_node(task.node, prefix='boot',
                                          suffix='.iso')


def override_api_url(params):
    if not CONF.deploy.external_callback_url:
        return params

    params = params or {}
    params[deploy_utils.IPA_URL_PARAM_NAME] = \
        CONF.deploy.external_callback_url.rstrip('/')
    return params


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
    object_name = _get_name(task.node, prefix='image', suffix='.img')
    params = override_api_url(params)

    LOG.debug("Trying to create floppy image for node "
              "%(node)s", {'node': task.node.uuid})

    with tempfile.NamedTemporaryFile(
            dir=CONF.tempdir, suffix='.img') as vfat_image_tmpfile_obj:

        vfat_image_tmpfile = vfat_image_tmpfile_obj.name
        images.create_vfat_image(vfat_image_tmpfile, fs_size_kib=1440,
                                 parameters=params)

        img_handler = ImageHandler(task.node.driver)
        node_http_url = task.node.driver_info.get("external_http_url")
        image_url = img_handler.publish_image(vfat_image_tmpfile, object_name,
                                              node_http_url)

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
    ImageHandler.unpublish_image_for_node(task.node, prefix='image',
                                          suffix='.img')


def prepare_configdrive_image(task, content):
    """Prepare an image with configdrive.

    Decodes base64 contents and writes it into a disk image that can be
    attached e.g. to a virtual USB device. Images stored in Swift are
    downloaded first.

    :param task: a TaskManager instance containing the node to act on.
    :param content: Config drive as a base64-encoded string.
    :raises: ImageCreationFailed, if it failed while creating the image.
    :raises: SwiftOperationError, if any operation with Swift fails.
    :returns: image URL for the image.
    """
    with tempfile.TemporaryFile(dir=CONF.tempdir) as comp_tmpfile_obj:
        if '://' in content:
            with tempfile.NamedTemporaryFile(dir=CONF.tempdir) as tmpfile2:
                images.fetch_into(task.context, content, tmpfile2)
                tmpfile2.flush()

                if utils.file_mime_type(tmpfile2.name) == "text/plain":
                    tmpfile2.seek(0)
                    base64.decode(tmpfile2, comp_tmpfile_obj)
                else:
                    # A binary image, use it as it is.
                    return prepare_disk_image(task, tmpfile2.name,
                                              prefix='configdrive')
        else:
            comp_tmpfile_obj.write(base64.b64decode(content))
        comp_tmpfile_obj.seek(0)

        gz = gzip.GzipFile(fileobj=comp_tmpfile_obj, mode='rb')
        with tempfile.NamedTemporaryFile(
                dir=CONF.tempdir, suffix='.img') as image_tmpfile_obj:
            shutil.copyfileobj(gz, image_tmpfile_obj)
            image_tmpfile_obj.flush()
            return prepare_disk_image(task, image_tmpfile_obj.name,
                                      prefix='configdrive')


def prepare_disk_image(task, content, prefix=None):
    """Prepare an image with the given content.

    If content is already an HTTP URL, return it unchanged.

    :param task: a TaskManager instance containing the node to act on.
    :param content: Content as a string with a file name or bytes with
        contents.
    :param prefix: Prefix to use for the object name.
    :raises: ImageCreationFailed, if it failed while creating the image.
    :raises: SwiftOperationError, if any operation with Swift fails.
    :returns: image URL for the image.
    """
    object_name = _get_name(task.node, prefix=prefix)

    LOG.debug("Creating a disk image for node %s", task.node.uuid)

    img_handler = ImageHandler(task.node.driver)
    if isinstance(content, str):
        image_url = img_handler.publish_image(content, object_name)
    else:
        with tempfile.NamedTemporaryFile(
                dir=CONF.tempdir, suffix='.img') as image_tmpfile_obj:
            image_tmpfile_obj.write(content)
            image_tmpfile_obj.flush()

            image_tmpfile = image_tmpfile_obj.name
            image_url = img_handler.publish_image(image_tmpfile, object_name)

    LOG.debug("Created a disk image %(name)s for node %(node)s, "
              "exposed as URL %(url)s", {'node': task.node.uuid,
                                         'name': object_name,
                                         'url': image_url})

    return image_url


def cleanup_disk_image(task, prefix=None):
    """Deletes the image if it was created for the node.

    :param task: an ironic node object.
    :param prefix: Prefix to use for the object name.
    """
    ImageHandler.unpublish_image_for_node(task.node, prefix=prefix)


# FIXME(dtantsur): file_name is not node-specific, we should probably replace
# it with a prefix/suffix pair and pass to _get_name
def prepare_remote_image(task, image_url, file_name='boot.iso',
                         download_source='local', cache=None):
    """Generic function for publishing remote images.

    Given the image provided by the user, generate a URL to pass to the BMC
    or a remote agent.

    :param task: TaskManager instance.
    :param image_url: The original URL or a glance UUID.
    :param file_name: File name to use when publishing.
    :param download_source: How the image will be published:
        'http' (via a plain HTTP link, preverving remote links),
        'local' (via the local HTTP server even if the remote link is HTTP),
        'swift' (same as 'http', but Glance images are published via Swift
        temporary URLs).
    :param cache: Image cache to use. Defaults to the ISO image cache.
    :return: The new URL (possibly the same as the old one).
    """
    scheme = urlparse.urlparse(image_url).scheme.lower()
    if scheme == 'swift':
        # FIXME(dtantsur): iLO supports swift: scheme. In the long run we
        # should support it for all boot interfaces by using temporary
        # URLs. Until it's done, return image_url as it is.
        return image_url

    if (download_source == 'swift'
            and service_utils.is_glance_image(image_url)):
        image_url = (
            images.get_temp_url_for_glance_image(task.context, image_url))
        # get_temp_url_for_glance_image return an HTTP (or HTTPS - doesn't
        # matter here) image.
        scheme = 'http'

    if download_source != 'local':
        if scheme in ('http', 'https'):
            return image_url
        LOG.debug("image_download_source set to %(download_source)s but "
                  "the image is not an HTTP URL: %(image_url)s",
                  {"image_url": image_url, "download_source": download_source})

    img_handler = ImageHandler(task.node.driver)
    if cache is None:
        cache = ISOImageCache()

    with tempfile.TemporaryDirectory(dir=CONF.tempdir) as temp_dir:
        tmp_file = os.path.join(temp_dir, file_name)
        cache.fetch_image(image_url, tmp_file,
                          ctx=task.context, force_raw=False)
        node_http_url = task.node.driver_info.get("external_http_url")
        return img_handler.publish_image(tmp_file, file_name, node_http_url)


def cleanup_remote_image(task, file_name):
    """Cleanup image created via prepare_remote_image."""
    ImageHandler(task.node.driver).unpublish_image(file_name)


def _prepare_iso_image(task, kernel_href, ramdisk_href,
                       bootloader_href=None, root_uuid=None, params=None,
                       base_iso=None, inject_files=None):
    """Prepare an ISO to boot the node.

    Build bootable ISO out of `kernel_href` and `ramdisk_href` (and
    `bootloader` if it's UEFI boot), then push built image up to Swift and
    return a temporary URL.

    :param task: a TaskManager instance containing the node to act on.
    :param kernel_href: URL or Glance UUID of the kernel to use
    :param ramdisk_href: URL or Glance UUID of the ramdisk to use
    :param bootloader_href: URL or Glance UUID of the EFI bootloader
         image to use when creating UEFI bootable ISO
    :param root_uuid: optional uuid of the root partition.
    :param params: a dictionary containing 'parameter name'->'value'
        mapping to be passed to kernel command line.
    :param inject_files: Mapping of local source file paths to their location
        on the final ISO image.
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

    i_info = task.node.instance_info
    is_ramdisk_boot = (
        task.node.provision_state == states.DEPLOYING
        and deploy_utils.get_boot_option(task.node) == 'ramdisk'
    )

    if is_ramdisk_boot:
        download_source = (i_info.get('ramdisk_image_download_source')
                           or CONF.deploy.ramdisk_image_download_source)
    else:
        download_source = CONF.deploy.ramdisk_image_download_source

    boot_mode = boot_mode_utils.get_boot_mode(task.node)
    iso_object_name = _get_name(task.node, prefix='boot', suffix='.iso')

    if base_iso:
        # NOTE(dtantsur): this should be "params or inject_files", but
        # params are always populated in the calling code.
        log_func = LOG.warning if inject_files else LOG.debug
        log_func('Using pre-built %(boot_mode)s ISO %(iso)s for node '
                 '%(node)s, custom configuration will not be available',
                 {'boot_mode': boot_mode, 'node': task.node.uuid,
                  'iso': base_iso})
        return prepare_remote_image(task, base_iso,
                                    file_name=iso_object_name,
                                    download_source=download_source)

    img_handler = ImageHandler(task.node.driver)

    if not is_ramdisk_boot:
        publisher_id = uuidutils.generate_uuid()

    with tempfile.TemporaryDirectory(dir=CONF.tempdir) as boot_file_dir:

        boot_iso_tmp_file = os.path.join(boot_file_dir, 'boot.iso')
        if is_ramdisk_boot:
            kernel_params = "root=/dev/ram0 text "
            kernel_params += i_info.get("ramdisk_kernel_arguments", "")
        else:
            kernel_params = driver_utils.get_kernel_append_params(
                task.node, default=img_handler.kernel_params)

        if not is_ramdisk_boot:
            kernel_params += " ir_pub_id=%s" % publisher_id

        if params:
            kernel_params = ' '.join(
                (kernel_params, ' '.join(
                    ('%s=%s' % kv) if kv[1] is not None else kv[0]
                    for kv in params.items())))

        LOG.debug(
            "Trying to create %(boot_mode)s ISO image for node %(node)s "
            "with kernel %(kernel_href)s, ramdisk %(ramdisk_href)s, "
            "bootloader %(bootloader_href)s and kernel params %(params)s",
            {'node': task.node.uuid,
                'boot_mode': boot_mode,
                'kernel_href': kernel_href,
                'ramdisk_href': ramdisk_href,
                'bootloader_href': bootloader_href,
                'params': kernel_params})

        if is_ramdisk_boot:
            images.create_boot_iso(
                task.context, boot_iso_tmp_file,
                kernel_href, ramdisk_href,
                esp_image_href=bootloader_href,
                root_uuid=root_uuid,
                kernel_params=kernel_params,
                boot_mode=boot_mode,
                inject_files=inject_files)

        else:
            images.create_boot_iso(
                task.context, boot_iso_tmp_file,
                kernel_href, ramdisk_href,
                esp_image_href=bootloader_href,
                root_uuid=root_uuid,
                kernel_params=kernel_params,
                boot_mode=boot_mode,
                inject_files=inject_files,
                publisher_id=publisher_id)

        node_http_url = task.node.driver_info.get("external_http_url")
        image_url = img_handler.publish_image(
            boot_iso_tmp_file, iso_object_name, node_http_url)

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
            if val is not None:
                return val


_TLS_REMOTE_FILE = 'etc/ironic-python-agent/ironic.crt'
_TLS_CONFIG_TEMPLATE = """[DEFAULT]
cafile = /%s
""" % _TLS_REMOTE_FILE


def prepare_deploy_iso(task, params, mode, d_info):
    """Prepare deploy or rescue ISO image

    Build bootable ISO out of
    `[driver_info]/deploy_kernel`/`[driver_info]/deploy_ramdisk` or
    `[driver_info]/rescue_kernel`/`[driver_info]/rescue_ramdisk`
    and `[driver_info]/bootloader`, then push built image up to Glance
    and return temporary Swift URL to the image.

    If network interface supplies network configuration (`network_data`),
    a `network_data.json` will be written into an appropriate location on
    the final ISO.

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
    iso_str = '%s_iso' % mode
    bootloader_str = 'bootloader'

    # Get kernel and ramdisk, respecting architecture-specific parameters
    agent_info = driver_utils.get_agent_kernel_ramdisk(task.node, mode)
    kernel_href = agent_info.get(kernel_str)
    ramdisk_href = agent_info.get(ramdisk_str)
    iso_href = _find_param(iso_str, d_info)

    if not d_info.get('bootloader'):
        d_info['bootloader'] = driver_utils.get_field(
            task.node, 'bootloader', use_conf=True)

    bootloader_href = _find_param(bootloader_str, d_info)

    params = override_api_url(params)

    # TODO(TheJulia): At some point we should support something like
    # boot_iso for the deploy interface, perhaps when we support config
    # injection.
    prepare_iso_image = functools.partial(
        _prepare_iso_image, task, kernel_href, ramdisk_href,
        bootloader_href=bootloader_href, params=params, base_iso=iso_href)

    inject_files = {}
    if CONF.agent.api_ca_file:
        inject_files[CONF.agent.api_ca_file] = _TLS_REMOTE_FILE
        inject_files[_TLS_CONFIG_TEMPLATE.encode('utf-8')] = \
            'etc/ironic-python-agent.d/ironic-tls.conf'

    network_data = task.driver.network.get_node_network_data(task)
    if network_data:
        LOG.debug('Injecting custom network data for node %s',
                  task.node.uuid)
        network_data = json.dumps(network_data, indent=2).encode('utf-8')
        inject_files[network_data] = (
            'openstack/latest/network_data.json'
        )

    return prepare_iso_image(inject_files=inject_files)


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
