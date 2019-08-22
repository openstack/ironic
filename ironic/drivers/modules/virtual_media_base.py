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

import tempfile

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import images
from ironic.common import swift
from ironic.conf import CONF
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils

LOG = log.getLogger(__name__)


def get_iso_image_name(node):
    """Returns the boot iso image name for a given node.

    :param node: the node for which image name is to be provided.
    """
    return "boot-%s" % node.uuid


def prepare_iso_image(task, kernel_href, ramdisk_href, deploy_iso_href=None,
                      bootloader_href=None, root_uuid=None,
                      kernel_params=None, timeout=None,
                      use_web_server=False, container=None):
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
        :param kernel_params: a dictionary containing 'parameter name'->'value'
            mapping to be passed to kernel command line.
        :param timeout: swift object expiry timeout
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
        images.create_boot_iso(task.context, boot_iso_tmp_file,
                               kernel_href, ramdisk_href,
                               deploy_iso_href=deploy_iso_href,
                               esp_image_href=bootloader_href,
                               root_uuid=root_uuid,
                               kernel_params=kernel_params,
                               boot_mode=boot_mode)

        iso_object_name = get_iso_image_name(task.node)

        if use_web_server:
            boot_iso_url = (
                deploy_utils.copy_image_to_web_server(boot_iso_tmp_file,
                                                      iso_object_name))
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_iso_created_in_web_server'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            LOG.debug("Created boot_iso %(boot_iso)s for node %(node)s",
                      {'boot_iso': boot_iso_url, 'node': task.node.uuid})
            return boot_iso_url
        else:
            swift_api = swift.SwiftAPI()

            object_headers = None
            if task.node.driver == 'redfish':
                object_headers = {'X-Delete-After': str(timeout)}

            swift_api.create_object(container, iso_object_name,
                                    boot_iso_tmp_file,
                                    object_headers=object_headers)

            LOG.debug("Created ISO %(name)s in Swift for node %(node)s",
                      {'node': task.node.uuid, 'name': iso_object_name})

            if task.node.driver == 'redfish':
                boot_iso_url = swift_api.get_temp_url(
                    container, iso_object_name, timeout)
                return boot_iso_url
            else:
                return 'swift:%s' % iso_object_name


def prepare_deploy_iso(task, params, mode, driver_info,
                       use_web_server=False, container=None):
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
        :param driver_info: a dictionary containing driver_info values.
        :returns: bootable ISO HTTP URL.
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        :raises: ImageCreationFailed, if creating ISO image failed.
    """

    kernel_href = driver_info.get('%s_kernel' % mode)
    ramdisk_href = driver_info.get('%s_ramdisk' % mode)
    bootloader_href = driver_info.get('bootloader')
    timeout = None

    if deploy_utils.get_boot_option(task.node) == "ramdisk":
        i_info = task.node.instance_info
        kernel_params = "root=/dev/ram0 text "
        kernel_params += i_info.get("ramdisk_kernel_arguments", "")
    elif task.node.driver == 'redfish':
        kernel_params = CONF.redfish.kernel_append_params
        timeout = CONF.redfish.swift_object_expiry_timeout
    else:
        kernel_params = CONF.pxe.pxe_append_params

    if params:
        kernel_params = ' '.join(
            (kernel_params, ' '.join(
                '%s=%s' % kv for kv in params.items())))

    return prepare_iso_image(task, kernel_href, ramdisk_href,
                             bootloader_href=bootloader_href,
                             kernel_params=kernel_params, timeout=timeout,
                             use_web_server=use_web_server,
                             container=container)
