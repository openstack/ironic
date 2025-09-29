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

import datetime
import os
import shutil
import tempfile
import time
from unittest import mock
import uuid

from oslo_config import cfg
from oslo_utils.imageutils import format_inspector as image_format_inspector
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import image_service
from ironic.common import images
from ironic.common import utils
from ironic.drivers.modules import image_cache
from ironic.tests import base


def touch(filename):
    open(filename, 'w').close()


class BaseTest(base.TestCase):

    def setUp(self):
        super().setUp()
        self.master_dir = tempfile.mkdtemp()
        self.cache = image_cache.ImageCache(self.master_dir, None, None)
        self.dest_dir = tempfile.mkdtemp()
        self.dest_path = os.path.join(self.dest_dir, 'dest')
        self.uuid = uuidutils.generate_uuid()
        self.master_path = ''.join([os.path.join(self.master_dir, self.uuid),
                                    '.converted'])
        self.img_info = {}


@mock.patch.object(image_service, 'get_image_service', autospec=True)
@mock.patch.object(image_cache.ImageCache, 'clean_up', autospec=True)
@mock.patch.object(image_cache.ImageCache, '_download_image', autospec=True)
class TestImageCacheFetch(BaseTest):

    @mock.patch.object(image_cache, '_fetch', autospec=True)
    def test_fetch_image_no_master_dir(self, mock_fetch, mock_download,
                                       mock_clean_up, mock_image_service):
        self.cache.master_dir = None
        self.cache.fetch_image(self.uuid, self.dest_path)
        self.assertFalse(mock_download.called)
        mock_fetch.assert_called_once_with(
            None, self.uuid, self.dest_path, True,
            None, None, None, disable_validation=False,
            image_auth_data=None)
        self.assertFalse(mock_clean_up.called)
        mock_image_service.assert_not_called()

    @mock.patch.object(image_cache, '_fetch', autospec=True)
    def test_fetch_image_no_master_dir_memory_low(self,
                                                  mock_fetch,
                                                  mock_download,
                                                  mock_clean_up,
                                                  mock_image_service):
        mock_fetch.side_effect = exception.InsufficientMemory
        self.cache.master_dir = None
        self.assertRaises(exception.InsufficientMemory,
                          self.cache.fetch_image,
                          self.uuid, self.dest_path)
        self.assertFalse(mock_download.called)
        mock_fetch.assert_called_once_with(
            None, self.uuid, self.dest_path, True,
            None, None, None, disable_validation=False,
            image_auth_data=None)
        self.assertFalse(mock_clean_up.called)
        mock_image_service.assert_not_called()

    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(image_cache, '_delete_dest_path_if_stale',
                       return_value=True, autospec=True)
    @mock.patch.object(image_cache, '_delete_master_path_if_stale',
                       return_value=True, autospec=True)
    def test_fetch_image_dest_and_master_uptodate(
            self, mock_cache_upd, mock_dest_upd, mock_link, mock_download,
            mock_clean_up, mock_image_service):
        self.cache.fetch_image(self.uuid, self.dest_path)
        mock_cache_upd.assert_called_once_with(
            self.master_path, self.uuid,
            mock_image_service.return_value.show.return_value)
        mock_dest_upd.assert_called_once_with(self.master_path, self.dest_path)
        self.assertFalse(mock_link.called)
        self.assertFalse(mock_download.called)
        self.assertFalse(mock_clean_up.called)
        mock_image_service.assert_called_once_with(self.uuid, context=None)
        mock_image_service.return_value.show.assert_called_once_with(self.uuid)

    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(image_cache, '_delete_dest_path_if_stale',
                       return_value=True, autospec=True)
    @mock.patch.object(image_cache, '_delete_master_path_if_stale',
                       return_value=True, autospec=True)
    def test_fetch_image_dest_and_master_uptodate_no_force_raw(
            self, mock_cache_upd, mock_dest_upd, mock_link, mock_download,
            mock_clean_up, mock_image_service):
        master_path = os.path.join(self.master_dir, self.uuid)
        self.cache.fetch_image(self.uuid, self.dest_path, force_raw=False)
        mock_cache_upd.assert_called_once_with(
            master_path, self.uuid,
            mock_image_service.return_value.show.return_value)
        mock_dest_upd.assert_called_once_with(master_path, self.dest_path)
        self.assertFalse(mock_link.called)
        self.assertFalse(mock_download.called)
        self.assertFalse(mock_clean_up.called)

    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(image_cache, '_delete_dest_path_if_stale',
                       return_value=False, autospec=True)
    @mock.patch.object(image_cache, '_delete_master_path_if_stale',
                       return_value=True, autospec=True)
    def test_fetch_image_dest_out_of_date(
            self, mock_cache_upd, mock_dest_upd, mock_link, mock_download,
            mock_clean_up, mock_image_service):
        self.cache.fetch_image(self.uuid, self.dest_path)
        mock_cache_upd.assert_called_once_with(
            self.master_path, self.uuid,
            mock_image_service.return_value.show.return_value)
        mock_dest_upd.assert_called_once_with(self.master_path, self.dest_path)
        mock_link.assert_called_once_with(self.master_path, self.dest_path)
        self.assertFalse(mock_download.called)
        self.assertFalse(mock_clean_up.called)

    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(image_cache, '_delete_dest_path_if_stale',
                       return_value=True, autospec=True)
    @mock.patch.object(image_cache, '_delete_master_path_if_stale',
                       return_value=False, autospec=True)
    def test_fetch_image_master_out_of_date(
            self, mock_cache_upd, mock_dest_upd, mock_link, mock_download,
            mock_clean_up, mock_image_service):
        self.cache.fetch_image(self.uuid, self.dest_path)
        mock_cache_upd.assert_called_once_with(
            self.master_path, self.uuid,
            mock_image_service.return_value.show.return_value)
        mock_dest_upd.assert_called_once_with(self.master_path, self.dest_path)
        self.assertFalse(mock_link.called)
        mock_download.assert_called_once_with(
            self.cache, self.uuid, self.master_path, self.dest_path,
            mock_image_service.return_value.show.return_value,
            ctx=None, force_raw=True, expected_format=None,
            expected_checksum=None, expected_checksum_algo=None,
            image_auth_data=None)
        mock_clean_up.assert_called_once_with(self.cache)
        mock_image_service.assert_called_once_with(self.uuid, context=None)
        mock_image_service.return_value.show.assert_called_once_with(self.uuid)

    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(image_cache, '_delete_dest_path_if_stale',
                       return_value=True, autospec=True)
    @mock.patch.object(image_cache, '_delete_master_path_if_stale',
                       return_value=False, autospec=True)
    def test_fetch_image_both_master_and_dest_out_of_date(
            self, mock_cache_upd, mock_dest_upd, mock_link, mock_download,
            mock_clean_up, mock_image_service):
        self.cache.fetch_image(self.uuid, self.dest_path)
        mock_cache_upd.assert_called_once_with(
            self.master_path, self.uuid,
            mock_image_service.return_value.show.return_value)
        mock_dest_upd.assert_called_once_with(self.master_path, self.dest_path)
        self.assertFalse(mock_link.called)
        mock_download.assert_called_once_with(
            self.cache, self.uuid, self.master_path, self.dest_path,
            mock_image_service.return_value.show.return_value,
            ctx=None, force_raw=True, expected_format=None,
            expected_checksum=None, expected_checksum_algo=None,
            image_auth_data=None)
        mock_clean_up.assert_called_once_with(self.cache)

    def test_fetch_image_not_uuid(self, mock_download, mock_clean_up,
                                  mock_image_service):
        href = u'http://abc.com/ubuntu.qcow2'
        href_converted = str(uuid.uuid5(uuid.NAMESPACE_URL, href))
        master_path = ''.join([os.path.join(self.master_dir, href_converted),
                               '.converted'])
        self.cache.fetch_image(href, self.dest_path)
        mock_download.assert_called_once_with(
            self.cache, href, master_path, self.dest_path,
            mock_image_service.return_value.show.return_value,
            ctx=None, force_raw=True, expected_format=None,
            expected_checksum=None, expected_checksum_algo=None,
            image_auth_data=None)
        self.assertTrue(mock_clean_up.called)

    def test_fetch_image_not_uuid_no_force_raw(self, mock_download,
                                               mock_clean_up,
                                               mock_image_service):
        href = u'http://abc.com/ubuntu.qcow2'
        href_converted = str(uuid.uuid5(uuid.NAMESPACE_URL, href))
        master_path = os.path.join(self.master_dir, href_converted)
        self.cache.fetch_image(href, self.dest_path, force_raw=False,
                               expected_checksum='f00',
                               expected_checksum_algo='sha256')
        mock_download.assert_called_once_with(
            self.cache, href, master_path, self.dest_path,
            mock_image_service.return_value.show.return_value,
            ctx=None, force_raw=False, expected_format=None,
            expected_checksum='f00', expected_checksum_algo='sha256',
            image_auth_data=None)
        self.assertTrue(mock_clean_up.called)

    @mock.patch.object(image_cache, '_fetch', autospec=True)
    def test_fetch_image_no_master_dir_disable_validation(
            self, mock_fetch, mock_download,
            mock_clean_up, mock_image_service):
        self.cache = image_cache.ImageCache(None, None, None,
                                            disable_validation=True)
        self.cache.fetch_image(self.uuid, self.dest_path)
        mock_download.assert_not_called()
        mock_fetch.assert_called_once_with(
            None, self.uuid, self.dest_path, True,
            None, None, None, disable_validation=True,
            image_auth_data=None)
        mock_clean_up.assert_not_called()
        mock_image_service.assert_not_called()

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(image_cache, '_delete_dest_path_if_stale',
                       return_value=False, autospec=True)
    @mock.patch.object(image_cache, '_delete_master_path_if_stale',
                       return_value=True, autospec=True)
    def test_fetch_image_hardlink_fails_fallback_to_copy(
            self, mock_cache_upd, mock_dest_upd, mock_link, mock_copyfile,
            mock_download, mock_clean_up, mock_image_service):
        mock_link.side_effect = OSError("Invalid cross-device link")

        self.cache.fetch_image(self.uuid, self.dest_path)

        mock_link.assert_called_once_with(self.master_path, self.dest_path)

        mock_copyfile.assert_called_once_with(self.master_path, self.dest_path)

        mock_cache_upd.assert_called_once_with(
            self.master_path, self.uuid,
            mock_image_service.return_value.show.return_value)
        mock_dest_upd.assert_called_once_with(self.master_path, self.dest_path)

        mock_download.assert_not_called()
        mock_clean_up.assert_not_called()

        mock_image_service.assert_called_once_with(self.uuid, context=None)
        mock_image_service.return_value.show.assert_called_once_with(self.uuid)


@mock.patch.object(image_cache, '_fetch', autospec=True)
class TestImageCacheDownload(BaseTest):

    def test__download_image(self, mock_fetch):
        def _fake_fetch(ctx, uuid, tmp_path, *_args, **_kwargs):
            self.assertEqual(self.uuid, uuid)
            self.assertNotEqual(self.dest_path, tmp_path)
            self.assertNotEqual(os.path.dirname(tmp_path), self.master_dir)
            with open(tmp_path, 'w') as fp:
                fp.write("TEST")

        mock_fetch.side_effect = _fake_fetch
        self.cache._download_image(self.uuid, self.master_path, self.dest_path,
                                   self.img_info)
        self.assertTrue(os.path.isfile(self.dest_path))
        self.assertTrue(os.path.isfile(self.master_path))
        self.assertEqual(os.stat(self.dest_path).st_ino,
                         os.stat(self.master_path).st_ino)
        with open(self.dest_path) as fp:
            self.assertEqual("TEST", fp.read())

    def test__download_image_large_url(self, mock_fetch):
        # A long enough URL may exceed the file name limits of the file system.
        # Make sure we don't use any parts of the URL anywhere.
        url = "http://example.com/image.iso?secret=%s" % ("x" * 1000)

        def _fake_fetch(ctx, href, tmp_path, *_args, **_kwargs):
            self.assertEqual(url, href)
            self.assertNotEqual(self.dest_path, tmp_path)
            self.assertNotEqual(os.path.dirname(tmp_path), self.master_dir)
            with open(tmp_path, 'w') as fp:
                fp.write("TEST")

        mock_fetch.side_effect = _fake_fetch
        self.cache._download_image(url, self.master_path, self.dest_path,
                                   self.img_info)
        self.assertTrue(os.path.isfile(self.dest_path))
        self.assertTrue(os.path.isfile(self.master_path))
        self.assertEqual(os.stat(self.dest_path).st_ino,
                         os.stat(self.master_path).st_ino)
        with open(self.dest_path) as fp:
            self.assertEqual("TEST", fp.read())

    @mock.patch.object(image_cache, 'LOG', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    def test__download_image_linkfail(self, mock_link, mock_log, mock_fetch):
        mock_link.side_effect = [None, OSError]
        self.assertRaises(exception.ImageDownloadFailed,
                          self.cache._download_image,
                          self.uuid, self.master_path, self.dest_path,
                          self.img_info)
        self.assertTrue(mock_fetch.called)
        self.assertEqual(2, mock_link.call_count)
        self.assertTrue(mock_log.error.called)

    def test__download_image_raises_memory_guard(self, mock_fetch):
        mock_fetch.side_effect = exception.InsufficientMemory
        self.assertRaises(exception.InsufficientMemory,
                          self.cache._download_image,
                          self.uuid, self.master_path,
                          self.dest_path, self.img_info)

    def test__download_image_disable_validation(self, mock_fetch):
        def _fake_fetch(ctx, uuid, tmp_path, *_args, disable_validation=False,
                        **_kwargs):
            self.assertEqual(self.uuid, uuid)
            self.assertNotEqual(self.dest_path, tmp_path)
            self.assertNotEqual(os.path.dirname(tmp_path), self.master_dir)
            with open(tmp_path, 'w') as fp:
                fp.write("TEST")
            self.assertTrue(disable_validation)

        mock_fetch.side_effect = _fake_fetch
        self.cache._disable_validation = True
        self.cache._download_image(self.uuid, self.master_path, self.dest_path,
                                   self.img_info)
        self.assertTrue(os.path.isfile(self.dest_path))
        self.assertTrue(os.path.isfile(self.master_path))
        self.assertEqual(os.stat(self.dest_path).st_ino,
                         os.stat(self.master_path).st_ino)
        with open(self.dest_path) as fp:
            self.assertEqual("TEST", fp.read())


@mock.patch.object(os, 'unlink', autospec=True)
class TestUpdateImages(BaseTest):

    @mock.patch.object(os.path, 'exists', return_value=False, autospec=True)
    def test__delete_master_path_if_stale_glance_img_not_cached(
            self, mock_path_exists, mock_unlink):
        res = image_cache._delete_master_path_if_stale(self.master_path,
                                                       self.uuid,
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        mock_path_exists.assert_called_once_with(self.master_path)
        self.assertFalse(res)

    @mock.patch.object(os.path, 'exists', return_value=True, autospec=True)
    def test__delete_master_path_if_stale_glance_img(
            self, mock_path_exists, mock_unlink):
        res = image_cache._delete_master_path_if_stale(self.master_path,
                                                       self.uuid,
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        mock_path_exists.assert_called_once_with(self.master_path)
        self.assertTrue(res)

    @mock.patch.object(os.path, 'exists', return_value=False, autospec=True)
    def test__delete_master_path_if_stale_oci_img_not_cached(
            self, mock_path_exists, mock_unlink):
        res = image_cache._delete_master_path_if_stale(self.master_path,
                                                       'oci://foo',
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        mock_path_exists.assert_called_once_with(self.master_path)
        self.assertFalse(res)

    @mock.patch.object(os.path, 'exists', return_value=True, autospec=True)
    def test__delete_master_path_if_stale_oci_img(
            self, mock_path_exists, mock_unlink):
        res = image_cache._delete_master_path_if_stale(self.master_path,
                                                       'oci://foo',
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        mock_path_exists.assert_called_once_with(self.master_path)
        self.assertTrue(res)

    def test__delete_master_path_if_stale_no_master(self, mock_unlink):
        res = image_cache._delete_master_path_if_stale(self.master_path,
                                                       'http://11',
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        self.assertFalse(res)

    def test__delete_master_path_if_stale_no_updated_at(self, mock_unlink):
        touch(self.master_path)
        href = 'http://awesomefreeimages.al/img111'
        res = image_cache._delete_master_path_if_stale(self.master_path, href,
                                                       self.img_info)
        mock_unlink.assert_called_once_with(self.master_path)
        self.assertFalse(res)

    def test__delete_master_path_if_stale_master_up_to_date(self, mock_unlink):
        touch(self.master_path)
        href = 'http://awesomefreeimages.al/img999'
        self.img_info = {
            'updated_at': datetime.datetime(1999, 11, 15, 8, 12, 31)
        }
        res = image_cache._delete_master_path_if_stale(self.master_path, href,
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        self.assertTrue(res)

    def test__delete_master_path_if_stale_master_same_time(self, mock_unlink):
        # When times identical should not delete cached file
        touch(self.master_path)
        mtime = utils.unix_file_modification_datetime(self.master_path)
        href = 'http://awesomefreeimages.al/img999'
        self.img_info = {
            'updated_at': mtime
        }
        res = image_cache._delete_master_path_if_stale(self.master_path, href,
                                                       self.img_info)
        self.assertFalse(mock_unlink.called)
        self.assertTrue(res)

    def test__delete_master_path_if_stale_out_of_date(self, mock_unlink):
        touch(self.master_path)
        href = 'http://awesomefreeimages.al/img999'
        self.img_info = {
            'updated_at': datetime.datetime((timeutils.utcnow().year
                                             + 1), 11, 15, 8, 12, 31)
        }
        res = image_cache._delete_master_path_if_stale(self.master_path, href,
                                                       self.img_info)
        mock_unlink.assert_called_once_with(self.master_path)
        self.assertFalse(res)

    def test__delete_dest_path_if_stale_no_dest(self, mock_unlink):
        res = image_cache._delete_dest_path_if_stale(self.master_path,
                                                     self.dest_path)
        self.assertFalse(mock_unlink.called)
        self.assertFalse(res)

    def test__delete_dest_path_if_stale_no_master(self, mock_unlink):
        touch(self.dest_path)
        res = image_cache._delete_dest_path_if_stale(self.master_path,
                                                     self.dest_path)
        mock_unlink.assert_called_once_with(self.dest_path)
        self.assertFalse(res)

    def test__delete_dest_path_if_stale_out_of_date(self, mock_unlink):
        touch(self.master_path)
        touch(self.dest_path)
        res = image_cache._delete_dest_path_if_stale(self.master_path,
                                                     self.dest_path)
        mock_unlink.assert_called_once_with(self.dest_path)
        self.assertFalse(res)

    def test__delete_dest_path_if_stale_up_to_date(self, mock_unlink):
        touch(self.master_path)
        os.link(self.master_path, self.dest_path)
        res = image_cache._delete_dest_path_if_stale(self.master_path,
                                                     self.dest_path)
        self.assertFalse(mock_unlink.called)
        self.assertTrue(res)


class TestImageCacheCleanUp(base.TestCase):

    def setUp(self):
        super(TestImageCacheCleanUp, self).setUp()
        self.master_dir = tempfile.mkdtemp()
        self.cache = image_cache.ImageCache(self.master_dir,
                                            cache_size=10,
                                            cache_ttl=600)

    @mock.patch.object(image_cache.ImageCache, '_clean_up_ensure_cache_size',
                       autospec=True)
    def test_clean_up_old_deleted(self, mock_clean_size):
        mock_clean_size.return_value = None
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(2)]
        for filename in files:
            touch(filename)
        # NOTE(dtantsur): Can't alter ctime, have to set mtime to the future
        new_current_time = time.time() + 900
        os.utime(files[0], (new_current_time - 100, new_current_time - 100))
        with mock.patch.object(time, 'time', lambda: new_current_time):
            self.cache.clean_up()

        mock_clean_size.assert_called_once_with(self.cache, mock.ANY, None)
        survived = mock_clean_size.call_args[0][1]
        self.assertEqual(1, len(survived))
        self.assertEqual(files[0], survived[0][0])
        # NOTE(dtantsur): do not compare milliseconds
        self.assertEqual(int(new_current_time - 100), int(survived[0][1]))
        self.assertEqual(int(new_current_time - 100),
                         int(survived[0][2].st_mtime))

    @mock.patch.object(image_cache.ImageCache, '_clean_up_ensure_cache_size',
                       autospec=True)
    def test_clean_up_old_with_amount(self, mock_clean_size):
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(2)]
        for filename in files:
            with open(filename, 'wb') as f:
                f.write(b'X')
        new_current_time = time.time() + 900
        with mock.patch.object(time, 'time', lambda: new_current_time):
            self.cache.clean_up(amount=1)

        self.assertFalse(mock_clean_size.called)
        # Exactly one file is expected to be deleted
        self.assertTrue(any(os.path.exists(f) for f in files))
        self.assertFalse(all(os.path.exists(f) for f in files))

    @mock.patch.object(image_cache.ImageCache, '_clean_up_ensure_cache_size',
                       autospec=True)
    def test_clean_up_files_with_links_untouched(self, mock_clean_size):
        mock_clean_size.return_value = None
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
        mock_clean_size.assert_called_once_with(mock.ANY, [], None)

    @mock.patch.object(image_cache.ImageCache, '_clean_up_too_old',
                       autospec=True)
    def test_clean_up_ensure_cache_size(self, mock_clean_ttl):
        mock_clean_ttl.side_effect = lambda *xx: xx[1:]
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

        mock_clean_ttl.assert_called_once_with(mock.ANY, mock.ANY, None)

    @mock.patch.object(image_cache.ImageCache, '_clean_up_too_old',
                       autospec=True)
    def test_clean_up_ensure_cache_size_with_amount(self, mock_clean_ttl):
        mock_clean_ttl.side_effect = lambda *xx: xx[1:]
        # NOTE(dtantsur): Cache size in test is 10 bytes, we create 6 files
        # with 3 bytes each and set amount to be 15, 5 files are to be deleted
        files = [os.path.join(self.master_dir, str(i))
                 for i in range(6)]
        for filename in files:
            with open(filename, 'w') as fp:
                fp.write('123')
        # NOTE(dtantsur): Make 1 file 'newer' to check that
        # old ones are deleted first
        new_current_time = time.time() + 100
        os.utime(files[0], (new_current_time, new_current_time))

        with mock.patch.object(time, 'time', lambda: new_current_time):
            self.cache.clean_up(amount=15)

        self.assertTrue(os.path.exists(files[0]))
        for filename in files[5:]:
            self.assertFalse(os.path.exists(filename))

        mock_clean_ttl.assert_called_once_with(mock.ANY, mock.ANY, 15)

    @mock.patch.object(image_cache.LOG, 'info', autospec=True)
    @mock.patch.object(image_cache.ImageCache, '_clean_up_too_old',
                       autospec=True)
    def test_clean_up_cache_still_large(self, mock_clean_ttl, mock_log):
        mock_clean_ttl.side_effect = lambda *xx: xx[1:]
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
        mock_clean_ttl.assert_called_once_with(mock.ANY, mock.ANY, None)

    @mock.patch.object(utils, 'rmtree_without_raise', autospec=True)
    @mock.patch.object(image_cache, '_fetch', autospec=True)
    def test_temp_images_not_cleaned(self, mock_fetch, mock_rmtree):
        def _fake_fetch(ctx, uuid, tmp_path, *_args, **_kwargs):
            with open(tmp_path, 'w') as fp:
                fp.write("TEST" * 10)

            # assume cleanup from another thread at this moment
            self.cache.clean_up()
            self.assertTrue(os.path.exists(tmp_path))

        mock_fetch.side_effect = _fake_fetch
        master_path = os.path.join(self.master_dir, 'uuid')
        dest_path = os.path.join(tempfile.mkdtemp(), 'dest')
        self.cache._download_image('uuid', master_path, dest_path, {})
        self.assertTrue(mock_rmtree.called)

    @mock.patch.object(utils, 'rmtree_without_raise', autospec=True)
    @mock.patch.object(image_cache, '_fetch', autospec=True)
    def test_temp_dir_exception(self, mock_fetch, mock_rmtree):
        mock_fetch.side_effect = exception.IronicException
        self.assertRaises(exception.IronicException,
                          self.cache._download_image,
                          'uuid', 'fake', 'fake', {})
        self.assertTrue(mock_rmtree.called)

    @mock.patch.object(image_cache.LOG, 'warning', autospec=True)
    @mock.patch.object(image_cache.ImageCache, '_clean_up_too_old',
                       autospec=True)
    @mock.patch.object(image_cache.ImageCache, '_clean_up_ensure_cache_size',
                       autospec=True)
    def test_clean_up_amount_not_satisfied(self, mock_clean_size,
                                           mock_clean_ttl, mock_log):
        mock_clean_ttl.side_effect = lambda *xx: xx[1:]
        mock_clean_size.side_effect = lambda self, listing, amount: amount
        self.cache.clean_up(amount=15)
        self.assertTrue(mock_log.called)

    def test_cleanup_ordering(self):

        class ParentCache(image_cache.ImageCache):
            def __init__(self):
                super(ParentCache, self).__init__('a', 1, 1, None)

        @image_cache.cleanup(priority=10000)
        class Cache1(ParentCache):
            pass

        @image_cache.cleanup(priority=20000)
        class Cache2(ParentCache):
            pass

        @image_cache.cleanup(priority=10000)
        class Cache3(ParentCache):
            pass

        self.assertEqual(image_cache._cache_cleanup_list[0][1], Cache2)

        # The order of caches with same priority is not deterministic.
        item_possibilities = [Cache1, Cache3]
        second_item_actual = image_cache._cache_cleanup_list[1][1]
        self.assertIn(second_item_actual, item_possibilities)
        item_possibilities.remove(second_item_actual)
        third_item_actual = image_cache._cache_cleanup_list[2][1]
        self.assertEqual(item_possibilities[0], third_item_actual)


@mock.patch.object(image_cache, '_cache_cleanup_list', autospec=True)
@mock.patch.object(os, 'statvfs', autospec=True)
@mock.patch.object(image_service, 'get_image_service', autospec=True)
class CleanupImageCacheTestCase(base.TestCase):

    def setUp(self):
        super(CleanupImageCacheTestCase, self).setUp()
        self.mock_first_cache = mock.MagicMock(spec_set=[])
        self.mock_second_cache = mock.MagicMock(spec_set=[])
        self.cache_cleanup_list = [(50, self.mock_first_cache),
                                   (20, self.mock_second_cache)]
        self.mock_first_cache.return_value.master_dir = 'first_cache_dir'
        self.mock_second_cache.return_value.master_dir = 'second_cache_dir'

    def test_no_clean_up(self, mock_image_service, mock_statvfs,
                         cache_cleanup_list_mock):
        # Enough space found - no clean up
        mock_show = mock_image_service.return_value.show
        mock_show.return_value = dict(size=42)
        mock_statvfs.return_value = mock.MagicMock(
            spec_set=['f_frsize', 'f_bavail'], f_frsize=1, f_bavail=1024)

        cache_cleanup_list_mock.__iter__.return_value = self.cache_cleanup_list

        image_cache.clean_up_caches(None, 'master_dir', [('uuid', 'path')])

        mock_show.assert_called_once_with('uuid')
        mock_statvfs.assert_called_once_with('master_dir')
        self.assertFalse(self.mock_first_cache.return_value.clean_up.called)
        self.assertFalse(self.mock_second_cache.return_value.clean_up.called)

        mock_statvfs.assert_called_once_with('master_dir')

    @mock.patch.object(os, 'stat', autospec=True)
    def test_one_clean_up(self, mock_stat, mock_image_service, mock_statvfs,
                          cache_cleanup_list_mock):
        # Not enough space, first cache clean up is enough
        mock_stat.return_value.st_dev = 1
        mock_show = mock_image_service.return_value.show
        mock_show.return_value = dict(size=42)
        mock_statvfs.side_effect = [
            mock.MagicMock(f_frsize=1, f_bavail=1,
                           spec_set=['f_frsize', 'f_bavail']),
            mock.MagicMock(f_frsize=1, f_bavail=1024,
                           spec_set=['f_frsize', 'f_bavail'])
        ]
        cache_cleanup_list_mock.__iter__.return_value = self.cache_cleanup_list
        image_cache.clean_up_caches(None, 'master_dir', [('uuid', 'path')])

        mock_show.assert_called_once_with('uuid')
        mock_statvfs.assert_called_with('master_dir')
        self.assertEqual(2, mock_statvfs.call_count)
        self.mock_first_cache.return_value.clean_up.assert_called_once_with(
            amount=(42 - 1))
        self.assertFalse(self.mock_second_cache.return_value.clean_up.called)

        # Since we are using generator expression in clean_up_caches, stat on
        # second cache wouldn't be called if we got enough free space on
        # cleaning up the first cache.
        mock_stat_calls_expected = [mock.call('master_dir'),
                                    mock.call('first_cache_dir')]
        mock_statvfs_calls_expected = [mock.call('master_dir'),
                                       mock.call('master_dir')]
        self.assertEqual(mock_stat_calls_expected, mock_stat.mock_calls)
        self.assertEqual(mock_statvfs_calls_expected, mock_statvfs.mock_calls)

    @mock.patch.object(os, 'stat', autospec=True)
    def test_clean_up_another_fs(self, mock_stat, mock_image_service,
                                 mock_statvfs, cache_cleanup_list_mock):
        # Not enough space, need to cleanup second cache
        mock_stat.side_effect = [mock.MagicMock(st_dev=1, spec_set=['st_dev']),
                                 mock.MagicMock(st_dev=2, spec_set=['st_dev']),
                                 mock.MagicMock(st_dev=1, spec_set=['st_dev'])]
        mock_show = mock_image_service.return_value.show
        mock_show.return_value = dict(size=42)
        mock_statvfs.side_effect = [
            mock.MagicMock(f_frsize=1, f_bavail=1,
                           spec_set=['f_frsize', 'f_bavail']),
            mock.MagicMock(f_frsize=1, f_bavail=1024,
                           spec_set=['f_frsize', 'f_bavail'])
        ]

        cache_cleanup_list_mock.__iter__.return_value = self.cache_cleanup_list
        image_cache.clean_up_caches(None, 'master_dir', [('uuid', 'path')])

        mock_show.assert_called_once_with('uuid')
        mock_statvfs.assert_called_with('master_dir')
        self.assertEqual(2, mock_statvfs.call_count)
        self.mock_second_cache.return_value.clean_up.assert_called_once_with(
            amount=(42 - 1))
        self.assertFalse(self.mock_first_cache.return_value.clean_up.called)

        # Since first cache exists on a different partition, it wouldn't be
        # considered for cleanup.
        mock_stat_calls_expected = [mock.call('master_dir'),
                                    mock.call('first_cache_dir'),
                                    mock.call('second_cache_dir')]
        mock_statvfs_calls_expected = [mock.call('master_dir'),
                                       mock.call('master_dir')]
        self.assertEqual(mock_stat_calls_expected, mock_stat.mock_calls)
        self.assertEqual(mock_statvfs_calls_expected, mock_statvfs.mock_calls)

    @mock.patch.object(os, 'stat', autospec=True)
    def test_both_clean_up(self, mock_stat, mock_image_service, mock_statvfs,
                           cache_cleanup_list_mock):
        # Not enough space, clean up of both caches required
        mock_stat.return_value.st_dev = 1
        mock_show = mock_image_service.return_value.show
        mock_show.return_value = dict(size=42)
        mock_statvfs.side_effect = [
            mock.MagicMock(f_frsize=1, f_bavail=1,
                           spec_set=['f_frsize', 'f_bavail']),
            mock.MagicMock(f_frsize=1, f_bavail=2,
                           spec_set=['f_frsize', 'f_bavail']),
            mock.MagicMock(f_frsize=1, f_bavail=1024,
                           spec_set=['f_frsize', 'f_bavail'])
        ]

        cache_cleanup_list_mock.__iter__.return_value = self.cache_cleanup_list
        image_cache.clean_up_caches(None, 'master_dir', [('uuid', 'path')])

        mock_show.assert_called_once_with('uuid')
        mock_statvfs.assert_called_with('master_dir')
        self.assertEqual(3, mock_statvfs.call_count)
        self.mock_first_cache.return_value.clean_up.assert_called_once_with(
            amount=(42 - 1))
        self.mock_second_cache.return_value.clean_up.assert_called_once_with(
            amount=(42 - 2))

        mock_stat_calls_expected = [mock.call('master_dir'),
                                    mock.call('first_cache_dir'),
                                    mock.call('second_cache_dir')]
        mock_statvfs_calls_expected = [mock.call('master_dir'),
                                       mock.call('master_dir'),
                                       mock.call('master_dir')]
        self.assertEqual(mock_stat_calls_expected, mock_stat.mock_calls)
        self.assertEqual(mock_statvfs_calls_expected, mock_statvfs.mock_calls)

    @mock.patch.object(os, 'stat', autospec=True)
    def test_clean_up_fail(self, mock_stat, mock_image_service, mock_statvfs,
                           cache_cleanup_list_mock):
        # Not enough space even after cleaning both caches - failure
        mock_stat.return_value.st_dev = 1
        mock_show = mock_image_service.return_value.show
        mock_show.return_value = dict(size=42)
        mock_statvfs.return_value = mock.MagicMock(
            f_frsize=1, f_bavail=1, spec_set=['f_frsize', 'f_bavail'])

        cache_cleanup_list_mock.__iter__.return_value = self.cache_cleanup_list
        self.assertRaises(exception.InsufficientDiskSpace,
                          image_cache.clean_up_caches,
                          None, 'master_dir', [('uuid', 'path')])

        mock_show.assert_called_once_with('uuid')
        mock_statvfs.assert_called_with('master_dir')
        self.assertEqual(3, mock_statvfs.call_count)
        self.mock_first_cache.return_value.clean_up.assert_called_once_with(
            amount=(42 - 1))
        self.mock_second_cache.return_value.clean_up.assert_called_once_with(
            amount=(42 - 1))

        mock_stat_calls_expected = [mock.call('master_dir'),
                                    mock.call('first_cache_dir'),
                                    mock.call('second_cache_dir')]
        mock_statvfs_calls_expected = [mock.call('master_dir'),
                                       mock.call('master_dir'),
                                       mock.call('master_dir')]
        self.assertEqual(mock_stat_calls_expected, mock_stat.mock_calls)
        self.assertEqual(mock_statvfs_calls_expected, mock_statvfs.mock_calls)


class TestFetchCleanup(base.TestCase):

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector):
        image_check = mock.MagicMock()
        image_check.__str__.side_effect = iter(['qcow2', 'raw'])
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_checksum='1234',
                           expected_checksum_algo='md5',
                           image_auth_data=None)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='1234',
                                           checksum_algo='md5',
                                           image_auth_data=None)
        mock_clean.assert_called_once_with('/foo', 100)
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        mock_remove.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_with_image_auth(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector):
        image_check = mock.MagicMock()
        image_check.__str__.side_effect = iter(['qcow2', 'raw'])
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_checksum='1234',
                           expected_checksum_algo='md5',
                           image_auth_data='foo')
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='1234',
                                           checksum_algo='md5',
                                           image_auth_data='foo')
        mock_clean.assert_called_once_with('/foo', 100)
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        mock_remove.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data='foo')
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_convert_to_gpt(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector):
        image_check = mock.MagicMock()
        image_check.__str__.side_effect = iter(['qcow2', 'gpt'])
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_checksum='1234',
                           expected_checksum_algo='md5')
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='1234',
                                           checksum_algo='md5',
                                           image_auth_data=None)
        mock_clean.assert_called_once_with('/foo', 100)
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        mock_remove.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_deep_inspection_disabled(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector):
        cfg.CONF.set_override(
            'disable_deep_image_inspection', True,
            group='conductor')
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'qcow2'
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum=None, checksum_algo=None,
                                           image_auth_data=None)
        mock_clean.assert_called_once_with('/foo', 100)
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        mock_remove.assert_not_called()
        mock_show.assert_not_called()
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_not_called()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_disable_validation(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector):
        image_check = mock.MagicMock()
        image_check.__str__.side_effect = iter(['qcow2', 'raw'])
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_checksum='1234',
                           expected_checksum_algo='md5',
                           disable_validation=True)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='1234',
                                           checksum_algo='md5',
                                           image_auth_data=None)
        mock_clean.assert_called_once_with('/foo', 100)
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        mock_remove.assert_not_called()
        mock_show.assert_not_called()
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_not_called()

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_part_already_exists(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_exists, mock_remove, mock_image_show,
            mock_format_inspector):
        image_check = mock.MagicMock()
        image_check.__str__.side_effect = iter(['qcow2', 'raw'])
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_exists.return_value = True
        mock_size.return_value = 100
        mock_image_show.return_value = {}
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_format=None, expected_checksum='f00',
                           expected_checksum_algo='sha256')
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='f00',
                                           checksum_algo='sha256',
                                           image_auth_data=None)
        mock_clean.assert_called_once_with('/foo', 100)
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        self.assertEqual(1, mock_exists.call_count)
        self.assertEqual(1, mock_remove.call_count)
        mock_image_show.assert_called_once_with('fake', 'fake-uuid',
                                                image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(os, 'rename', autospec=True)
    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_already_raw(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_show, mock_format_inspector,
            mock_rename):
        mock_show.return_value = {'disk_format': 'raw'}
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'raw'
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_checksum='e00',
                           expected_checksum_algo='sha256')
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='e00',
                                           checksum_algo='sha256',
                                           image_auth_data=None)
        mock_clean.assert_not_called()
        mock_size.assert_not_called()
        mock_raw.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)
        mock_rename.assert_called_once_with('/foo/bar.part', '/foo/bar')

    @mock.patch.object(os, 'rename', autospec=True)
    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_already_gpt(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_show, mock_format_inspector,
            mock_rename):
        mock_show.return_value = {'disk_format': 'raw'}
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'gpt'
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True,
                           expected_checksum='e00',
                           expected_checksum_algo='sha256')
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='e00',
                                           checksum_algo='sha256',
                                           image_auth_data=None)
        mock_clean.assert_not_called()
        mock_size.assert_not_called()
        mock_raw.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)
        mock_rename.assert_called_once_with('/foo/bar.part', '/foo/bar')

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_format_does_not_match_glance(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_show, mock_format_inspector):
        mock_show.return_value = {'disk_format': 'raw'}
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'qcow2'
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        self.assertRaises(exception.InvalidImage,
                          image_cache._fetch,
                          'fake', 'fake-uuid',
                          '/foo/bar', force_raw=True,
                          expected_format=None,
                          expected_checksum='a00',
                          expected_checksum_algo='sha512')
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum='a00',
                                           checksum_algo='sha512',
                                           image_auth_data=None)
        mock_clean.assert_not_called()
        mock_size.assert_not_called()
        mock_raw.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_not_safe_image(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_show, mock_format_inspector):
        mock_show.return_value = {'disk_format': 'qcow2'}
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'qcow2'
        image_check.safety_check.side_effect = \
            image_format_inspector.SafetyCheckFailed({"I'm a teapot": True})
        mock_format_inspector.return_value = image_check
        self.assertRaises(exception.InvalidImage,
                          image_cache._fetch,
                          'fake', 'fake-uuid',
                          '/foo/bar', force_raw=True)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum=None, checksum_algo=None,
                                           image_auth_data=None)
        mock_clean.assert_not_called()
        mock_size.assert_not_called()
        mock_raw.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(0, image_check.__str__.call_count)

    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_estimate_fallback(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_show, mock_format_inspector):
        mock_show.return_value = {'disk_format': 'qcow2'}
        image_check = mock.MagicMock()
        image_check.__str__.side_effect = iter(['qcow2', 'raw'])
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_size.side_effect = [100, 10]
        mock_clean.side_effect = [exception.InsufficientDiskSpace(), None]

        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum=None, checksum_algo=None,
                                           image_auth_data=None)
        mock_size.assert_has_calls([
            mock.call('/foo/bar.part', estimate=False),
            mock.call('/foo/bar.part', estimate=True),
        ])
        mock_clean.assert_has_calls([
            mock.call('/foo', 100),
            mock.call('/foo', 10),
        ])
        mock_raw.assert_called_once_with('fake-uuid', '/foo/bar',
                                         '/foo/bar.part')
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)

    @mock.patch.object(os, 'rename', autospec=True)
    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_ramdisk_kernel(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector,
            mock_rename):
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'raw'
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {'disk_format': 'aki'}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum=None, checksum_algo=None,
                                           image_auth_data=None)
        mock_clean.assert_not_called()
        mock_raw.assert_not_called()
        mock_remove.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)
        mock_rename.assert_called_once_with('/foo/bar.part', '/foo/bar')

    @mock.patch.object(os, 'rename', autospec=True)
    @mock.patch.object(images, 'detect_file_format', autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(os, 'remove', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(image_cache, '_clean_up_caches', autospec=True)
    def test__fetch_ramdisk_image(
            self, mock_clean, mock_raw, mock_fetch,
            mock_size, mock_remove, mock_show, mock_format_inspector,
            mock_rename):
        image_check = mock.MagicMock()
        image_check.__str__.return_value = 'raw'
        image_check.safety_check.return_value = True
        mock_format_inspector.return_value = image_check
        mock_show.return_value = {'disk_format': 'ari'}
        mock_size.return_value = 100
        image_cache._fetch('fake', 'fake-uuid', '/foo/bar', force_raw=True)
        mock_fetch.assert_called_once_with('fake', 'fake-uuid',
                                           '/foo/bar.part', force_raw=False,
                                           checksum=None, checksum_algo=None,
                                           image_auth_data=None)
        mock_clean.assert_not_called()
        mock_raw.assert_not_called()
        mock_remove.assert_not_called()
        mock_show.assert_called_once_with('fake', 'fake-uuid',
                                          image_auth_data=None)
        mock_format_inspector.assert_called_once_with('/foo/bar.part')
        image_check.safety_check.assert_called_once()
        self.assertEqual(1, image_check.__str__.call_count)
        mock_rename.assert_called_once_with('/foo/bar.part', '/foo/bar')
