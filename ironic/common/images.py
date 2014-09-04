# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""
Handling of VM disk images.
"""

import os
import shutil

import jinja2
from oslo.config import cfg

from ironic.common import exception
from ironic.common import i18n
from ironic.common.i18n import _
from ironic.common import image_service as service
from ironic.common import paths
from ironic.common import utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import imageutils
from ironic.openstack.common import log as logging
from ironic.openstack.common import processutils

LOG = logging.getLogger(__name__)

_LE = i18n._LE

image_opts = [
    cfg.BoolOpt('force_raw_images',
                default=True,
                help='Force backing images to raw format.'),
    cfg.StrOpt('isolinux_bin',
                default='/usr/lib/syslinux/isolinux.bin',
                help='Path to isolinux binary file.'),
    cfg.StrOpt('isolinux_config_template',
                default=paths.basedir_def('common/isolinux_config.template'),
                help='Template file for isolinux configuration file.'),
]

CONF = cfg.CONF
CONF.register_opts(image_opts)


def _create_root_fs(root_directory, files_info):
    """Creates a filesystem root in given directory.

    Given a mapping of absolute path of files to their relative paths
    within the filesystem, this method copies the files to their
    destination.

    :param root_directory: the filesystem root directory.
    :param files_info: A dict containing absolute path of file to be copied
        -> relative path within the vfat image. For example,
        {
         '/absolute/path/to/file' -> 'relative/path/within/root'
         ...
        }
    :raises: OSError, if creation of any directory failed.
    :raises: IOError, if copying any of the files failed.
    """
    for src_file, path in files_info.items():
        target_file = os.path.join(root_directory, path)
        dirname = os.path.dirname(target_file)
        if not os.path.exists(dirname):
            os.makedirs(dirname)

        shutil.copyfile(src_file, target_file)


def create_vfat_image(output_file, files_info=None, parameters=None,
                      parameters_file='parameters.txt', fs_size_kib=100):
    """Creates the fat fs image on the desired file.

    This method copies the given files to a root directory (optional),
    writes the parameters specified to the parameters file within the
    root directory (optional), and then creates a vfat image of the root
    directory.

    :param output_file: The path to the file where the fat fs image needs
        to be created.
    :param files_info: A dict containing absolute path of file to be copied
        -> relative path within the vfat image. For example,
        {
         '/absolute/path/to/file' -> 'relative/path/within/root'
         ...
        }
    :param parameters: A dict containing key-value pairs of parameters.
    :param parameters_file: The filename for the parameters file.
    :param fs_size_kib: size of the vfat filesystem in KiB.
    :raises: ImageCreationFailed, if image creation failed while doing any
        of filesystem manipulation activities like creating dirs, mounting,
        creating filesystem, copying files, etc.
    """
    try:
        utils.dd('/dev/zero', output_file, 'count=1', "bs=%dKiB" % fs_size_kib)
    except processutils.ProcessExecutionError as e:
        raise exception.ImageCreationFailed(image_type='vfat', error=e)

    with utils.tempdir() as tmpdir:

        try:
            utils.mkfs('vfat', output_file)
            utils.mount(output_file, tmpdir, '-o', 'umask=0')
        except processutils.ProcessExecutionError as e:
            raise exception.ImageCreationFailed(image_type='vfat', error=e)

        try:
            if files_info:
                _create_root_fs(tmpdir, files_info)

            if parameters:
                parameters_file = os.path.join(tmpdir, parameters_file)
                params_list = ['%(key)s=%(val)s' % {'key': k, 'val': v}
                           for k, v in parameters.items()]
                file_contents = '\n'.join(params_list)
                utils.write_to_file(parameters_file, file_contents)

        except Exception as e:
            LOG.exception(_LE("vfat image creation failed. Error: %s"), e)
            raise exception.ImageCreationFailed(image_type='vfat', error=e)

        finally:
            try:
                utils.umount(tmpdir)
            except processutils.ProcessExecutionError as e:
                raise exception.ImageCreationFailed(image_type='vfat', error=e)


def _generate_isolinux_cfg(kernel_params):
    """Generates a isolinux configuration file.

    Given a given a list of strings containing kernel parameters, this method
    returns the kernel cmdline string.
    :param kernel_params: a list of strings(each element being a string like
        'K=V' or 'K' or combination of them like 'K1=V1 K2 K3=V3') to be added
        as the kernel cmdline.
    :returns: a string containing the contents of the isolinux configuration
        file.
    """
    if not kernel_params:
        kernel_params = []
    kernel_params_str = ' '.join(kernel_params)

    template = CONF.isolinux_config_template
    tmpl_path, tmpl_file = os.path.split(template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    template = env.get_template(tmpl_file)

    options = {'kernel': '/vmlinuz', 'ramdisk': '/initrd',
               'kernel_params': kernel_params_str}

    cfg = template.render(options)
    return cfg


def create_isolinux_image(output_file, kernel, ramdisk, kernel_params=None):
    """Creates an isolinux image on the specified file.

    Copies the provided kernel, ramdisk to a directory, generates the isolinux
    configuration file using the kernel parameters provided, and then generates
    a bootable ISO image.

    :param output_file: the path to the file where the iso image needs to be
        created.
    :param kernel: the kernel to use.
    :param ramdisk: the ramdisk to use.
    :param kernel_params: a list of strings(each element being a string like
        'K=V' or 'K' or combination of them like 'K1=V1,K2,...') to be added
        as the kernel cmdline.
    :raises: ImageCreationFailed, if image creation failed while copying files
        or while running command to generate iso.
    """
    ISOLINUX_BIN = 'isolinux/isolinux.bin'
    ISOLINUX_CFG = 'isolinux/isolinux.cfg'

    with utils.tempdir() as tmpdir:

        files_info = {
                      kernel: 'vmlinuz',
                      ramdisk: 'initrd',
                      CONF.isolinux_bin: ISOLINUX_BIN,
                     }

        try:
            _create_root_fs(tmpdir, files_info)
        except (OSError, IOError) as e:
            LOG.exception(_LE("Creating the filesystem root failed."))
            raise exception.ImageCreationFailed(image_type='iso', error=e)

        cfg = _generate_isolinux_cfg(kernel_params)

        isolinux_cfg = os.path.join(tmpdir, ISOLINUX_CFG)
        utils.write_to_file(isolinux_cfg, cfg)

        try:
            utils.execute('mkisofs', '-r', '-V', "BOOT IMAGE",
                          '-cache-inodes', '-J', '-l', '-no-emul-boot',
                          '-boot-load-size', '4', '-boot-info-table',
                          '-b', ISOLINUX_BIN, '-o', output_file, tmpdir)
        except processutils.ProcessExecutionError as e:
            LOG.exception(_LE("Creating ISO image failed."))
            raise exception.ImageCreationFailed(image_type='iso', error=e)


def qemu_img_info(path):
    """Return an object containing the parsed output from qemu-img info."""
    if not os.path.exists(path):
        return imageutils.QemuImgInfo()

    out, err = utils.execute('env', 'LC_ALL=C', 'LANG=C',
                             'qemu-img', 'info', path)
    return imageutils.QemuImgInfo(out)


def convert_image(source, dest, out_format, run_as_root=False):
    """Convert image to other format."""
    cmd = ('qemu-img', 'convert', '-O', out_format, source, dest)
    utils.execute(*cmd, run_as_root=run_as_root)


def fetch(context, image_href, path, image_service=None):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    if not image_service:
        image_service = service.Service(version=1, context=context)

    with fileutils.remove_path_on_error(path):
        with open(path, "wb") as image_file:
            image_service.download(image_href, image_file)


def fetch_to_raw(context, image_href, path, image_service=None):
    path_tmp = "%s.part" % path
    fetch(context, image_href, path_tmp, image_service)
    image_to_raw(image_href, path, path_tmp)


def image_to_raw(image_href, path, path_tmp):
    with fileutils.remove_path_on_error(path_tmp):
        data = qemu_img_info(path_tmp)

        fmt = data.file_format
        if fmt is None:
            raise exception.ImageUnacceptable(
                    reason=_("'qemu-img info' parsing failed."),
                    image_id=image_href)

        backing_file = data.backing_file
        if backing_file is not None:
            raise exception.ImageUnacceptable(image_id=image_href,
                reason=_("fmt=%(fmt)s backed by: %(backing_file)s") %
                                              {'fmt': fmt,
                                               'backing_file': backing_file})

        if fmt != "raw" and CONF.force_raw_images:
            staged = "%s.converted" % path
            LOG.debug("%(image)s was %(format)s, converting to raw" %
                    {'image': image_href, 'format': fmt})
            with fileutils.remove_path_on_error(staged):
                convert_image(path_tmp, staged, 'raw')
                os.unlink(path_tmp)

                data = qemu_img_info(staged)
                if data.file_format != "raw":
                    raise exception.ImageConvertFailed(image_id=image_href,
                        reason=_("Converted to raw, but format is now %s") %
                                 data.file_format)

                os.rename(staged, path)
        else:
            os.rename(path_tmp, path)


def download_size(context, image_href, image_service=None):
    if not image_service:
        image_service = service.Service(version=1, context=context)
    return image_service.show(image_href)['size']


def converted_size(path):
    """Get size of converted raw image.

    The size of image converted to raw format can be growing up to the virtual
    size of the image.

    :param path: path to the image file.
    :returns: virtual size of the image or 0 if conversion not needed.

    """
    data = qemu_img_info(path)
    if data.file_format == "raw" or not CONF.force_raw_images:
        return 0
    return data.virtual_size


def get_glance_image_property(context, image_uuid, property):
    """Returns the value of a glance image property.

    :param context: context
    :param image_uuid: the UUID of the image in glance
    :param property: the property whose value is required.
    :returns: the value of the property if it exists, otherwise None.
    """
    glance_service = service.Service(version=1, context=context)
    iproperties = glance_service.show(image_uuid)['properties']
    return iproperties.get(property)


def get_temp_url_for_glance_image(context, image_uuid):
    """Returns the tmp url for a glance image.

    :param context: context
    :param image_uuid: the UUID of the image in glance
    :returns: the tmp url for the glance image.
    """
    # Glance API version 2 is required for getting direct_url of the image.
    glance_service = service.Service(version=2, context=context)
    image_properties = glance_service.show(image_uuid)
    LOG.debug('Got image info: %(info)s for image %(image_uuid)s.',
              {'info': image_properties, 'image_uuid': image_uuid})
    return glance_service.swift_temp_url(image_properties)


def create_boot_iso(context, output_filename, kernel_uuid,
        ramdisk_uuid, root_uuid=None, kernel_params=None):
    """Creates a bootable ISO image for a node.

    Given the glance UUID of kernel, ramdisk, root partition's UUID and
    kernel cmdline arguments, this method fetches the kernel, ramdisk from
    glance, and builds a bootable ISO image that can be used to boot up the
    baremetal node.

    :param context: context
    :param output_filename: the absolute path of the output ISO file
    :param kernel_uuid: glance uuid of the kernel to use
    :param ramdisk_uuid: glance uuid of the ramdisk to use
    :param root_uuid: uuid of the root filesystem (optional)
    :param kernel_params: a string containing whitespace separated values
        kernel cmdline arguments of the form K=V or K (optional).
    :raises: ImageCreationFailed, if creating boot ISO failed.
    """
    with utils.tempdir() as tmpdir:
        kernel_path = os.path.join(tmpdir, kernel_uuid)
        ramdisk_path = os.path.join(tmpdir, ramdisk_uuid)
        fetch_to_raw(context, kernel_uuid, kernel_path)
        fetch_to_raw(context, ramdisk_uuid, ramdisk_path)

        params = []
        if root_uuid:
            params.append('root=UUID=%s' % root_uuid)
        if kernel_params:
            params.append(kernel_params)

        create_isolinux_image(output_filename, kernel_path,
                              ramdisk_path, params)
