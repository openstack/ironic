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

from ironic.common import exception
from ironic.common import images
from ironic.openstack.common import excutils
from ironic.tests import base


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
