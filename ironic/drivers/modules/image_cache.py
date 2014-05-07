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
import tempfile
import time

from oslo.config import cfg

from ironic.common.glance_service import service_utils
from ironic.common import images
from ironic.common import utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import lockutils
from ironic.openstack.common import log as logging


LOG = logging.getLogger(__name__)

img_cache_opts = [
    cfg.BoolOpt('parallel_image_downloads',
                default=False,
                help='Run image downloads and raw format conversions in '
                     'parallel.'),
]

CONF = cfg.CONF
CONF.register_opts(img_cache_opts)


class ImageCache(object):
    """Class handling access to cache for master images."""

    def __init__(self, master_dir, cache_size, cache_ttl,
                 image_service=None):
        """Constructor.

        :param master_dir: cache directory to work on
        :param cache_size: desired maximum cache size in bytes
        :param cache_ttl: cache entity TTL in seconds
        :param image_service: Glance image service to use, None for default
        """
        self.master_dir = master_dir
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl
        self._image_service = image_service
        if master_dir is not None:
            fileutils.ensure_tree(master_dir)

    def fetch_image(self, uuid, dest_path, ctx=None):
        """Fetch image with given uuid to the destination path.

        Does nothing if destination path exists.
        Only creates a link if master image for this UUID is already in cache.
        Otherwise downloads an image and also stores it in cache.

        :param uuid: image UUID or href to fetch
        :param dest_path: destination file path
        :param ctx: context
        """
        img_download_lock_name = 'download-image'
        if self.master_dir is None:
            #NOTE(ghe): We don't share images between instances/hosts
            if not CONF.parallel_image_downloads:
                with lockutils.lock(img_download_lock_name, 'ironic-'):
                    images.fetch_to_raw(ctx, uuid, dest_path,
                                        self._image_service)
            else:
                images.fetch_to_raw(ctx, uuid, dest_path,
                                    self._image_service)
            return

        #TODO(ghe): have hard links and counts the same behaviour in all fs

        master_file_name = service_utils.parse_image_ref(uuid)[0]
        master_path = os.path.join(self.master_dir, master_file_name)

        if CONF.parallel_image_downloads:
            img_download_lock_name = 'download-image:%s' % master_file_name

        # TODO(dtantsur): lock expiration time
        with lockutils.lock(img_download_lock_name, 'ironic-'):
            if os.path.exists(dest_path):
                LOG.debug("Destination %(dest)s already exists for "
                            "image %(uuid)s" %
                          {'uuid': uuid,
                           'dest': dest_path})
                return

            try:
                # NOTE(dtantsur): ensure we're not in the middle of clean up
                with lockutils.lock('master_image', 'ironic-'):
                    os.link(master_path, dest_path)
            except OSError:
                LOG.info(_("Master cache miss for image %(uuid)s, "
                           "starting download") %
                         {'uuid': uuid})
            else:
                LOG.debug("Master cache hit for image %(uuid)s",
                          {'uuid': uuid})
                return

            self._download_image(uuid, master_path, dest_path, ctx=ctx)

        # NOTE(dtantsur): we increased cache size - time to clean up
        self.clean_up()

    def _download_image(self, uuid, master_path, dest_path, ctx=None):
        """Download image from Glance and store at a given path.
        This method should be called with uuid-specific lock taken.

        :param uuid: image UUID or href to fetch
        :param master_path: destination master path
        :param dest_path: destination file path
        :param ctx: context
        """
        #TODO(ghe): timeout and retry for downloads
        #TODO(ghe): logging when image cannot be created
        fd, tmp_path = tempfile.mkstemp(dir=self.master_dir)
        os.close(fd)
        images.fetch_to_raw(ctx, uuid, tmp_path,
                            self._image_service)
        # NOTE(dtantsur): no need for global lock here - master_path
        # will have link count >1 at any moment, so won't be cleaned up
        os.link(tmp_path, master_path)
        os.link(master_path, dest_path)
        os.unlink(tmp_path)

    @lockutils.synchronized('master_image', 'ironic-')
    def clean_up(self):
        """Clean up directory with images, keeping cache of the latest images.

        Files with link count >1 are never deleted.
        Protected by global lock, so that no one messes with master images
        after we get listing and before we actually delete files.
        """
        if self.master_dir is None:
            return

        LOG.debug("Starting clean up for master image cache %(dir)s" %
                  {'dir': self.master_dir})

        listing = _find_candidates_for_deletion(self.master_dir)
        survived = self._clean_up_too_old(listing)
        self._clean_up_ensure_cache_size(survived)

    def _clean_up_too_old(self, listing):
        """Clean up stage 1: drop images that are older than TTL.

        :param listing: list of tuples (file name, last used time)
        :returns: list of files left after clean up
        """
        threshold = time.time() - self._cache_ttl
        survived = []
        for file_name, last_used, stat in listing:
            if last_used < threshold:
                utils.unlink_without_raise(file_name)
            else:
                survived.append((file_name, last_used, stat))
        return survived

    def _clean_up_ensure_cache_size(self, listing):
        """Clean up stage 2: try to ensure cache size < threshold.
        Try to delete the oldest files until conditions is satisfied
        or no more files are eligable for delition.

        :param listing: list of tuples (file name, last used time)
        """
        # NOTE(dtantsur): Sort listing to delete the oldest files first
        listing = sorted(listing,
                         key=lambda entry: entry[1],
                         reverse=True)
        total_listing = (os.path.join(self.master_dir, f)
                         for f in os.listdir(self.master_dir))
        total_size = sum(os.path.getsize(f)
                         for f in total_listing)
        while total_size > self._cache_size and listing:
            file_name, last_used, stat = listing.pop()
            try:
                os.unlink(file_name)
            except EnvironmentError as exc:
                LOG.warn(_("Unable to delete file %(name)s from "
                           "master image cache: %(exc)s") %
                         {'name': file_name, 'exc': exc})
            else:
                total_size -= stat.st_size

        if total_size > self._cache_size:
            LOG.info(_("After cleaning up cache dir %(dir)s "
                       "cache size %(actual)d is still larger than "
                       "threshold %(expected)d") %
                     {'dir': self.master_dir, 'actual': total_size,
                      'expected': self._cache_size})


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
