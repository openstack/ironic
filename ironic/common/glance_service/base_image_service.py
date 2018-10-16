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
from oslo_log import log
import sendfile
import six
import six.moves.urllib.parse as urlparse

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf import CONF


LOG = log.getLogger(__name__)

_GLANCE_SESSION = None


def _get_glance_session(**session_kwargs):
    global _GLANCE_SESSION
    if not _GLANCE_SESSION:
        _GLANCE_SESSION = keystone.get_session('glance', **session_kwargs)
    return _GLANCE_SESSION


def _translate_image_exception(image_id, exc_value):
    if isinstance(exc_value, (glance_exc.Forbidden,
                              glance_exc.Unauthorized)):
        return exception.ImageNotAuthorized(image_id=image_id)
    if isinstance(exc_value, glance_exc.NotFound):
        return exception.ImageNotFound(image_id=image_id)
    if isinstance(exc_value, glance_exc.BadRequest):
        return exception.Invalid(exc_value)
    return exc_value


# NOTE(pas-ha) while looking very ugly currently, this will be simplified
# in Rocky after all deprecated [glance] options are removed and
# keystone catalog is always used with 'keystone' auth strategy
# together with session always loaded from config options
def check_image_service(func):
    """Creates a glance client if doesn't exists and calls the function."""
    @six.wraps(func)
    def wrapper(self, *args, **kwargs):
        """Wrapper around methods calls.

        :param image_href: href that describes the location of an image
        """

        if self.client:
            return func(self, *args, **kwargs)

        # TODO(pas-ha) remove in Rocky
        session_params = {}
        if CONF.glance.glance_api_insecure and not CONF.glance.insecure:
            session_params['insecure'] = CONF.glance.glance_api_insecure
        if CONF.glance.glance_cafile and not CONF.glance.cafile:
            session_params['cacert'] = CONF.glance.glance_cafile
        # NOTE(pas-ha) glanceclient uses Adapter-based SessionClient,
        # so we can pass session and auth separately, makes things easier
        session = _get_glance_session(**session_params)

        # TODO(pas-ha) remove in Rocky
        # NOTE(pas-ha) new option must win if configured
        if (CONF.glance.glance_api_servers
                and not CONF.glance.endpoint_override):
            # NOTE(pas-ha) all the 2 methods have image_href as the first
            #              positional arg, but check in kwargs too
            image_href = args[0] if args else kwargs.get('image_href')
            url = service_utils.get_glance_api_server(image_href)
            CONF.set_override('endpoint_override', url, group='glance')

        # TODO(pas-ha) remove in Rocky
        if CONF.glance.auth_strategy == 'noauth':
            CONF.set_override('auth_type', 'none', group='glance')

        service_auth = keystone.get_auth('glance')

        adapter_params = {}
        adapter = keystone.get_adapter('glance', session=session,
                                       auth=service_auth, **adapter_params)
        self.endpoint = adapter.get_endpoint()

        user_auth = None
        # NOTE(pas-ha) our ContextHook removes context.auth_token in noauth
        # case, so when ironic is in noauth but glance is not, we will not
        # enter the next if-block and use auth from [glance] config section
        if self.context.auth_token:
            user_auth = keystone.get_service_auth(self.context, self.endpoint,
                                                  service_auth)
        self.client = client.Client(2, session=session,
                                    auth=user_auth or service_auth,
                                    endpoint_override=self.endpoint,
                                    global_request_id=self.context.global_id)
        return func(self, *args, **kwargs)

    return wrapper


class BaseImageService(object):

    def __init__(self, client=None, context=None):
        self.client = client
        self.context = context
        self.endpoint = None

    def call(self, method, *args, **kwargs):
        """Call a glance client method.

        If we get a connection error,
        retry the request according to CONF.glance_num_retries.

        :param context: The request context, for access checks.
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
                error_msg = ("Error contacting glance endpoint "
                             "%(endpoint)s for '%(method)s', attempt "
                             "%(attempt)s of %(num_attempts)s failed.")
                LOG.exception(error_msg, {'endpoint': self.endpoint,
                                          'num_attempts': num_attempts,
                                          'attempt': attempt,
                                          'method': method})
                if attempt == num_attempts:
                    raise exception.GlanceConnectionFailed(
                        endpoint=self.endpoint, reason=e)
                time.sleep(1)
            except image_excs as e:
                exc_type, exc_value, exc_trace = sys.exc_info()
                new_exc = _translate_image_exception(
                    args[0], exc_value)
                six.reraise(type(new_exc), new_exc, exc_trace)

    @check_image_service
    def _show(self, image_href, method='get'):
        """Returns a dict with image data for the given opaque image id.

        :param image_href: The opaque image identifier.
        :returns: A dict containing image metadata.

        :raises: ImageNotFound
        :raises: ImageUnacceptable if the image status is not active
        """
        LOG.debug("Getting image metadata from glance. Image: %s",
                  image_href)
        image_id = service_utils.parse_image_id(image_href)

        image = self.call(method, image_id)

        if not service_utils.is_image_active(image):
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("The image is required to be in an active state."))

        if not service_utils.is_image_available(self.context, image):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = service_utils.translate_from_glance(image)
        return base_image_meta

    @check_image_service
    def _download(self, image_href, data=None, method='data'):
        """Calls out to Glance for data and writes data.

        :param image_href: The opaque image identifier.
        :param data: (Optional) File object to write data to.
        """
        image_id = service_utils.parse_image_id(image_href)

        if 'file' in CONF.glance.allowed_direct_url_schemes:
            location = self._get_location(image_id)
            url = urlparse.urlparse(location)
            if url.scheme == "file":
                with open(url.path, "r") as f:
                    filesize = os.path.getsize(f.name)
                    sendfile.sendfile(data.fileno(), f.fileno(), 0, filesize)
                return

        image_chunks = self.call(method, image_id)
        # NOTE(dtantsur): when using Glance V2, image_chunks is a wrapper
        # around real data, so we have to check the wrapped data for None.
        if image_chunks.wrapped is None:
            raise exception.ImageDownloadFailed(
                image_href=image_href, reason=_('image contains no data.'))

        if data is None:
            return image_chunks
        else:
            for chunk in image_chunks:
                data.write(chunk)
