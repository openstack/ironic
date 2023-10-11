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

import abc
import os.path
import shutil
from urllib import parse as urlparse

from ironic_lib import utils as ironic_utils
from oslo_log import log

from ironic.common import exception
from ironic.common import swift
from ironic.common import utils
from ironic.conf import CONF

LOG = log.getLogger(__name__)


class AbstractPublisher(metaclass=abc.ABCMeta):
    """Abstract base class for publishing images via HTTP."""

    @abc.abstractmethod
    def publish(self, source_path, file_name=None):
        """Publish an image.

        :param source_path: Path to the source file.
        :param file_name: Destination file name. If None, the file component
            of source_path is used.
        :return: The HTTP URL of the published image.
        """

    @abc.abstractmethod
    def unpublish(self, file_name):
        """Unpublish the image.

        :param file_name: File name to unpublish.
        """


class LocalPublisher(AbstractPublisher):
    """Image publisher using a local web server."""

    def __init__(self, image_subdir=None, file_permission=0o644,
                 dir_permission=0o755, root_url=None):
        """Create a local publisher.

        :param image_subdir: A subdirectory to put the image to.
            Using an empty directory may cause name conflicts.
        :param file_permission: Permissions for copied files.
        :param dir_permission: Permissions for created directories.
        :param root_url: Public URL of the web server. If empty, determined
            from the configuration.
        """
        self.image_subdir = image_subdir
        self.root_url = (root_url or CONF.deploy.external_http_url
                         or CONF.deploy.http_url)
        self.file_permission = file_permission
        self.dir_permission = dir_permission

    def publish(self, source_path, file_name=None):
        if not file_name:
            file_name = os.path.basename(source_path)

        if self.image_subdir:
            public_dir = os.path.join(CONF.deploy.http_root, self.image_subdir)
        else:
            public_dir = CONF.deploy.http_root

        if not os.path.exists(public_dir):
            os.mkdir(public_dir, self.dir_permission)

        published_file = os.path.join(public_dir, file_name)

        try:
            os.link(source_path, published_file)
            os.chmod(source_path, self.file_permission)
            try:
                utils.execute(
                    '/usr/sbin/restorecon', '-i', '-R', 'v', public_dir)
            except FileNotFoundError as exc:
                LOG.debug(
                    "Could not restore SELinux context on "
                    "%(public_dir)s, restorecon command not found.\n"
                    "Error: %(error)s",
                    {'public_dir': public_dir,
                        'error': exc})

        except OSError as exc:
            LOG.debug(
                "Could not hardlink image file %(image)s to public "
                "location %(public)s (will copy it over): "
                "%(error)s", {'image': source_path,
                              'public': published_file,
                              'error': exc})

            shutil.copyfile(source_path, published_file)
            os.chmod(published_file, self.file_permission)

        if self.image_subdir:
            return os.path.join(self.root_url, self.image_subdir, file_name)
        else:
            return os.path.join(self.root_url, file_name)

    def unpublish(self, file_name):
        published_file = os.path.join(
            CONF.deploy.http_root, self.image_subdir, file_name)
        ironic_utils.unlink_without_raise(published_file)


class SwiftPublisher(AbstractPublisher):
    """Image publisher using OpenStack Swift."""

    def __init__(self, container, delete_after):
        """Create a Swift publisher.

        :param container: Swift container to use.
        :param delete_after: Number of seconds after which the link will
            no longer be valid.
        """
        self.container = container
        self.delete_after = delete_after

    def _append_filename_param(self, url, filename):
        """Append 'filename=<file>' parameter to given URL.

        Some BMCs seem to validate boot image URL requiring the URL to end
        with something resembling ISO image file name.

        This function tries to add, hopefully, meaningless 'filename'
        parameter to URL's query string in hope to make the entire boot image
        URL looking more convincing to the BMC.

        However, `url` with fragments might not get cured by this hack.

        :param url: a URL to work on
        :param filename: name of the file to append to the URL
        :returns: original URL with 'filename' parameter appended
        """
        parsed_url = urlparse.urlparse(url)
        parsed_qs = urlparse.parse_qsl(parsed_url.query)

        has_filename = [x for x in parsed_qs if x[0].lower() == 'filename']
        if has_filename:
            return url

        parsed_qs.append(('filename', filename))
        parsed_url = list(parsed_url)
        parsed_url[4] = urlparse.urlencode(parsed_qs)

        return urlparse.urlunparse(parsed_url)

    def publish(self, source_path, file_name=None):
        api = swift.SwiftAPI()
        if not file_name:
            file_name = os.path.basename(source_path)

        object_headers = {'X-Delete-After': str(self.delete_after)}
        api.create_object(self.container, file_name, source_path,
                          object_headers=object_headers)

        image_url = api.get_temp_url(self.container, file_name,
                                     self.delete_after)
        return self._append_filename_param(
            image_url, os.path.basename(source_path))

    def unpublish(self, file_name):
        api = swift.SwiftAPI()
        LOG.debug("Cleaning up image %(name)s from Swift container "
                  "%(container)s", {'name': file_name,
                                    'container': self.container})

        try:
            api.delete_object(self.container, file_name)

        except exception.SwiftOperationError as exc:
            LOG.warning("Failed to clean up image %(image)s. Error: "
                        "%(error)s.", {'image': file_name, 'error': exc})
