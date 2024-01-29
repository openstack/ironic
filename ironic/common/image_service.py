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
        :raises: exception.ImageRefIsARedirect if the supplied URL is a
            redirect to a different URL. The caller may be able to handle
            this.
        :returns: Response to HEAD request.
        """
        output_url = 'secreturl' if secret else image_href

        try:
            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        try:
            # NOTE(TheJulia): Head requests do not work on things that are not
            # files, but they can be responded with redirects or a 200 OK....
            # We don't want to permit endless redirects either, thus not
            # request an override to the requests default to try and resolve
            # redirects as otherwise we might end up with something like
            # HTTPForbidden or a list of files. Both should be okay to at
            # least know things are okay in a limited fashion.
            response = requests.head(image_href, verify=verify,
                                     timeout=CONF.webserver_connection_timeout)

            if response.status_code == http_client.MOVED_PERMANENTLY:
                # NOTE(TheJulia): In the event we receive a redirect, we need
                # to notify the caller. Before this we would just fail,
                # but a url which is missing a trailing slash results in a
                # redirect to a target path, and the caller *may* actually
                # care about that.
                redirect = requests.Session().get_redirect_target(response)

                # Extra guard because this is pointless if there is no
                # location in the field. Requests also properly formats
                # our string for us, or gives us None.
                if redirect:
                    raise exception.ImageRefIsARedirect(
                        image_ref=image_href,
                        redirect_url=redirect)

            if (response.status_code == http_client.FORBIDDEN
                    and str(image_href).endswith('/')):
                LOG.warning('Attempted to validate a URL %s, however we '
                            'received an HTTP Forbidden response and the '
                            'url ends with trailing slash (/), suggesting '
                            'non-image deploy may be in progress with '
                            'a webserver which is not permitting an index '
                            'to be generated. We will treat this as valid, '
                            'but return the response.', image_href)
                return response

            # NOTE(TheJulia): Any file list reply will proceed past here just
            # fine as they are conveyed as an HTTP 200 OK response with a
            # server rendered HTML document payload.
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

        no_cache = 'no-store' in response.headers.get('Cache-Control', '')

        return {
            'size': int(image_size),
            'updated_at': date,
            'properties': {},
            'no_cache': no_cache,
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
        try:
            image_file.close()
            os.remove(dest_image_path)

            # NOTE(dtantsur): os.link is supposed to follow symlinks, but it
            # does not: https://github.com/python/cpython/issues/81793
            real_image_path = os.path.realpath(source_image_path)
            try:
                os.link(real_image_path, dest_image_path)
            except OSError as exc:
                orig = (f' (real path {real_image_path})'
                        if real_image_path != source_image_path
                        else '')

                LOG.debug('Could not create a link from %(src)s%(orig)s to '
                          '%(dest)s, will copy the content instead. '
                          'Error: %(exc)s.',
                          {'src': source_image_path, 'dest': dest_image_path,
                           'orig': orig, 'exc': exc})
            else:
                return

            # NOTE(dtantsur): starting with Python 3.8, copyfile() uses
            # efficient copying (i.e. sendfile) under the hood.
            shutil.copyfile(source_image_path, dest_image_path)
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
            'properties': {},
            # No point in caching local file images
            'no_cache': True,
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
