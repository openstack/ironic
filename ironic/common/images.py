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
import time

from ironic_lib import disk_utils
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import fileutils
import pycdlib

from ironic.common import exception
from ironic.common.glance_service import service_utils as glance_utils
from ironic.common.i18n import _
from ironic.common import image_service as service
from ironic.common import utils
from ironic.conf import CONF

LOG = logging.getLogger(__name__)


def _create_root_fs(root_directory, files_info):
    """Creates a filesystem root in given directory.

    Given a mapping of absolute path of files to their relative paths
    within the filesystem, this method copies the files to their
    destination.

    :param root_directory: the filesystem root directory.
    :param files_info: A dict containing absolute path of file to be copied
                       or its content as bytes -> relative path within
                       the vfat image. For example::
                        {
                        '/absolute/path/to/file': 'relative/path/within/root',
                        b'{"some": "json"}': 'another/relative/path'
                        ...
                        }
    :raises: OSError, if creation of any directory failed.
    :raises: IOError, if copying any of the files failed.
    """
    for src_file, path in files_info.items():
        LOG.debug('Injecting %(path)s into an ISO from %(source)r',
                  {'path': path, 'source': src_file})
        target_file = os.path.join(root_directory, path)
        dirname = os.path.dirname(target_file)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        if isinstance(src_file, bytes):
            with open(target_file, 'wb') as fp:
                fp.write(src_file)
        else:
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
                       -> relative path within the vfat image. For example::

                        {
                        '/absolute/path/to/file' -> 'relative/path/within/root'
                        ...
                        }
    :param parameters: A dict containing key-value pairs of parameters.
    :param parameters_file: The filename for the parameters file.
    :param fs_size_kib: size of the vfat filesystem in KiB.
    :raises: ImageCreationFailed, if image creation failed while doing any
             of filesystem manipulation activities like creating dirs,
             mounting, creating filesystem, copying files, etc.
    """
    try:
        # TODO(sbaker): use ironic_lib.utils.dd when rootwrap has been removed
        utils.execute('dd', 'if=/dev/zero', 'of=%s' % output_file, 'count=1',
                      'bs=%dKiB' % fs_size_kib)
    except processutils.ProcessExecutionError as e:
        raise exception.ImageCreationFailed(image_type='vfat', error=e)

    with utils.tempdir() as tmpdir:

        try:
            # The label helps ramdisks to find the partition containing
            # the parameters (by using /dev/disk/by-label/ir-vfd-dev).
            # NOTE: FAT filesystem label can be up to 11 characters long.
            # TODO(sbaker): use ironic_lib.utils.mkfs when rootwrap has been
            #              removed
            utils.execute('mkfs', '-t', 'vfat', '-n',
                          'ir-vfd-dev', output_file)
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

            file_list = os.listdir(tmpdir)

            if not file_list:
                return

            file_list = [os.path.join(tmpdir, item) for item in file_list]

            # use mtools to copy the files into the image in a single
            # operation
            utils.execute('mcopy', '-s', *file_list, '-i', output_file, '::')

        except Exception as e:
            LOG.exception("vfat image creation failed. Error: %s", e)
            raise exception.ImageCreationFailed(image_type='vfat', error=e)


def _generate_cfg(kernel_params, template, options):
    """Generates a isolinux or grub configuration file.

    Given a given a list of strings containing kernel parameters, this method
    returns the kernel cmdline string.
    :param kernel_params: a list of strings(each element being a string like
        'K=V' or 'K' or combination of them like 'K1=V1 K2 K3=V3') to be added
        as the kernel cmdline.
    :param template: the path of the config template file.
    :param options: a dictionary of keywords which need to be replaced in
                    template file to generate a proper config file.
    :returns: a string containing the contents of the isolinux configuration
        file.
    """
    options.update({'kernel_params': ' '.join(kernel_params or [])})
    return utils.render_template(template, options)


def _label(files_info):
    """Get a suitable label for the files.

    Returns "config-2" if the openstack metadata is present.
    """
    if any(x.startswith('openstack/') for x in files_info.values()):
        return 'config-2'
    else:
        return 'VMEDIA_BOOT_ISO'


def create_isolinux_image_for_bios(
        output_file, kernel, ramdisk, kernel_params=None, inject_files=None):
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
    :param inject_files: Mapping of local source file paths to their location
        on the final ISO image.
    :raises: ImageCreationFailed, if image creation failed while copying files
        or while running command to generate iso.
    """
    ISOLINUX_BIN = 'isolinux/isolinux.bin'
    ISOLINUX_CFG = 'isolinux/isolinux.cfg'
    LDLINUX_SRC_DIRS = ['/usr/lib/syslinux/modules/bios',
                        '/usr/share/syslinux']
    LDLINUX_BIN = 'isolinux/ldlinux.c32'

    options = {'kernel': '/vmlinuz', 'ramdisk': '/initrd'}

    with utils.tempdir() as tmpdir:
        files_info = {
            kernel: 'vmlinuz',
            ramdisk: 'initrd',
            CONF.isolinux_bin: ISOLINUX_BIN,
        }
        if inject_files:
            files_info.update(inject_files)

        # ldlinux.c32 is required for syslinux 5.0 or later.
        if CONF.ldlinux_c32:
            ldlinux_src = CONF.ldlinux_c32
        else:
            for directory in LDLINUX_SRC_DIRS:
                ldlinux_src = os.path.join(directory, 'ldlinux.c32')
                if os.path.isfile(ldlinux_src):
                    break
            else:
                ldlinux_src = None
        if ldlinux_src:
            files_info[ldlinux_src] = LDLINUX_BIN

        try:
            _create_root_fs(tmpdir, files_info)

        except EnvironmentError as e:
            LOG.exception("Creating the filesystem root failed.")
            raise exception.ImageCreationFailed(image_type='iso', error=e)

        cfg = _generate_cfg(kernel_params,
                            CONF.isolinux_config_template, options)

        isolinux_cfg = os.path.join(tmpdir, ISOLINUX_CFG)
        utils.write_to_file(isolinux_cfg, cfg)

        try:
            utils.execute('mkisofs', '-r', '-V', _label(files_info),
                          '-J', '-l', '-no-emul-boot',
                          '-boot-load-size', '4', '-boot-info-table',
                          '-b', ISOLINUX_BIN, '-o', output_file, tmpdir)
        except processutils.ProcessExecutionError as e:
            LOG.exception("Creating ISO image failed.")
            raise exception.ImageCreationFailed(image_type='iso', error=e)


def create_esp_image_for_uefi(
        output_file, kernel, ramdisk, deploy_iso=None, esp_image=None,
        kernel_params=None, inject_files=None):
    """Creates an ESP image on the specified file.

    Copies the provided kernel, ramdisk and EFI system partition image (ESP) to
    a directory, generates the grub configuration file using kernel parameters
    and then generates a bootable ISO image for UEFI.

    :param output_file: the path to the file where the iso image needs to be
        created.
    :param kernel: the kernel to use.
    :param ramdisk: the ramdisk to use.
    :param deploy_iso: deploy ISO image to extract EFI system partition image
        from. If not specified, the `esp_image` option is required.
    :param esp_image: FAT12/16/32-formatted EFI system partition image
        containing the EFI boot loader (e.g. GRUB2) for each hardware
        architecture to boot. This image will be embedded into the ISO image.
        If not specified, the `deploy_iso` option is required.
    :param kernel_params: a list of strings(each element being a string like
        'K=V' or 'K' or combination of them like 'K1=V1,K2,...') to be added
        as the kernel cmdline.
    :param inject_files: Mapping of local source file paths to their location
        on the final ISO image.
    :raises: ImageCreationFailed, if image creation failed while copying files
        or while running command to generate iso.
    """
    EFIBOOT_LOCATION = 'boot/grub/efiboot.img'

    grub_options = {'linux': '/vmlinuz', 'initrd': '/initrd'}

    with utils.tempdir() as tmpdir:
        files_info = {
            kernel: 'vmlinuz',
            ramdisk: 'initrd',
        }
        if inject_files:
            files_info.update(inject_files)

        with utils.tempdir() as mountdir:
            # Open the deploy iso used to initiate deploy and copy the
            # efiboot.img i.e. boot loader to the current temporary
            # directory.
            if deploy_iso and not esp_image:
                uefi_path_info, e_img_rel_path, grub_rel_path = (
                    _get_deploy_iso_files(deploy_iso, mountdir))

                grub_cfg = os.path.join(tmpdir, grub_rel_path)

            # Use ELF boot loader provided
            elif esp_image and not deploy_iso:
                e_img_rel_path = EFIBOOT_LOCATION
                grub_rel_path = CONF.grub_config_path.lstrip(' ' + os.sep)
                grub_cfg = os.path.join(tmpdir, grub_rel_path)

                # Create an empty grub config file by copying /dev/null.
                # This is to avoid write failures when actual write of
                # config file happens. Write failures are caused if grub
                # config path does not exist on root file system.
                uefi_path_info = {
                    esp_image: e_img_rel_path,
                    '/dev/null': grub_rel_path
                }

            else:
                msg = _('Neither deploy ISO nor ESP image configured or '
                        'both of them configured')
                raise exception.ImageCreationFailed(
                    image_type='iso', error=msg)

            files_info.update(uefi_path_info)

            try:
                _create_root_fs(tmpdir, files_info)

            except EnvironmentError as e:
                LOG.exception("Creating the filesystem root failed.")
                raise exception.ImageCreationFailed(
                    image_type='iso', error=e)

            finally:
                if deploy_iso:
                    shutil.rmtree(mountdir)

        # Generate and copy grub config file.
        grub_conf = _generate_cfg(kernel_params,
                                  CONF.grub_config_template, grub_options)
        utils.write_to_file(grub_cfg, grub_conf)

        # Create the boot_iso.
        try:
            utils.execute('mkisofs', '-r', '-V', _label(files_info),
                          '-l', '-e', e_img_rel_path, '-no-emul-boot',
                          '-o', output_file, tmpdir)

        except processutils.ProcessExecutionError as e:
            LOG.exception("Creating ISO image failed.")
            raise exception.ImageCreationFailed(image_type='iso', error=e)


def fetch_into(context, image_href, image_file):
    # TODO(vish): Improve context handling and add owner and auth data
    #             when it is added to glance.  Right now there is no
    #             auth checking in glance, so we assume that access was
    #             checked before we got here.
    image_service = service.get_image_service(image_href,
                                              context=context)
    LOG.debug("Using %(image_service)s to download image %(image_href)s.",
              {'image_service': image_service.__class__.__name__,
               'image_href': image_href})
    start = time.time()

    if isinstance(image_file, str):
        with open(image_file, "wb") as image_file_obj:
            image_service.download(image_href, image_file_obj)
    else:
        image_service.download(image_href, image_file)

    LOG.debug("Image %(image_href)s downloaded in %(time).2f seconds.",
              {'image_href': image_href, 'time': time.time() - start})


def fetch(context, image_href, path, force_raw=False):
    with fileutils.remove_path_on_error(path):
        fetch_into(context, image_href, path)

    if force_raw:
        image_to_raw(image_href, path, "%s.part" % path)


def get_source_format(image_href, path):
    data = disk_utils.qemu_img_info(path)

    fmt = data.file_format
    if fmt is None:
        raise exception.ImageUnacceptable(
            reason=_("'qemu-img info' parsing failed."),
            image_id=image_href)

    backing_file = data.backing_file
    if backing_file is not None:
        raise exception.ImageUnacceptable(
            image_id=image_href,
            reason=_("fmt=%(fmt)s backed by: %(backing_file)s") %
            {'fmt': fmt, 'backing_file': backing_file})

    return fmt


def force_raw_will_convert(image_href, path_tmp):
    with fileutils.remove_path_on_error(path_tmp):
        fmt = get_source_format(image_href, path_tmp)
    if fmt != "raw":
        return True
    return False


def image_to_raw(image_href, path, path_tmp):
    with fileutils.remove_path_on_error(path_tmp):
        fmt = get_source_format(image_href, path_tmp)

        if fmt != "raw":
            staged = "%s.converted" % path

            utils.is_memory_insufficent(raise_if_fail=True)
            LOG.debug("%(image)s was %(format)s, converting to raw",
                      {'image': image_href, 'format': fmt})
            with fileutils.remove_path_on_error(staged):
                disk_utils.convert_image(path_tmp, staged, 'raw')
                os.unlink(path_tmp)

                data = disk_utils.qemu_img_info(staged)
                if data.file_format != "raw":
                    raise exception.ImageConvertFailed(
                        image_id=image_href,
                        reason=_("Converted to raw, but format is "
                                 "now %s") % data.file_format)

                os.rename(staged, path)
        else:
            os.rename(path_tmp, path)


def image_show(context, image_href, image_service=None):
    if image_service is None:
        image_service = service.get_image_service(image_href, context=context)
    return image_service.show(image_href)


def download_size(context, image_href, image_service=None):
    return image_show(context, image_href, image_service)['size']


def converted_size(path, estimate=False):
    """Get size of converted raw image.

    The size of image converted to raw format can be growing up to the virtual
    size of the image.

    :param path: path to the image file.
    :param estimate: Whether to estimate the size by scaling the
        original size
    :returns: For `estimate=False`, return the size of the
        raw image file. For `estimate=True`, return the size of
        the original image scaled by the configuration value
        `raw_image_growth_factor`.
    """
    data = disk_utils.qemu_img_info(path)
    if not estimate:
        return data.virtual_size
    growth_factor = CONF.raw_image_growth_factor
    return int(min(data.disk_size * growth_factor, data.virtual_size))


def get_image_properties(context, image_href, properties="all"):
    """Returns the values of several properties of an image

    :param context: context
    :param image_href: href of the image
    :param properties: the properties whose values are required.
        This argument is optional, default value is "all", so if not specified
        all properties will be returned.
    :returns: a dict of the values of the properties. A property not on the
        glance metadata will have a value of None.
    """
    img_service = service.get_image_service(image_href, context=context)
    iproperties = img_service.show(image_href)['properties']

    if properties == "all":
        return iproperties

    return {p: iproperties.get(p) for p in properties}


def get_temp_url_for_glance_image(context, image_uuid):
    """Returns the tmp url for a glance image.

    :param context: context
    :param image_uuid: the UUID of the image in glance
    :returns: the tmp url for the glance image.
    """
    glance_service = service.GlanceImageService(context=context)
    image_properties = glance_service.show(image_uuid)
    LOG.debug('Got image info: %(info)s for image %(image_uuid)s.',
              {'info': image_properties, 'image_uuid': image_uuid})
    return glance_service.swift_temp_url(image_properties)


def create_boot_iso(context, output_filename, kernel_href,
                    ramdisk_href, deploy_iso_href=None, esp_image_href=None,
                    root_uuid=None, kernel_params=None, boot_mode=None,
                    inject_files=None):
    """Creates a bootable ISO image for a node.

    Given the hrefs for kernel, ramdisk, root partition's UUID and
    kernel cmdline arguments, this method fetches the kernel and ramdisk,
    and builds a bootable ISO image that can be used to boot up the
    baremetal node.

    :param context: context
    :param output_filename: the absolute path of the output ISO file
    :param kernel_href: URL or glance uuid of the kernel to use
    :param ramdisk_href: URL or glance uuid of the ramdisk to use
    :param deploy_iso_href: URL or glance UUID of the deploy ISO image
        to extract EFI system partition image. If not specified,
        the `esp_image_href` option must be present if UEFI-bootable
        ISO is desired.
    :param esp_image_href: URL or glance UUID of FAT12/16/32-formatted EFI
        system partition image containing the EFI boot loader (e.g. GRUB2)
        for each hardware architecture to boot. This image will be written
        onto the ISO image. If not specified, the `deploy_iso_href` option
        is only required for building UEFI-bootable ISO.
    :param kernel_params: a string containing whitespace separated values
        kernel cmdline arguments of the form K=V or K (optional).
    :boot_mode: the boot mode in which the deploy is to happen.
    :param inject_files: Mapping of local source file paths to their location
        on the final ISO image.
    :raises: ImageCreationFailed, if creating boot ISO failed.
    """
    with utils.tempdir() as tmpdir:
        kernel_path = os.path.join(tmpdir, kernel_href.split('/')[-1])
        ramdisk_path = os.path.join(tmpdir, ramdisk_href.split('/')[-1])
        fetch(context, kernel_href, kernel_path)
        fetch(context, ramdisk_href, ramdisk_path)

        params = []
        if root_uuid:
            params.append('root=UUID=%s' % root_uuid)
        if kernel_params:
            params.append(kernel_params)

        if boot_mode == 'uefi':

            deploy_iso_path = esp_image_path = None

            if deploy_iso_href:
                deploy_iso_path = os.path.join(
                    tmpdir, deploy_iso_href.split('/')[-1])
                fetch(context, deploy_iso_href, deploy_iso_path)

            elif esp_image_href:
                esp_image_path = os.path.join(
                    tmpdir, esp_image_href.split('/')[-1])
                fetch(context, esp_image_href, esp_image_path)

            elif CONF.esp_image:
                esp_image_path = CONF.esp_image
            # TODO(TheJulia): we should opportunisticly try to make bios
            # bootable and UEFI. In other words, collapse a lot of this
            # path since they are not mutually exclusive.
            # UEFI boot mode, but Network iPXE -> ISO means bios bootable
            # contents are still required.
            create_esp_image_for_uefi(
                output_filename, kernel_path, ramdisk_path,
                deploy_iso=deploy_iso_path, esp_image=esp_image_path,
                kernel_params=params, inject_files=inject_files)

        else:
            create_isolinux_image_for_bios(
                output_filename, kernel_path, ramdisk_path,
                kernel_params=params, inject_files=inject_files)


IMAGE_TYPE_PARTITION = 'partition'
IMAGE_TYPE_WHOLE_DISK = 'whole-disk'
VALID_IMAGE_TYPES = frozenset((IMAGE_TYPE_PARTITION, IMAGE_TYPE_WHOLE_DISK))


def is_whole_disk_image(ctx, instance_info):
    """Find out if the image is a partition image or a whole disk image.

    :param ctx: an admin context
    :param instance_info: a node's instance info dict

    :returns: True for whole disk images and False for partition images
        and None on no image_source or Error.
    """
    image_source = instance_info.get('image_source')
    if not image_source:
        return

    image_type = instance_info.get('image_type')
    if image_type:
        # This logic reflects the fact that whole disk images are the default
        return image_type != IMAGE_TYPE_PARTITION

    is_whole_disk_image = False
    if glance_utils.is_glance_image(image_source):
        try:
            iproperties = get_image_properties(ctx, image_source)
        except Exception:
            return

        image_type = iproperties.get('img_type')
        if image_type:
            return image_type != IMAGE_TYPE_PARTITION

        is_whole_disk_image = (not iproperties.get('kernel_id')
                               and not iproperties.get('ramdisk_id'))
    else:
        # Non glance image ref
        if (not instance_info.get('kernel')
            and not instance_info.get('ramdisk')):
            is_whole_disk_image = True

    return is_whole_disk_image


def _extract_iso(extract_iso, extract_dir):
    # NOTE(rpittau): we could probably just extract the files we need
    # if we find them. Also we probably need to detect the correct iso
    # type (UDF, RR, JOLIET).
    iso = pycdlib.PyCdlib()
    iso.open(extract_iso)

    for dirname, dirlist, filelist in iso.walk(iso_path='/'):
        dir_path = dirname.lstrip('/')
        for dir_iso in dirlist:
            os.makedirs(os.path.join(extract_dir, dir_path, dir_iso))
        for file in filelist:
            file_path = os.path.join(extract_dir, dirname, file)
            iso.get_file_from_iso(
                os.path.join(extract_dir, dir_path, file),
                iso_path=file_path)

    iso.close()


def _get_deploy_iso_files(deploy_iso, mountdir):
    """This function opens up the deploy iso used for deploy.

    :param deploy_iso: path to the deploy iso where its
                       contents are fetched to.
    :raises: ImageCreationFailed if mount fails.
    :returns: a tuple consisting of - 1. a dictionary containing
                                         the values as required
                                         by create_isolinux_image,
                                      2. efiboot.img relative path, and
                                      3. grub.cfg relative path.

    """
    e_img_rel_path = None
    e_img_path = None
    grub_rel_path = None
    grub_path = None

    try:
        _extract_iso(deploy_iso, mountdir)
    except Exception as e:
        LOG.exception("extracting the deploy iso failed.")
        raise exception.ImageCreationFailed(image_type='iso', error=e)

    try:
        for (dir, subdir, files) in os.walk(mountdir):
            if 'efiboot.img' in files:
                e_img_path = os.path.join(dir, 'efiboot.img')
                e_img_rel_path = os.path.relpath(e_img_path,
                                                 mountdir)
            if 'grub.cfg' in files:
                grub_path = os.path.join(dir, 'grub.cfg')
                grub_rel_path = os.path.relpath(grub_path,
                                                mountdir)
    except (OSError, IOError) as e:
        LOG.exception("examining the deploy iso failed.")
        shutil.rmtree(mountdir)
        raise exception.ImageCreationFailed(image_type='iso', error=e)

    # check if the variables are assigned some values or not during
    # walk of the mountdir.
    if not (e_img_path and e_img_rel_path and grub_path and grub_rel_path):
        error = (_("Deploy iso didn't contain efiboot.img or grub.cfg"))
        shutil.rmtree(mountdir)
        raise exception.ImageCreationFailed(image_type='iso', error=error)

    uefi_path_info = {e_img_path: e_img_rel_path,
                      grub_path: grub_rel_path}

    # Returning a tuple as it makes the code simpler and clean.
    # uefi_path_info: is needed by the caller for _create_root_fs to create
    # appropriate directory structures for uefi boot iso.
    # grub_rel_path: is needed to copy the new grub.cfg generated using
    # generate_cfg() to the same directory path structure where it was
    # present in deploy iso. This path varies for different OS vendors.
    # e_img_rel_path: is required by mkisofs to generate boot iso.
    return uefi_path_info, e_img_rel_path, grub_rel_path
