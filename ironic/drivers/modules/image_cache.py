# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""
Utility for caching master images.
"""

import os
import shutil
import tempfile
import threading
import time
import uuid

from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import fileutils

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import images
from ironic.common import utils
from ironic.conf import CONF


LOG = logging.getLogger(__name__)

# This would contain a sorted list of instances of ImageCache to be
# considered for cleanup. This list will be kept sorted in non-increasing
# order of priority.
_cache_cleanup_list = []


_concurrency_semaphore = threading.Semaphore(CONF.image_download_concurrency)


class ImageCache(object):
    """Class handling access to cache for master images."""

    def __init__(self, master_dir, cache_size, cache_ttl,
                 disable_validation=False, force_raw=True):
        """Constructor.

        :param master_dir: cache directory to work on
                           Value of None disables image caching.
        :param cache_size: desired maximum cache size in bytes
        :param cache_ttl: cache entity TTL in seconds
        :param disable_validation: disable security checks on cached images
        """
        self.master_dir = master_dir
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl
        self._force_raw = force_raw
        self._disable_validation = disable_validation
        if master_dir is not None:
            fileutils.ensure_tree(master_dir)

    def fetch_image(self, href, dest_path, ctx=None, force_raw=None,
                    expected_format=None, expected_checksum=None,
                    expected_checksum_algo=None,
                    image_auth_data=None):
        """Fetch image by given href to the destination path.

        Does nothing if destination path exists and is up to date with cache
        and href contents.
        Only creates a hard link (dest_path) to cached image if requested
        image is already in cache and up to date with href contents.
        Otherwise downloads an image, stores it in cache and creates a hard
        link (dest_path) to it.

        :param href: image UUID or href to fetch
        :param dest_path: destination file path
        :param ctx: context
        :param force_raw: boolean value, whether to convert the image to raw
                          format
        :param expected_format: The expected image format.
        :param expected_checksum: The expected image checksum
        :param expected_checksum_algo: The expected image checksum algorithm,
                                       if needed/supplied.
        """
        force_raw = force_raw if force_raw is not None else self._force_raw
        if expected_format is not None and self._disable_validation:
            raise AssertionError("BUG: passing expected_format to caches with "
                                 "disabled validation makes no sense")
        img_download_lock_name = 'download-image'
        if self.master_dir is None:
            # NOTE(ghe): We don't share images between instances/hosts
            # NOTE(TheJulia): These is a weird code path, because master_dir
            # has to be None, which by default it never should be unless
            # an operator forces it to None, which is a path we just never
            # expect.
            # TODO(TheJulia): This may be dead-ish code and likely needs
            # to be removed. Likely originated *out* of just the iscsi
            # deployment interface and local image caching.
            if not CONF.parallel_image_downloads:
                with lockutils.lock(img_download_lock_name):
                    _fetch(ctx, href, dest_path, force_raw,
                           expected_format=expected_format,
                           expected_checksum=expected_checksum,
                           expected_checksum_algo=expected_checksum_algo,
                           disable_validation=self._disable_validation,
                           image_auth_data=image_auth_data)
            else:
                with _concurrency_semaphore:
                    _fetch(ctx, href, dest_path, force_raw,
                           expected_format=expected_format,
                           expected_checksum=expected_checksum,
                           expected_checksum_algo=expected_checksum_algo,
                           disable_validation=self._disable_validation,
                           image_auth_data=image_auth_data)
            return

        # TODO(ghe): have hard links and counts the same behaviour in all fs

        # NOTE(vdrok): File name is converted to UUID if it's not UUID already,
        # so that two images with same file names do not collide
        if service_utils.is_glance_image(href):
            master_file_name = service_utils.parse_image_id(href)
        else:
            master_file_name = str(uuid.uuid5(uuid.NAMESPACE_URL, href))
        # NOTE(kaifeng) The ".converted" suffix acts as an indicator that the
        # image cached has gone through the conversion logic.
        if force_raw:
            master_file_name = master_file_name + '.converted'

        master_path = os.path.join(self.master_dir, master_file_name)

        if CONF.parallel_image_downloads:
            img_download_lock_name = 'download-image:%s' % master_file_name

        # TODO(dtantsur): lock expiration time
        with lockutils.lock(img_download_lock_name):
            img_service = image_service.get_image_service(href, context=ctx)
            if img_service.is_auth_set_needed:
                # We need to possibly authenticate based on what a user
                # has supplied, so we'll send that along.
                img_service.set_image_auth(href, image_auth_data)
            img_info = img_service.show(href)
            # NOTE(vdrok): After rebuild requested image can change, so we
            # should ensure that dest_path and master_path (if exists) are
            # pointing to the same file and their content is up to date
            cache_up_to_date = _delete_master_path_if_stale(master_path, href,
                                                            img_info)
            dest_up_to_date = _delete_dest_path_if_stale(master_path,
                                                         dest_path)

            if cache_up_to_date and dest_up_to_date:
                LOG.debug("Destination %(dest)s already exists "
                          "for image %(href)s",
                          {'href': href, 'dest': dest_path})
                return

            if cache_up_to_date:
                # NOTE(dtantsur): ensure we're not in the middle of clean up
                with lockutils.lock('master_image'):
                    try:
                        os.link(master_path, dest_path)
                    except OSError as exc:
                        LOG.debug(
                            "Could not hardlink image file %(image)s to "
                            "the cache location %(dest_path)s (will copy it "
                            "over): %(error)s", {
                                'image': master_path,
                                'dest_path': dest_path,
                                'error': exc})
                        shutil.copyfile(master_path, dest_path)
                LOG.debug("Master cache hit for image %(href)s",
                          {'href': href})
                return

            LOG.info("Master cache miss for image %(href)s, will download",
                     {'href': href})
            self._download_image(
                href, master_path, dest_path, img_info,
                ctx=ctx, force_raw=force_raw,
                expected_format=expected_format,
                expected_checksum=expected_checksum,
                expected_checksum_algo=expected_checksum_algo,
                image_auth_data=image_auth_data)

        # NOTE(dtantsur): we increased cache size - time to clean up
        self.clean_up()

    def _download_image(self, href, master_path, dest_path, img_info,
                        ctx=None, force_raw=None, expected_format=None,
                        expected_checksum=None, expected_checksum_algo=None,
                        image_auth_data=None):
        """Download image by href and store at a given path.

        This method should be called with uuid-specific lock taken.

        :param href: image UUID or href to fetch
        :param master_path: destination master path
        :param dest_path: destination file path
        :param img_info: image information from the image service
        :param ctx: context
        :param force_raw: boolean value, whether to convert the image to raw
                          format
        :param expected_format: The expected original format for the image.
        :param expected_checksum: The expected image checksum.
        :param expected_checksum_algo: The expected image checksum algorithm.
        :param image_auth_data: Dictionary with credential details which may be
                                required to download the file.
        :raise ImageDownloadFailed: when the image cache and the image HTTP or
                                    TFTP location are on different file system,
                                    causing hard link to fail.
        """
        # TODO(ghe): timeout and retry for downloads
        # TODO(ghe): logging when image cannot be created
        tmp_dir = tempfile.mkdtemp(dir=self.master_dir)
        tmp_path = os.path.join(tmp_dir, os.path.basename(master_path))
        force_raw = force_raw if force_raw is not None else self._force_raw
        try:
            with _concurrency_semaphore:
                _fetch(ctx, href, tmp_path, force_raw, expected_format,
                       expected_checksum=expected_checksum,
                       expected_checksum_algo=expected_checksum_algo,
                       disable_validation=self._disable_validation,
                       image_auth_data=image_auth_data)

            if img_info.get('no_cache'):
                LOG.debug("Caching is disabled for image %s", href)
                # Cache disabled, link directly to destination
                os.link(tmp_path, dest_path)
            else:
                # NOTE(dtantsur): no need for global lock here - master_path
                # will have link count >1 at any moment, so won't be cleaned up
                os.link(tmp_path, master_path)
                os.link(master_path, dest_path)
        except OSError as exc:
            msg = (_("Could not link image %(img_href)s from %(src_path)s "
                     "to %(dst_path)s, error: %(exc)s") %
                   {'img_href': href, 'src_path': master_path,
                    'dst_path': dest_path, 'exc': exc})
            LOG.error(msg)
            raise exception.ImageDownloadFailed(msg)
        finally:
            utils.rmtree_without_raise(tmp_dir)

    @lockutils.synchronized('master_image')
    def clean_up(self, amount=None):
        """Clean up directory with images, keeping cache of the latest images.

        Files with link count >1 are never deleted.
        Protected by global lock, so that no one messes with master images
        after we get listing and before we actually delete files.

        :param amount: if present, amount of space to reclaim in bytes,
                       cleaning will stop, if this goal was reached,
                       even if it is possible to clean up more files
        """
        if self.master_dir is None:
            return

        LOG.debug("Starting clean up for master image cache %(dir)s",
                  {'dir': self.master_dir})

        amount_copy = amount
        listing = _find_candidates_for_deletion(self.master_dir)
        survived, amount = self._clean_up_too_old(listing, amount)
        if amount is not None and amount <= 0:
            return
        amount = self._clean_up_ensure_cache_size(survived, amount)
        if amount is not None and amount > 0:
            LOG.warning("Cache clean up was unable to reclaim %(required)d "
                        "MiB of disk space, still %(left)d MiB required",
                        {'required': amount_copy / 1024 / 1024,
                         'left': amount / 1024 / 1024})

    def _clean_up_too_old(self, listing, amount):
        """Clean up stage 1: drop images that are older than TTL.

        This method removes files all files older than TTL seconds
        unless 'amount' is non-None. If 'amount' is non-None,
        it starts removing files older than TTL seconds,
        oldest first, until the required 'amount' of space is reclaimed.

        :param listing: list of tuples (file name, last used time)
        :param amount: if not None, amount of space to reclaim in bytes,
                       cleaning will stop, if this goal was reached,
                       even if it is possible to clean up more files
        :returns: tuple (list of files left after clean up,
                         amount still to reclaim)
        """
        threshold = time.time() - self._cache_ttl
        survived = []
        count = 0
        for file_name, last_used, stat in listing:
            if last_used < threshold:
                try:
                    os.unlink(file_name)
                except EnvironmentError as exc:
                    LOG.warning("Unable to delete file %(name)s from "
                                "master image cache: %(exc)s",
                                {'name': file_name, 'exc': exc})
                else:
                    count += 1
                    if amount is not None:
                        amount -= stat.st_size
                        if amount <= 0:
                            amount = 0
                            break
            else:
                survived.append((file_name, last_used, stat))
        if count:
            LOG.debug('Removed %(count)d expired file(s) from %(dir)s',
                      {'count': count, 'dir': self.master_dir})
        return survived, amount

    def _clean_up_ensure_cache_size(self, listing, amount):
        """Clean up stage 2: try to ensure cache size < threshold.

        Try to delete the oldest files until conditions is satisfied
        or no more files are eligible for deletion.

        :param listing: list of tuples (file name, last used time)
        :param amount: amount of space to reclaim, if possible.
                       if amount is not None, it has higher priority than
                       cache size in settings
        :returns: amount of space still required after clean up
        """
        # NOTE(dtantsur): Sort listing to delete the oldest files first
        listing = sorted(listing,
                         key=lambda entry: entry[1],
                         reverse=True)
        total_listing = (os.path.join(self.master_dir, f)
                         for f in os.listdir(self.master_dir))
        total_size = sum(os.path.getsize(f)
                         for f in total_listing)
        count = 0
        while listing and (total_size > self._cache_size
                           or (amount is not None and amount > 0)):
            file_name, last_used, stat = listing.pop()
            try:
                os.unlink(file_name)
            except EnvironmentError as exc:
                LOG.warning("Unable to delete file %(name)s from "
                            "master image cache: %(exc)s",
                            {'name': file_name, 'exc': exc})
            else:
                total_size -= stat.st_size
                count += 1
                if amount is not None:
                    amount -= stat.st_size

        if total_size > self._cache_size:
            LOG.info("After cleaning up cache dir %(dir)s "
                     "cache size %(actual)d is still larger than "
                     "threshold %(expected)d",
                     {'dir': self.master_dir, 'actual': total_size,
                      'expected': self._cache_size})
        elif count:
            LOG.debug(
                'Removed %(count)d file(s) from %(dir)s to free up space',
                {'count': count, 'dir': self.master_dir})
        return max(amount, 0) if amount is not None else 0


def _find_candidates_for_deletion(master_dir):
    """Find files eligible for deletion i.e. with link count ==1.

    :param master_dir: directory to operate on
    :returns: iterator yielding tuples (file name, last used time, stat)
    """
    for filename in os.listdir(master_dir):
        filename = os.path.join(master_dir, filename)
        stat = os.stat(filename)
        if not os.path.isfile(filename) or stat.st_nlink > 1:
            continue
        # NOTE(dtantsur): Detect most recently accessed files,
        # seeing atime can be disabled by the mount option
        # Also include ctime as it changes when image is linked to
        last_used_time = max(stat.st_mtime, stat.st_atime, stat.st_ctime)
        yield filename, last_used_time, stat


def _free_disk_space_for(path):
    """Get free disk space on a drive where path is located."""
    stat = os.statvfs(path)
    return stat.f_frsize * stat.f_bavail


def _fetch(context, image_href, path, force_raw=False,
           expected_format=None, expected_checksum=None,
           expected_checksum_algo=None,
           disable_validation=False, image_auth_data=None):
    """Fetch image and convert to raw format if needed."""
    assert not (disable_validation and expected_format)
    path_tmp = "%s.part" % path
    if os.path.exists(path_tmp):
        LOG.warning("%s exist, assuming it's stale", path_tmp)
        os.remove(path_tmp)
    images.fetch(context, image_href, path_tmp, force_raw=False,
                 checksum=expected_checksum,
                 checksum_algo=expected_checksum_algo,
                 image_auth_data=image_auth_data)
    # By default, the image format is unknown
    image_format = None
    disable_dii = (disable_validation
                   or CONF.conductor.disable_deep_image_inspection)
    if not disable_dii:
        if not expected_format:
            # Call of last resort to check the image format. Caching other
            # artifacts like kernel/ramdisks are not going to have an expected
            # format known even if they are not passed to qemu-img.
            remote_image_format = images.image_show(
                context,
                image_href,
                image_auth_data=image_auth_data).get('disk_format')
        else:
            remote_image_format = expected_format
        image_format = images.safety_check_image(path_tmp)
        images.check_if_image_format_is_permitted(
            image_format, remote_image_format)

    # Notes(yjiang5): If glance can provide the virtual size information,
    # then we can firstly clean cache and then invoke images.fetch().
    if (force_raw
            and ((disable_dii
                 and images.force_raw_will_convert(image_href, path_tmp))
                 or (not disable_dii
                     and image_format not in images.RAW_IMAGE_FORMATS))):
        # NOTE(TheJulia): What is happening here is the rest of the logic
        # is hinged on force_raw, but also we don't need to take the entire
        # path *if* the image on disk is *already* raw. Depending on settings,
        # the path differs slightly because if we have deep image inspection,
        # we can just rely upon the inspection image format, otherwise we
        # need to ask the image format.

        required_space = images.converted_size(path_tmp, estimate=False)
        directory = os.path.dirname(path_tmp)
        try:
            _clean_up_caches(directory, required_space)
        except exception.InsufficientDiskSpace:

            # try again with an estimated raw size instead of the full size
            required_space = images.converted_size(path_tmp, estimate=True)
            try:
                _clean_up_caches(directory, required_space)
            except exception.InsufficientDiskSpace:
                LOG.error('Not enough space for estimated image size. '
                          'Consider lowering '
                          '[DEFAULT]raw_image_growth_factor=%s',
                          CONF.raw_image_growth_factor)
                raise
        images.image_to_raw(image_href, path, path_tmp)
    else:
        os.rename(path_tmp, path)


def _clean_up_caches(directory, amount):
    """Explicitly cleanup caches based on their priority (if required).

    :param directory: the directory (of the cache) to be freed up.
    :param amount: amount of space to reclaim.
    :raises: InsufficientDiskSpace exception, if we cannot free up enough space
             after trying all the caches.
    """
    free = _free_disk_space_for(directory)

    if amount < free:
        return

    # NOTE(dtantsur): filter caches, whose directory is on the same device
    st_dev = os.stat(directory).st_dev

    caches_to_clean = [x[1]() for x in _cache_cleanup_list]
    caches = (c for c in caches_to_clean
              if os.stat(c.master_dir).st_dev == st_dev)
    for cache_to_clean in caches:
        cache_to_clean.clean_up(amount=(amount - free))
        free = _free_disk_space_for(directory)
        if amount < free:
            break
    else:
        raise exception.InsufficientDiskSpace(path=directory,
                                              required=amount / 1024 / 1024,
                                              actual=free / 1024 / 1024,
                                              )


def clean_up_caches(ctx, directory, images_info, image_auth_data=None):
    """Explicitly cleanup caches based on their priority (if required).

    This cleans up the caches to free up the amount of space required for the
    images in images_info. The caches are cleaned up one after the other in
    the order of their priority.  If we still cannot free up enough space
    after trying all the caches, this method throws exception.

    :param ctx: context
    :param directory: the directory (of the cache) to be freed up.
    :param images_info: a list of tuples of the form (image_uuid,path)
                        for which space is to be created in cache.
    :raises: InsufficientDiskSpace exception, if we cannot free up enough space
             after trying all the caches.
    """
    total_size = sum(images.download_size(ctx, uuid,
                                          image_auth_data=image_auth_data)
                     for (uuid, path) in images_info)
    _clean_up_caches(directory, total_size)


def clean_up_all():
    """Clean up all entries from all caches."""
    caches_to_clean = [x[1]() for x in _cache_cleanup_list]
    for cache in caches_to_clean:
        cache.clean_up()


def cleanup(priority):
    """Decorator method for adding cleanup priority to a class."""
    def _add_property_to_class_func(cls):
        _cache_cleanup_list.append((priority, cls))
        _cache_cleanup_list.sort(reverse=True, key=lambda tuple_: tuple_[0])
        return cls

    return _add_property_to_class_func


def _delete_master_path_if_stale(master_path, href, img_info):
    """Delete image from cache if it is not up to date with href contents.

    :param master_path: path to an image in master cache
    :param href: image href
    :param img_info: image information from the service
    :returns: True if master_path is up to date with href contents,
        False if master_path was stale and was deleted or it didn't exist
    """
    if service_utils.is_glance_image(href):
        # Glance image contents cannot be updated without changing image's UUID
        return os.path.exists(master_path)
    if image_service.is_container_registry_url(href):
        # OCI Images cannot be changed without changing the digest values.
        return os.path.exists(master_path)
    if os.path.exists(master_path):
        img_mtime = img_info.get('updated_at')
        if not img_mtime:
            # This means that href is not a glance image and doesn't have an
            # updated_at attribute. To play on the safe side, redownload the
            # master copy of the image.
            LOG.warning("Image service couldn't determine last "
                        "modification time of %(href)s, updating "
                        "the cached copy %(cached_file)s.",
                        {'href': href, 'cached_file': master_path})
        else:
            master_mtime = utils.unix_file_modification_datetime(master_path)
            if img_mtime <= master_mtime:
                return True
            # Delete image from cache as it is outdated
            LOG.info('Image %(href)s was last modified at %(remote_time)s. '
                     'Deleting the cached copy "%(cached_file)s since it was '
                     'last modified at %(local_time)s and may be outdated.',
                     {'href': href, 'remote_time': img_mtime,
                      'local_time': master_mtime, 'cached_file': master_path})

        os.unlink(master_path)
    return False


def _delete_dest_path_if_stale(master_path, dest_path):
    """Delete dest_path if it does not point to cached image.

    :param master_path: path to an image in master cache
    :param dest_path: hard link to an image
    :returns: True if dest_path points to master_path, False if dest_path was
        stale and was deleted or it didn't exist
    """
    dest_path_exists = os.path.exists(dest_path)
    if not dest_path_exists:
        # Image not cached, re-download
        return False
    master_path_exists = os.path.exists(master_path)
    if (not master_path_exists
            or os.stat(master_path).st_ino != os.stat(dest_path).st_ino):
        # Image exists in cache, but dest_path out of date
        os.unlink(dest_path)
        return False
    return True
