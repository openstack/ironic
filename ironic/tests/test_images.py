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

import contextlib
import fixtures
import mock
import os
import shutil

from oslo.config import cfg
from oslo.utils import excutils

from ironic.common import exception
from ironic.common import images
from ironic.common import utils
from ironic.openstack.common import processutils
from ironic.tests import base

CONF = cfg.CONF


class IronicImagesTestCase(base.TestCase):
    def test_fetch_raw_image(self):

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        def fake_rename(old, new):
            self.executes.append(('mv', old, new))

        def fake_unlink(path):
            self.executes.append(('rm', path))

        @contextlib.contextmanager
        def fake_rm_on_error(path):
            try:
                yield
            except Exception:
                with excutils.save_and_reraise_exception():
                    fake_del_if_exists(path)

        def fake_del_if_exists(path):
            self.executes.append(('rm', '-f', path))

        def fake_qemu_img_info(path):
            class FakeImgInfo(object):
                pass

            file_format = path.split('.')[-1]
            if file_format == 'part':
                file_format = path.split('.')[-2]
            elif file_format == 'converted':
                file_format = 'raw'
            if 'backing' in path:
                backing_file = 'backing'
            else:
                backing_file = None

            FakeImgInfo.file_format = file_format
            FakeImgInfo.backing_file = backing_file

            return FakeImgInfo()

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.common.utils.execute', fake_execute))
        self.useFixture(fixtures.MonkeyPatch('os.rename', fake_rename))
        self.useFixture(fixtures.MonkeyPatch('os.unlink', fake_unlink))
        self.useFixture(fixtures.MonkeyPatch(
                'ironic.common.images.fetch', lambda *_: None))
        self.useFixture(fixtures.MonkeyPatch(
                'ironic.common.images.qemu_img_info', fake_qemu_img_info))
        self.useFixture(fixtures.MonkeyPatch(
                'ironic.openstack.common.fileutils.remove_path_on_error',
                fake_rm_on_error))
        self.useFixture(fixtures.MonkeyPatch(
                'ironic.openstack.common.fileutils.delete_if_exists',
                fake_del_if_exists))

        context = 'opaque context'
        image_id = '4'

        target = 't.qcow2'
        self.executes = []
        expected_commands = [('qemu-img', 'convert', '-O', 'raw',
                              't.qcow2.part', 't.qcow2.converted'),
                             ('rm', 't.qcow2.part'),
                             ('mv', 't.qcow2.converted', 't.qcow2')]
        images.fetch_to_raw(context, image_id, target)
        self.assertEqual(expected_commands, self.executes)

        target = 't.raw'
        self.executes = []
        expected_commands = [('mv', 't.raw.part', 't.raw')]
        images.fetch_to_raw(context, image_id, target)
        self.assertEqual(expected_commands, self.executes)

        target = 'backing.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'backing.qcow2.part')]
        self.assertRaises(exception.ImageUnacceptable,
                          images.fetch_to_raw,
                          context, image_id, target)
        self.assertEqual(expected_commands, self.executes)

        del self.executes


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

        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle
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
