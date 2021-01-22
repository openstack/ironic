# Copyright 2010 OpenStack Foundation
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


import abc
import datetime
from http import client as http_client
import os
import shutil
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import requests

from ironic.common import exception
from ironic.common.glance_service.image_service import GlanceImageService
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1mb
# NOTE(kaifeng) Image will be truncated to 2GiB by sendfile,
# we use a large chunk size here for a better performance
# while keep the chunk size less than the size limit.
SENDFILE_CHUNK_SIZE = 1024 * 1024 * 1024  # 1Gb
LOG = log.getLogger(__name__)


class BaseImageService(object, metaclass=abc.ABCMeta):
    """Provides retrieval of disk images."""

    @abc.abstractmethod
    def validate_href(self, image_href):
        """Validate image reference.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed.
        :returns: Information needed to further operate with an image.
        """

    @abc.abstractmethod
    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed.
        :raises: exception.ImageDownloadFailed.
        """

    @abc.abstractmethod
    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed.
        :returns: dictionary of image properties. It has three of them: 'size',
            'updated_at' and 'properties'. 'updated_at' attribute is a naive
            UTC datetime object.
        """


class HttpImageService(BaseImageService):
    """Provides retrieval of disk images using HTTP."""

    def validate_href(self, image_href, secret=False):
        """Validate HTTP image reference.

        :param image_href: Image reference.
        :param secret: Specify if image_href being validated should not be
            shown in exception message.
        :raises: exception.ImageRefValidationFailed if HEAD request failed or
            returned response code not equal to 200.
        :returns: Response to HEAD request.
        """
        output_url = 'secreturl' if secret else image_href

        try:
            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        try:
            response = requests.head(image_href, verify=verify,
                                     timeout=CONF.webserver_connection_timeout)
            if response.status_code != http_client.OK:
                raise exception.ImageRefValidationFailed(
                    image_href=output_url,
                    reason=_("Got HTTP code %s instead of 200 in response "
                             "to HEAD request.") % response.status_code)

        except (OSError, requests.ConnectionError,
                requests.RequestException) as e:
            raise exception.ImageRefValidationFailed(image_href=output_url,
                                                     reason=str(e))
        return response

    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed if GET request returned
            response code not equal to 200.
        :raises: exception.ImageDownloadFailed if:
            * IOError happened during file write;
            * GET request failed.
        """

        try:
            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        try:
            response = requests.get(image_href, stream=True, verify=verify,
                                    timeout=CONF.webserver_connection_timeout)
            if response.status_code != http_client.OK:
                raise exception.ImageRefValidationFailed(
                    image_href=image_href,
                    reason=_("Got HTTP code %s instead of 200 in response "
                             "to GET request.") % response.status_code)

            with response.raw as input_img:
                shutil.copyfileobj(input_img, image_file, IMAGE_CHUNK_SIZE)

        except (OSError, requests.ConnectionError, requests.RequestException,
                IOError) as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=str(e))

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if:
            * HEAD request failed;
            * HEAD request returned response code not equal to 200;
            * Content-Length header not found in response to HEAD request.
        :returns: dictionary of image properties. It has three of them: 'size',
            'updated_at' and 'properties'. 'updated_at' attribute is a naive
            UTC datetime object.
        """
        response = self.validate_href(image_href)
        image_size = response.headers.get('Content-Length')
        if image_size is None:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_("Cannot determine image size as there is no "
                         "Content-Length header specified in response "
                         "to HEAD request."))

        # Parse last-modified header to return naive datetime object
        str_date = response.headers.get('Last-Modified')
        date = None
        if str_date:
            http_date_format_strings = [
                '%a, %d %b %Y %H:%M:%S GMT',  # RFC 822
                '%A, %d-%b-%y %H:%M:%S GMT',  # RFC 850
                '%a %b %d %H:%M:%S %Y'        # ANSI C
            ]
            for fmt in http_date_format_strings:
                try:
                    date = datetime.datetime.strptime(str_date, fmt)
                    break
                except ValueError:
                    continue

        return {
            'size': int(image_size),
            'updated_at': date,
            'properties': {}
        }


class FileImageService(BaseImageService):
    """Provides retrieval of disk images available locally on the conductor."""

    def validate_href(self, image_href):
        """Validate local image reference.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if source image file
            doesn't exist.
        :returns: Path to image file if it exists.
        """
        image_path = urlparse.urlparse(image_href).path
        if not os.path.isfile(image_path):
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_("Specified image file not found."))
        return image_path

    def download(self, image_href, image_file):
        """Downloads image to specified location.

        :param image_href: Image reference.
        :param image_file: File object to write data to.
        :raises: exception.ImageRefValidationFailed if source image file
            doesn't exist.
        :raises: exception.ImageDownloadFailed if exceptions were raised while
            writing to file or creating hard link.
        """
        source_image_path = self.validate_href(image_href)
        dest_image_path = image_file.name
        local_device = os.stat(dest_image_path).st_dev
        try:
            # We should have read and write access to source file to create
            # hard link to it.
            if (local_device == os.stat(source_image_path).st_dev
                    and os.access(source_image_path, os.R_OK | os.W_OK)):
                image_file.close()
                os.remove(dest_image_path)
                os.link(source_image_path, dest_image_path)
            else:
                filesize = os.path.getsize(source_image_path)
                offset = 0
                with open(source_image_path, 'rb') as input_img:
                    while offset < filesize:
                        count = min(SENDFILE_CHUNK_SIZE, filesize - offset)
                        nbytes_out = os.sendfile(image_file.fileno(),
                                                 input_img.fileno(),
                                                 offset,
                                                 count)
                        offset += nbytes_out
        except Exception as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=str(e))

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if image file specified
            doesn't exist.
        :returns: dictionary of image properties. It has three of them: 'size',
            'updated_at' and 'properties'. 'updated_at' attribute is a naive
            UTC datetime object.
        """
        source_image_path = self.validate_href(image_href)
        return {
            'size': os.path.getsize(source_image_path),
            'updated_at': utils.unix_file_modification_datetime(
                source_image_path),
            'properties': {}
        }


protocol_mapping = {
    'http': HttpImageService,
    'https': HttpImageService,
    'file': FileImageService,
    'glance': GlanceImageService,
}


def get_image_service(image_href, client=None, context=None):
    """Get image service instance to download the image.

    :param image_href: String containing href to get image service for.
    :param client: Glance client to be used for download, used only if
        image_href is Glance href.
    :param context: request context, used only if image_href is Glance href.
    :raises: exception.ImageRefValidationFailed if no image service can
        handle specified href.
    :returns: Instance of an image service class that is able to download
        specified image.
    """
    scheme = urlparse.urlparse(image_href).scheme.lower()

    if not scheme:
        if uuidutils.is_uuid_like(str(image_href)):
            cls = GlanceImageService
        else:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_('Scheme-less image href is not a UUID.'))
    else:
        cls = protocol_mapping.get(scheme)
        if not cls:
            raise exception.ImageRefValidationFailed(
                image_href=image_href,
                reason=_('Image download protocol %s is not supported.'
                         ) % scheme)

    if cls == GlanceImageService:
        return cls(client, context)
    return cls()
