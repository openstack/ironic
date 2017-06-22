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


import os
import sys
import time

from glanceclient import client
from glanceclient import exc as glance_exc
from oslo_config import cfg
from oslo_log import log
import sendfile
import six
import six.moves.urllib.parse as urlparse

from ironic.common import exception
from ironic.common.glance_service import service_utils


LOG = log.getLogger(__name__)
CONF = cfg.CONF


def _translate_image_exception(image_id, exc_value):
    if isinstance(exc_value, (glance_exc.Forbidden,
                              glance_exc.Unauthorized)):
        return exception.ImageNotAuthorized(image_id=image_id)
    if isinstance(exc_value, glance_exc.NotFound):
        return exception.ImageNotFound(image_id=image_id)
    if isinstance(exc_value, glance_exc.BadRequest):
        return exception.Invalid(exc_value)
    return exc_value


def check_image_service(func):
    """Creates a glance client if doesn't exists and calls the function."""
    @six.wraps(func)
    def wrapper(self, *args, **kwargs):
        """Wrapper around methods calls.

        :param image_href: href that describes the location of an image
        """

        if self.client:
            return func(self, *args, **kwargs)

        image_href = kwargs.get('image_href')
        _id, self.endpoint, use_ssl = service_utils.parse_image_ref(image_href)

        params = {}
        params['insecure'] = CONF.glance.glance_api_insecure
        if (not params['insecure'] and CONF.glance.glance_cafile
                and use_ssl):
            params['cacert'] = CONF.glance.glance_cafile
        if CONF.glance.auth_strategy == 'keystone':
            params['token'] = self.context.auth_token
        self.client = client.Client(self.version,
                                    self.endpoint, **params)
        return func(self, *args, **kwargs)
    return wrapper


class BaseImageService(object):

    def __init__(self, client=None, version=1, context=None):
        self.client = client
        self.version = version
        self.context = context
        self.endpoint = None

    def call(self, method, *args, **kwargs):
        """Call a glance client method.

        If we get a connection error,
        retry the request according to CONF.glance_num_retries.

        :param context: The request context, for access checks.
        :param version: The requested API version.v
        :param method: The method requested to be called.
        :param args: A list of positional arguments for the method called
        :param kwargs: A dict of keyword arguments for the method called

        :raises: GlanceConnectionFailed
        """
        retry_excs = (glance_exc.ServiceUnavailable,
                      glance_exc.InvalidEndpoint,
                      glance_exc.CommunicationError)
        image_excs = (glance_exc.Forbidden,
                      glance_exc.Unauthorized,
                      glance_exc.NotFound,
                      glance_exc.BadRequest)
        num_attempts = 1 + CONF.glance.glance_num_retries

        # TODO(pas-ha) use retrying lib here
        for attempt in range(1, num_attempts + 1):
            try:
                return getattr(self.client.images, method)(*args, **kwargs)
            except retry_excs as e:
                error_msg = ("Error contacting glance server "
                             "'%(endpoint)s' for '%(method)s', attempt"
                             " %(attempt)s of %(num_attempts)s failed.")
                LOG.exception(error_msg, {'endpoint': self.endpoint,
                                          'num_attempts': num_attempts,
                                          'attempt': attempt,
                                          'method': method})
                if attempt == num_attempts:
                    raise exception.GlanceConnectionFailed(
                        endpoint=self.endpoint, reason=str(e))
                time.sleep(1)
            except image_excs as e:
                exc_type, exc_value, exc_trace = sys.exc_info()
                new_exc = _translate_image_exception(
                    args[0], exc_value)
                six.reraise(type(new_exc), new_exc, exc_trace)

    @check_image_service
    def _show(self, image_href, method='get'):
        """Returns a dict with image data for the given opaque image id.

        :param image_id: The opaque image identifier.
        :returns: A dict containing image metadata.

        :raises: ImageNotFound
        """
        LOG.debug("Getting image metadata from glance. Image: %s",
                  image_href)
        image_id = service_utils.parse_image_ref(image_href)[0]

        image = self.call(method, image_id)

        if not service_utils.is_image_available(self.context, image):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = service_utils.translate_from_glance(image)
        return base_image_meta

    @check_image_service
    def _download(self, image_href, data=None, method='data'):
        """Calls out to Glance for data and writes data.

        :param image_id: The opaque image identifier.
        :param data: (Optional) File object to write data to.
        """
        image_id = service_utils.parse_image_ref(image_href)[0]

        if (self.version == 2 and
                'file' in CONF.glance.allowed_direct_url_schemes):

            location = self._get_location(image_id)
            url = urlparse.urlparse(location)
            if url.scheme == "file":
                with open(url.path, "r") as f:
                    filesize = os.path.getsize(f.name)
                    sendfile.sendfile(data.fileno(), f.fileno(), 0, filesize)
                return

        image_chunks = self.call(method, image_id)

        if data is None:
            return image_chunks
        else:
            for chunk in image_chunks:
                data.write(chunk)
