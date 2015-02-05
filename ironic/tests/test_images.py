# Vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
import six.moves.builtins as __builtin__

from ironic.common import exception
from ironic.common import image_service
from ironic.common import images
from ironic.common import utils
from ironic.openstack.common import imageutils
from ironic.tests import base

CONF = cfg.CONF


class IronicImagesTestCase(base.TestCase):

    class FakeImgInfo(object):
        pass

    @mock.patch.object(imageutils, 'QemuImgInfo')
    @mock.patch.object(os.path, 'exists', return_value=False)
    def test_qemu_img_info_path_doesnt_exist(self, path_exists_mock,
                                             qemu_img_info_mock):
        images.qemu_img_info('noimg')
        path_exists_mock.assert_called_once_with('noimg')
        qemu_img_info_mock.assert_called_once_with()

    @mock.patch.object(utils, 'execute', return_value=('out', 'err'))
    @mock.patch.object(imageutils, 'QemuImgInfo')
    @mock.patch.object(os.path, 'exists', return_value=True)
    def test_qemu_img_info_path_exists(self, path_exists_mock,
                                       qemu_img_info_mock, execute_mock):
        images.qemu_img_info('img')
        path_exists_mock.assert_called_once_with('img')
        execute_mock.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', 'img')
        qemu_img_info_mock.assert_called_once_with('out')

    @mock.patch.object(utils, 'execute')
    def test_convert_image(self, execute_mock):
        images.convert_image('source', 'dest', 'out_format')
        execute_mock.assert_called_once_with('qemu-img', 'convert', '-O',
                                             'out_format', 'source', 'dest',
                                             run_as_root=False)

    @mock.patch.object(image_service, 'Service')
    @mock.patch.object(__builtin__, 'open')
    def test_fetch_no_image_service(self, open_mock, image_service_mock):
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'file'
        open_mock.return_value = mock_file_handle

        images.fetch('context', 'image_href', 'path')

        open_mock.assert_called_once_with('path', 'wb')
        image_service_mock.assert_called_once_with(version=1,
                                                   context='context')
        image_service_mock.return_value.download.assert_called_once_with(
            'image_href', 'file')

    @mock.patch.object(__builtin__, 'open')
    def test_fetch_image_service(self, open_mock):
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'file'
        open_mock.return_value = mock_file_handle
        image_service_mock = mock.Mock()

        images.fetch('context', 'image_href', 'path', image_service_mock)

        open_mock.assert_called_once_with('path', 'wb')
        image_service_mock.download.assert_called_once_with(
            'image_href', 'file')

    @mock.patch.object(images, 'image_to_raw')
    @mock.patch.object(__builtin__, 'open')
    def test_fetch_image_service_force_raw(self, open_mock, image_to_raw_mock):
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'file'
        open_mock.return_value = mock_file_handle
        image_service_mock = mock.Mock()

        images.fetch('context', 'image_href', 'path', image_service_mock,
                     force_raw=True)

        open_mock.assert_called_once_with('path', 'wb')
        image_service_mock.download.assert_called_once_with(
            'image_href', 'file')
        image_to_raw_mock.assert_called_once_with(
            'image_href', 'path', 'path.part')

    @mock.patch.object(images, 'qemu_img_info')
    def test_image_to_raw_no_file_format(self, qemu_img_info_mock):
        info = self.FakeImgInfo()
        info.file_format = None
        qemu_img_info_mock.return_value = info

        e = self.assertRaises(exception.ImageUnacceptable, images.image_to_raw,
                              'image_href', 'path', 'path_tmp')
        qemu_img_info_mock.assert_called_once_with('path_tmp')
        self.assertIn("'qemu-img info' parsing failed.", str(e))

    @mock.patch.object(images, 'qemu_img_info')
    def test_image_to_raw_backing_file_present(self, qemu_img_info_mock):
        info = self.FakeImgInfo()
        info.file_format = 'raw'
        info.backing_file = 'backing_file'
        qemu_img_info_mock.return_value = info

        e = self.assertRaises(exception.ImageUnacceptable, images.image_to_raw,
                              'image_href', 'path', 'path_tmp')
        qemu_img_info_mock.assert_called_once_with('path_tmp')
        self.assertIn("fmt=raw backed by: backing_file", str(e))

    @mock.patch.object(os, 'rename')
    @mock.patch.object(os, 'unlink')
    @mock.patch.object(images, 'convert_image')
    @mock.patch.object(images, 'qemu_img_info')
    def test_image_to_raw(self, qemu_img_info_mock, convert_image_mock,
                          unlink_mock, rename_mock):
        CONF.set_override('force_raw_images', True)
        info = self.FakeImgInfo()
        info.file_format = 'fmt'
        info.backing_file = None
        qemu_img_info_mock.return_value = info

        def convert_side_effect(source, dest, out_format):
            info.file_format = 'raw'
        convert_image_mock.side_effect = convert_side_effect

        images.image_to_raw('image_href', 'path', 'path_tmp')

        qemu_img_info_mock.assert_has_calls([mock.call('path_tmp'),
                                             mock.call('path.converted')])
        convert_image_mock.assert_called_once_with('path_tmp',
                                                   'path.converted', 'raw')
        unlink_mock.assert_called_once_with('path_tmp')
        rename_mock.assert_called_once_with('path.converted', 'path')

    @mock.patch.object(os, 'unlink')
    @mock.patch.object(images, 'convert_image')
    @mock.patch.object(images, 'qemu_img_info')
    def test_image_to_raw_not_raw_after_conversion(self, qemu_img_info_mock,
                                                   convert_image_mock,
                                                   unlink_mock):
        CONF.set_override('force_raw_images', True)
        info = self.FakeImgInfo()
        info.file_format = 'fmt'
        info.backing_file = None
        qemu_img_info_mock.return_value = info

        self.assertRaises(exception.ImageConvertFailed, images.image_to_raw,
                          'image_href', 'path', 'path_tmp')
        qemu_img_info_mock.assert_has_calls([mock.call('path_tmp'),
                                             mock.call('path.converted')])
        convert_image_mock.assert_called_once_with('path_tmp',
                                                   'path.converted', 'raw')
        unlink_mock.assert_called_once_with('path_tmp')

    @mock.patch.object(os, 'rename')
    @mock.patch.object(images, 'qemu_img_info')
    def test_image_to_raw_already_raw_format(self, qemu_img_info_mock,
                                             rename_mock):
        info = self.FakeImgInfo()
        info.file_format = 'raw'
        info.backing_file = None
        qemu_img_info_mock.return_value = info

        images.image_to_raw('image_href', 'path', 'path_tmp')

        qemu_img_info_mock.assert_called_once_with('path_tmp')
        rename_mock.assert_called_once_with('path_tmp', 'path')

    @mock.patch.object(image_service, 'Service')
    def test_download_size_no_image_service(self, image_service_mock):
        images.download_size('context', 'image_href')
        image_service_mock.assert_called_once_with(version=1,
                                                   context='context')
        image_service_mock.return_value.show.assert_called_once_with(
            'image_href')

    def test_download_size_image_service(self):
        image_service_mock = mock.MagicMock()
        images.download_size('context', 'image_href', image_service_mock)
        image_service_mock.show.assert_called_once_with('image_href')

    @mock.patch.object(images, 'qemu_img_info')
    def test_converted_size(self, qemu_img_info_mock):
        info = self.FakeImgInfo()
        info.virtual_size = 1
        qemu_img_info_mock.return_value = info
        size = images.converted_size('path')
        qemu_img_info_mock.assert_called_once_with('path')
        self.assertEqual(1, size)


class FsImageTestCase(base.TestCase):

    @mock.patch.object(shutil, 'copyfile')
    @mock.patch.object(os, 'makedirs')
    @mock.patch.object(os.path, 'dirname')
    @mock.patch.object(os.path, 'exists')
    def test__create_root_fs(self, path_exists_mock,
                            dirname_mock, mkdir_mock, cp_mock):

        path_exists_mock_func = lambda path: path == 'root_dir'

        files_info = {
                'a1': 'b1',
                'a2': 'b2',
                'a3': 'sub_dir/b3'}

        path_exists_mock.side_effect = path_exists_mock_func
        dirname_mock.side_effect = ['root_dir', 'root_dir',
                                    'root_dir/sub_dir', 'root_dir/sub_dir']
        images._create_root_fs('root_dir', files_info)
        cp_mock.assert_any_call('a1', 'root_dir/b1')
        cp_mock.assert_any_call('a2', 'root_dir/b2')
        cp_mock.assert_any_call('a3', 'root_dir/sub_dir/b3')

        path_exists_mock.assert_any_call('root_dir/sub_dir')
        dirname_mock.assert_any_call('root_dir/b1')
        dirname_mock.assert_any_call('root_dir/b2')
        dirname_mock.assert_any_call('root_dir/sub_dir/b3')
        mkdir_mock.assert_called_once_with('root_dir/sub_dir')

    @mock.patch.object(images, '_create_root_fs')
    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'write_to_file')
    @mock.patch.object(utils, 'dd')
    @mock.patch.object(utils, 'umount')
    @mock.patch.object(utils, 'mount')
    @mock.patch.object(utils, 'mkfs')
    def test_create_vfat_image(self, mkfs_mock, mount_mock, umount_mock,
            dd_mock, write_mock, tempdir_mock, create_root_fs_mock):

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tempdir'
        tempdir_mock.return_value = mock_file_handle

        parameters = {'p1': 'v1'}
        files_info = {'a': 'b'}
        images.create_vfat_image('tgt_file', parameters=parameters,
                files_info=files_info, parameters_file='qwe',
                fs_size_kib=1000)

        dd_mock.assert_called_once_with('/dev/zero',
                                         'tgt_file',
                                         'count=1',
                                         'bs=1000KiB')

        mkfs_mock.assert_called_once_with('vfat', 'tgt_file')
        mount_mock.assert_called_once_with('tgt_file', 'tempdir',
                                           '-o', 'umask=0')

        parameters_file_path = os.path.join('tempdir', 'qwe')
        write_mock.assert_called_once_with(parameters_file_path, 'p1=v1')
        create_root_fs_mock.assert_called_once_with('tempdir', files_info)
        umount_mock.assert_called_once_with('tempdir')

    @mock.patch.object(images, '_create_root_fs')
    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'dd')
    @mock.patch.object(utils, 'umount')
    @mock.patch.object(utils, 'mount')
    @mock.patch.object(utils, 'mkfs')
    def test_create_vfat_image_always_umount(self, mkfs_mock, mount_mock,
            umount_mock, dd_mock, tempdir_mock, create_root_fs_mock):

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tempdir'
        tempdir_mock.return_value = mock_file_handle
        files_info = {'a': 'b'}
        create_root_fs_mock.side_effect = OSError()
        self.assertRaises(exception.ImageCreationFailed,
                          images.create_vfat_image, 'tgt_file',
                          files_info=files_info)

        umount_mock.assert_called_once_with('tempdir')

    @mock.patch.object(utils, 'dd')
    def test_create_vfat_image_dd_fails(self, dd_mock):

        dd_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.ImageCreationFailed,
                          images.create_vfat_image, 'tgt_file')

    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'dd')
    @mock.patch.object(utils, 'mkfs')
    def test_create_vfat_image_mkfs_fails(self, mkfs_mock, dd_mock,
                                          tempdir_mock):

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tempdir'
        tempdir_mock.return_value = mock_file_handle

        mkfs_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.ImageCreationFailed,
                          images.create_vfat_image, 'tgt_file')

    @mock.patch.object(images, '_create_root_fs')
    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'dd')
    @mock.patch.object(utils, 'umount')
    @mock.patch.object(utils, 'mount')
    @mock.patch.object(utils, 'mkfs')
    def test_create_vfat_image_umount_fails(self, mkfs_mock, mount_mock,
            umount_mock, dd_mock, tempdir_mock, create_root_fs_mock):

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tempdir'
        tempdir_mock.return_value = mock_file_handle
        umount_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_vfat_image, 'tgt_file')

    def test__generate_isolinux_cfg(self):

        kernel_params = ['key1=value1', 'key2']
        expected_cfg = ("default boot\n"
                        "\n"
                        "label boot\n"
                        "kernel /vmlinuz\n"
                        "append initrd=/initrd text key1=value1 key2 --")
        cfg = images._generate_isolinux_cfg(kernel_params)
        self.assertEqual(expected_cfg, cfg)

    @mock.patch.object(images, '_create_root_fs')
    @mock.patch.object(utils, 'write_to_file')
    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(images, '_generate_isolinux_cfg')
    def test_create_isolinux_image(self, gen_cfg_mock, utils_mock,
                                   tempdir_mock, write_to_file_mock,
                                   create_root_fs_mock):

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        cfg = "cfg"
        cfg_file = 'tmpdir/isolinux/isolinux.cfg'
        gen_cfg_mock.return_value = cfg

        params = ['a=b', 'c']

        images.create_isolinux_image('tgt_file', 'path/to/kernel',
                'path/to/ramdisk', kernel_params=params)

        files_info = {
                'path/to/kernel': 'vmlinuz',
                'path/to/ramdisk': 'initrd',
                CONF.isolinux_bin: 'isolinux/isolinux.bin'
                }
        create_root_fs_mock.assert_called_once_with('tmpdir', files_info)
        gen_cfg_mock.assert_called_once_with(params)
        write_to_file_mock.assert_called_once_with(cfg_file, cfg)

        utils_mock.assert_called_once_with('mkisofs', '-r', '-V',
                 "BOOT IMAGE", '-cache-inodes', '-J', '-l',
                 '-no-emul-boot', '-boot-load-size',
                 '4', '-boot-info-table', '-b', 'isolinux/isolinux.bin',
                 '-o', 'tgt_file', 'tmpdir')

    @mock.patch.object(images, '_create_root_fs')
    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'execute')
    def test_create_isolinux_image_rootfs_fails(self, utils_mock,
                                                tempdir_mock,
                                                create_root_fs_mock):
        create_root_fs_mock.side_effect = IOError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_isolinux_image,
                          'tgt_file', 'path/to/kernel',
                          'path/to/ramdisk')

    @mock.patch.object(images, '_create_root_fs')
    @mock.patch.object(utils, 'write_to_file')
    @mock.patch.object(utils, 'tempdir')
    @mock.patch.object(utils, 'execute')
    @mock.patch.object(images, '_generate_isolinux_cfg')
    def test_create_isolinux_image_mkisofs_fails(self, gen_cfg_mock,
                                                 utils_mock,
                                                 tempdir_mock,
                                                 write_to_file_mock,
                                                 create_root_fs_mock):

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle
        utils_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_isolinux_image,
                          'tgt_file', 'path/to/kernel',
                          'path/to/ramdisk')

    @mock.patch.object(images, 'create_isolinux_image')
    @mock.patch.object(images, 'fetch')
    @mock.patch.object(utils, 'tempdir')
    def test_create_boot_iso(self, tempdir_mock, fetch_images_mock,
                             create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso('ctx', 'output_file', 'kernel-uuid',
                               'ramdisk-uuid', 'root-uuid', 'kernel-params')

        fetch_images_mock.assert_any_call('ctx', 'kernel-uuid',
                'tmpdir/kernel-uuid')
        fetch_images_mock.assert_any_call('ctx', 'ramdisk-uuid',
                'tmpdir/ramdisk-uuid')
        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with('output_file',
                'tmpdir/kernel-uuid', 'tmpdir/ramdisk-uuid', params)

    @mock.patch.object(image_service, 'Service')
    def test_get_glance_image_properties_no_such_prop(
            self, image_service_mock):

        prop_dict = {'properties': {'p1': 'v1',
                                    'p2': 'v2'}}

        image_service_obj_mock = image_service_mock.return_value
        image_service_obj_mock.show.return_value = prop_dict

        ret_val = images.get_glance_image_properties('con', 'uuid',
                                                     ['p1', 'p2', 'p3'])
        image_service_mock.assert_called_once_with(version=1, context='con')
        image_service_obj_mock.show.assert_called_once_with('uuid')
        self.assertEqual({'p1': 'v1',
                          'p2': 'v2',
                          'p3': None}, ret_val)

    @mock.patch.object(image_service, 'Service')
    def test_get_glance_image_properties_default_all(
            self, image_service_mock):

        prop_dict = {'properties': {'p1': 'v1',
                                    'p2': 'v2'}}

        image_service_obj_mock = image_service_mock.return_value
        image_service_obj_mock.show.return_value = prop_dict

        ret_val = images.get_glance_image_properties('con', 'uuid')
        image_service_mock.assert_called_once_with(version=1, context='con')
        image_service_obj_mock.show.assert_called_once_with('uuid')
        self.assertEqual({'p1': 'v1',
                          'p2': 'v2'}, ret_val)

    @mock.patch.object(image_service, 'Service')
    def test_get_glance_image_properties_with_prop_subset(
            self, image_service_mock):

        prop_dict = {'properties': {'p1': 'v1',
                                    'p2': 'v2',
                                    'p3': 'v3'}}

        image_service_obj_mock = image_service_mock.return_value
        image_service_obj_mock.show.return_value = prop_dict

        ret_val = images.get_glance_image_properties('con', 'uuid',
                                                     ['p1', 'p3'])
        image_service_mock.assert_called_once_with(version=1, context='con')
        image_service_obj_mock.show.assert_called_once_with('uuid')
        self.assertEqual({'p1': 'v1',
                          'p3': 'v3'}, ret_val)

    @mock.patch.object(image_service, 'Service')
    def test_get_temp_url_for_glance_image(self, image_service_mock):

        direct_url = 'swift+http://host/v1/AUTH_xx/con/obj'
        image_info = {'id': 'qwe', 'properties': {'direct_url': direct_url}}
        glance_service_mock = image_service_mock.return_value
        glance_service_mock.swift_temp_url.return_value = 'temp-url'
        glance_service_mock.show.return_value = image_info

        temp_url = images.get_temp_url_for_glance_image('context',
                                                        'glance_uuid')

        glance_service_mock.show.assert_called_once_with('glance_uuid')
        self.assertEqual('temp-url', temp_url)
