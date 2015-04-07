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
import os
import shutil

from oslo_config import cfg
from oslo_utils import importutils
import requests
import sendfile
import six
import six.moves.urllib.parse as urlparse

from ironic.common import exception
from ironic.common.i18n import _
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1mb


CONF = cfg.CONF
# Import this opt early so that it is available when registering
# glance_opts below.
CONF.import_opt('my_ip', 'ironic.netconf')

glance_opts = [
    cfg.StrOpt('glance_host',
               default='$my_ip',
               help='Default glance hostname or IP address.'),
    cfg.IntOpt('glance_port',
               default=9292,
               help='Default glance port.'),
    cfg.StrOpt('glance_protocol',
               default='http',
               help='Default protocol to use when connecting to glance. '
               'Set to https for SSL.'),
    cfg.ListOpt('glance_api_servers',
                help='A list of the glance api servers available to ironic. '
                'Prefix with https:// for SSL-based glance API servers. '
                'Format is [hostname|IP]:port.'),
    cfg.BoolOpt('glance_api_insecure',
                default=False,
                help='Allow to perform insecure SSL (https) requests to '
                     'glance.'),
    cfg.IntOpt('glance_num_retries',
               default=0,
               help='Number of retries when downloading an image from '
                    'glance.'),
    cfg.StrOpt('auth_strategy',
               default='keystone',
               help='Authentication strategy to use when connecting to '
                    'glance. Only "keystone" and "noauth" are currently '
                    'supported by ironic.'),
]

CONF.register_opts(glance_opts, group='glance')


def import_versioned_module(version, submodule=None):
    module = 'ironic.common.glance_service.v%s' % version
    if submodule:
        module = '.'.join((module, submodule))
    return importutils.try_import(module)


def GlanceImageService(client=None, version=1, context=None):
    module = import_versioned_module(version, 'image_service')
    service_class = getattr(module, 'GlanceImageService')
    return service_class(client, version, context)


@six.add_metaclass(abc.ABCMeta)
class BaseImageService(object):
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
        :returns: dictionary of image properties.
        """


class HttpImageService(BaseImageService):
    """Provides retrieval of disk images using HTTP."""

    def validate_href(self, image_href):
        """Validate HTTP image reference.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if HEAD request failed or
            returned response code not equal to 200.
        :returns: Response to HEAD request.
        """
        try:
            response = requests.head(image_href)
            if response.status_code != 200:
                raise exception.ImageRefValidationFailed(image_href=image_href,
                    reason=_("Got HTTP code %s instead of 200 in response to "
                             "HEAD request.") % response.status_code)
        except requests.RequestException as e:
            raise exception.ImageRefValidationFailed(image_href=image_href,
                                                     reason=e)
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
            response = requests.get(image_href, stream=True)
            if response.status_code != 200:
                raise exception.ImageRefValidationFailed(image_href=image_href,
                    reason=_("Got HTTP code %s instead of 200 in response to "
                             "GET request.") % response.status_code)
            with response.raw as input_img:
                shutil.copyfileobj(input_img, image_file, IMAGE_CHUNK_SIZE)
        except (requests.RequestException, IOError) as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=e)

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if:
            * HEAD request failed;
            * HEAD request returned response code not equal to 200;
            * Content-Length header not found in response to HEAD request.
        :returns: dictionary of image properties.
        """
        response = self.validate_href(image_href)
        image_size = response.headers.get('Content-Length')
        if image_size is None:
            raise exception.ImageRefValidationFailed(image_href=image_href,
                reason=_("Cannot determine image size as there is no "
                         "Content-Length header specified in response "
                         "to HEAD request."))
        return {
            'size': int(image_size),
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
            raise exception.ImageRefValidationFailed(image_href=image_href,
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
            if (local_device == os.stat(source_image_path).st_dev and
                    os.access(source_image_path, os.R_OK | os.W_OK)):
                image_file.close()
                os.remove(dest_image_path)
                os.link(source_image_path, dest_image_path)
            else:
                filesize = os.path.getsize(source_image_path)
                with open(source_image_path, 'rb') as input_img:
                    sendfile.sendfile(image_file.fileno(), input_img.fileno(),
                                      0, filesize)
        except Exception as e:
            raise exception.ImageDownloadFailed(image_href=image_href,
                                                reason=e)

    def show(self, image_href):
        """Get dictionary of image properties.

        :param image_href: Image reference.
        :raises: exception.ImageRefValidationFailed if image file specified
            doesn't exist.
        :returns: dictionary of image properties.
        """
        source_image_path = self.validate_href(image_href)
        return {
            'size': os.path.getsize(source_image_path),
            'properties': {}
        }


protocol_mapping = {
    'http': HttpImageService,
    'https': HttpImageService,
    'file': FileImageService,
    'glance': GlanceImageService,
}


def get_image_service(image_href, client=None, version=1, context=None):
    """Get image service instance to download the image.

    :param image_href: String containing href to get image service for.
    :param client: Glance client to be used for download, used only if
        image_href is Glance href.
    :param version: Version of Glance API to use, used only if image_href is
        Glance href.
    :param context: request context, used only if image_href is Glance href.
    :raises: exception.ImageRefValidationFailed if no image service can
        handle specified href.
    :returns: Instance of an image service class that is able to download
        specified image.
    """
    scheme = urlparse.urlparse(image_href).scheme.lower()
    try:
        cls = protocol_mapping[scheme or 'glance']
    except KeyError:
        raise exception.ImageRefValidationFailed(
            image_href=image_href,
            reason=_('Image download protocol '
                     '%s is not supported.') % scheme
        )

    if cls == GlanceImageService:
        return cls(client, version, context)
    return cls()
