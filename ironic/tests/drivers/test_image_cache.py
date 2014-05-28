# -*- encoding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
#
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

"""Tests for ImageCache class and helper functions."""

import mock
import os
import tempfile
import time

from ironic.common import images
from ironic.drivers.modules import image_cache
from ironic.tests import base


def touch(filename):
    open(filename, 'w').close()


@mock.patch.object(images, 'fetch_to_raw')
class TestImageCacheFetch(base.TestCase):

    def setUp(self):
        super(TestImageCacheFetch, self).setUp()
        self.master_dir = tempfile.mkdtemp()
        self.cache = image_cache.ImageCache(self.master_dir, None, None)
        self.dest_dir = tempfile.mkdtemp()
        self.dest_path = os.path.join(self.dest_dir, 'dest')
        self.uuid = 'uuid'
        self.master_path = os.path.join(self.master_dir, self.uuid)

    @mock.patch.object(image_cache.ImageCache, 'clean_up')
    @mock.patch.object(image_cache.ImageCache, '_download_image')
    def test_fetch_image_no_master_dir(self, mock_download, mock_clean_up,
                                       mock_fetch_to_raw):
        self.cache.master_dir = None
        self.cache.fetch_image('uuid', self.dest_path)
        self.assertFalse(mock_download.called)
        mock_fetch_to_raw.assert_called_once_with(
            None, 'uuid', self.dest_path, None)
        self.assertFalse(mock_clean_up.called)

    @mock.patch.object(image_cache.ImageCache, 'clean_up')
    @mock.patch.object(image_cache.ImageCache, '_download_image')
    def test_fetch_image_dest_exists(self, mock_download, mock_clean_up,
                                     mock_fetch_to_raw):
        touch(self.dest_path)
        self.cache.fetch_image(self.uuid, self.dest_path)
        self.assertFalse(mock_download.called)
        self.assertFalse(mock_fetch_to_raw.called)
        self.assertFalse(mock_clean_up.called)

    @mock.patch.object(image_cache.ImageCache, 'clean_up')
    @mock.patch.object(image_cache.ImageCache, '_download_image')
    def test_fetch_image_master_exists(self, mock_download, mock_clean_up,
                                       mock_fetch_to_raw):
        touch(self.master_path)
        self.cache.fetch_image(self.uuid, self.dest_path)
        self.assertFalse(mock_download.called)
        self.assertFalse(mock_fetch_to_raw.called)
        self.assertTrue(os.path.isfile(self.dest_path))
        self.assertEqual(os.stat(self.dest_path).st_ino,
                         os.stat(self.master_path).st_ino)
        self.assertFalse(mock_clean_up.called)

    @mock.patch.object(image_cache.ImageCache, 'clean_up')
    @mock.patch.object(image_cache.ImageCache, '_download_image')
    def test_fetch_image(self, mock_download, mock_clean_up,
                         mock_fetch_to_raw):
        self.cache.fetch_image(self.uuid, self.dest_path)
        self.assertFalse(mock_fetch_to_raw.called)
        mock_download.assert_called_once_with(
            self.uuid, self.master_path, self.dest_path, ctx=None)
        self.assertTrue(mock_clean_up.called)

    def test__download_image(self, mock_fetch_to_raw):
        def _fake_fetch_to_raw(ctx, uuid, tmp_path, *args):
            self.assertEqual(self.uuid, uuid)
            self.assertTrue(os.path.isfile(tmp_path))
            self.assertNotEqual(self.dest_path, tmp_path)
            with open(tmp_path, 'w') as fp:
                fp.write("TEST")

        mock_fetch_to_raw.side_effect = _fake_fetch_to_raw
        self.cache._download_image(self.uuid, self.master_path, self.dest_path)
        self.assertTrue(os.path.isfile(self.dest_path))
        self.assertTrue(os.path.isfile(self.master_path))
        self.assertEqual(os.stat(self.dest_path).st_ino,
                         os.stat(self.master_path).st_ino)
        with open(self.dest_path) as fp:
            self.assertEqual("TEST", fp.read())


class TestImageCacheCleanUp(base.TestCase):

    def setUp(self):
        super(TestImageCacheCleanUp, self).setUp()
        self.master_dir = tempfile.mkdtemp()
        self.cache = image_cache.ImageCache(self.master_dir,
                                            cache_size=10,
                                            cache_ttl=600)

    @mock.patch.object(image_cache.ImageCache, '_clean_up_ensure_cache_size')
    def test_clean_up_old_deleted(self, mock_clean_size):
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(2)]
        for filename in files:
            touch(filename)
        # NOTE(dtantsur): Can't alter ctime, have to set mtime to the future
        new_current_time = time.time() + 900
        os.utime(files[0], (new_current_time - 100, new_current_time - 100))
        with mock.patch.object(time, 'time', lambda: new_current_time):
            self.cache.clean_up()

        survived = mock_clean_size.call_args[0][0]
        self.assertEqual(1, len(survived))
        self.assertEqual(files[0], survived[0][0])
        # NOTE(dtantsur): do not compare milliseconds
        self.assertEqual(int(new_current_time - 100), int(survived[0][1]))
        self.assertEqual(int(new_current_time - 100),
                         int(survived[0][2].st_mtime))

    @mock.patch.object(image_cache.ImageCache, '_clean_up_ensure_cache_size')
    def test_clean_up_files_with_links_untouched(self, mock_clean_size):
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(2)]
        for filename in files:
            touch(filename)
            os.link(filename, filename + 'copy')

        new_current_time = time.time() + 900
        with mock.patch.object(time, 'time', lambda: new_current_time):
            self.cache.clean_up()

        for filename in files:
            self.assertTrue(os.path.exists(filename))
        mock_clean_size.assert_called_once_with([])

    @mock.patch.object(image_cache.ImageCache, '_clean_up_too_old')
    def test_clean_up_ensure_cache_size(self, mock_clean_ttl):
        mock_clean_ttl.side_effect = lambda listing: listing
        # NOTE(dtantsur): Cache size in test is 10 bytes, we create 6 files
        # with 3 bytes each and expect 3 to be deleted
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(6)]
        for filename in files:
            with open(filename, 'w') as fp:
                fp.write('123')
        # NOTE(dtantsur): Make 3 files 'newer' to check that
        # old ones are deleted first
        new_current_time = time.time() + 100
        for filename in files[:3]:
            os.utime(filename, (new_current_time, new_current_time))

        with mock.patch.object(time, 'time', lambda: new_current_time):
            self.cache.clean_up()

        for filename in files[:3]:
            self.assertTrue(os.path.exists(filename))
        for filename in files[3:]:
            self.assertFalse(os.path.exists(filename))

    @mock.patch.object(image_cache.LOG, 'info')
    @mock.patch.object(image_cache.ImageCache, '_clean_up_too_old')
    def test_clean_up_cache_still_large(self, mock_clean_ttl, mock_log):
        mock_clean_ttl.side_effect = lambda listing: listing
        # NOTE(dtantsur): Cache size in test is 10 bytes, we create 2 files
        # than cannot be deleted and expected this to be logged
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(2)]
        for filename in files:
            with open(filename, 'w') as fp:
                fp.write('123')
            os.link(filename, filename + 'copy')

        self.cache.clean_up()

        for filename in files:
            self.assertTrue(os.path.exists(filename))
        self.assertTrue(mock_log.called)
