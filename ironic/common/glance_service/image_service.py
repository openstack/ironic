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

import collections
import functools
import os
import re
import sys
import time
from urllib import parse as urlparse

from keystoneauth1 import exceptions as ks_exception
import openstack
from openstack.connection import exceptions as openstack_exc
from oslo_log import log
from oslo_utils import uuidutils
import tenacity

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.common import swift
from ironic.common import utils
from ironic.conf import CONF

TempUrlCacheElement = collections.namedtuple('TempUrlCacheElement',
                                             ['url', 'url_expires_at'])


LOG = log.getLogger(__name__)
_GLANCE_SESSION = None


def _translate_image_exception(image_id, exc_value):
    if isinstance(exc_value, (openstack_exc.ForbiddenException)):
        return exception.ImageNotAuthorized(image_id=image_id)
    if isinstance(exc_value, openstack_exc.NotFoundException):
        return exception.ImageNotFound(image_id=image_id)
    if isinstance(exc_value, openstack_exc.BadRequestException):
        return exception.Invalid(exc_value)
    return exc_value


def check_image_service(func):
    """Creates a glance client if doesn't exists and calls the function."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        """Wrapper around methods calls.

        :param image_href: href that describes the location of an image
        """

        if self.client:
            return func(self, *args, **kwargs)

        global _GLANCE_SESSION
        if not _GLANCE_SESSION:
            _GLANCE_SESSION = keystone.get_session('glance')

        service_auth = keystone.get_auth('glance')

        self.endpoint = keystone.get_endpoint('glance',
                                              session=_GLANCE_SESSION,
                                              auth=service_auth)

        user_auth = None
        # NOTE(pas-ha) our ContextHook removes context.auth_token in noauth
        # case, so when ironic is in noauth but glance is not, we will not
        # enter the next if-block and use auth from [glance] config section
        if self.context.auth_token:
            user_auth = keystone.get_service_auth(self.context, self.endpoint,
                                                  service_auth)
        sess = keystone.get_session('glance',
                                    auth=user_auth or service_auth)
        conn = openstack.connection.Connection(
            session=sess,
            image_endpoint_override=self.endpoint,
            image_api_version='2')

        self.client = conn.global_request(self.context.global_id).image

        return func(self, *args, **kwargs)

    return wrapper


class GlanceImageService(object):

    # A dictionary containing cached temp URLs in namedtuples
    # in format:
    # {
    #     <image_id> : (
    #          url=<temp_url>,
    #          url_expires_at=<expiration_time>
    #     )
    # }
    _cache = {}

    def __init__(self, client=None, context=None):
        self.client = client
        self.context = context
        self.endpoint = None

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            exception.GlanceConnectionFailed),
        stop=utils.stop_after_retries('num_retries', group='glance'),
        wait=tenacity.wait_fixed(1),
        reraise=True
    )
    def call(self, method, *args, **kwargs):
        """Call a glance client method.

        If we get a connection error,
        retry the request according to CONF.num_retries.

        :param method: The method requested to be called.
        :param args: A list of positional arguments for the method called
        :param kwargs: A dict of keyword arguments for the method called

        :raises: GlanceConnectionFailed
        """
        try:
            return getattr(self.client, method)(*args, **kwargs)
        except openstack_exc.SDKException:
            exc_type, exc_value, exc_trace = sys.exc_info()
            new_exc = _translate_image_exception(
                args[0], exc_value)
            if isinstance(new_exc, exception.IronicException):
                # exception has been translated to a new one, raise it
                raise type(new_exc)(new_exc).with_traceback(exc_trace)
        except ks_exception.ClientException as e:
            error_msg = ("Error contacting glance endpoint "
                         "%(endpoint)s for '%(method)s'")
            LOG.exception(error_msg, {'endpoint': self.endpoint,
                                      'method': method})
            raise exception.GlanceConnectionFailed(
                endpoint=self.endpoint, reason=e)

    @check_image_service
    def show(self, image_href):
        """Returns a dict with image data for the given opaque image id.

        :param image_href: The opaque image identifier.
        :returns: A dict containing image metadata.

        :raises: ImageNotFound
        :raises: ImageUnacceptable if the image status is not active
        """
        LOG.debug("Getting image metadata from glance. Image: %s",
                  image_href)
        image_id = service_utils.parse_image_id(image_href)

        image = self.call('get_image', image_id)

        if not service_utils.is_image_active(image):
            raise exception.ImageUnacceptable(
                image_id=image_id,
                reason=_("The image is required to be in an active state."))

        if not service_utils.is_image_available(self.context, image):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = service_utils.translate_from_glance(image)
        return base_image_meta

    @check_image_service
    def download(self, image_href, data=None):
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
                    os.sendfile(data.fileno(), f.fileno(), 0, filesize)
                return

        image_size = 0
        image_data = None
        if data:
            image_chunks = self.call('download_image', image_id, stream=True)
            for chunk in image_chunks:
                data.write(chunk)
                image_size += len(chunk)
        else:
            image_data = self.call('download_image', image_id).content
            image_size = len(image_data)
        if image_size == 0:
            raise exception.ImageDownloadFailed(
                image_href=image_href, reason=_('image contains no data.'))
        return image_data

    def _generate_temp_url(self, path, seconds, key, method, endpoint,
                           image_id):
        """Get Swift temporary URL.

        Generates (or returns the cached one if caching is enabled) a
        temporary URL that gives unauthenticated access to the Swift object.

        :param path: The full path to the Swift object. Example:
            /v1/AUTH_account/c/o.
        :param seconds: The amount of time in seconds the temporary URL will
            be valid for.
        :param key: The secret temporary URL key set on the Swift cluster.
        :param method: A HTTP method, typically either GET or PUT, to allow for
            this temporary URL.
        :param endpoint: Endpoint URL of Swift service.
        :param image_id: UUID of a Glance image.
        :returns: temporary URL
        """

        if CONF.glance.swift_temp_url_cache_enabled:
            self._remove_expired_items_from_cache()
            if image_id in self._cache:
                return self._cache[image_id].url

        swiftapi = swift.SwiftAPI()
        path = swiftapi.generate_temp_url(
            path=path, timeout=seconds, temp_url_key=key, method=method)

        temp_url = '{endpoint_url}{url_path}'.format(
            endpoint_url=endpoint, url_path=path)

        if CONF.glance.swift_temp_url_cache_enabled:
            query = urlparse.urlparse(temp_url).query
            exp_time_str = dict(urlparse.parse_qsl(query))['temp_url_expires']
            self._cache[image_id] = TempUrlCacheElement(
                url=temp_url, url_expires_at=int(exp_time_str)
            )

        return temp_url

    def swift_temp_url(self, image_info):
        """Generate a no-auth Swift temporary URL.

        This function will generate (or return the cached one if temp URL
        cache is enabled) the temporary Swift URL using the image
        id from Glance and the config options: 'swift_endpoint_url',
        'swift_api_version', 'swift_account' and 'swift_container'.
        The temporary URL will be valid for 'swift_temp_url_duration' seconds.
        This allows Ironic to download a Glance image without passing around
        an auth_token.

        :param image_info: The return from a GET request to Glance for a
            certain image_id. Should be a dictionary, with keys like 'name' and
            'checksum'. See
            https://docs.openstack.org/glance/latest/user/glanceapi.html for
            examples.
        :returns: A signed Swift URL from which an image can be downloaded,
            without authentication.

        :raises: InvalidParameterValue if Swift config options are not set
            correctly.
        :raises: MissingParameterValue if a required parameter is not set.
        :raises: ImageUnacceptable if the image info from Glance does not
            have an image ID.
        """
        self._validate_temp_url_config()

        if ('id' not in image_info or not
                uuidutils.is_uuid_like(image_info['id'])):
            raise exception.ImageUnacceptable(_(
                'The given image info does not have a valid image id: %s')
                % image_info)

        image_id = image_info['id']

        url_fragments = {
            'api_version': CONF.glance.swift_api_version,
            'container': self._get_swift_container(image_id),
            'object_id': image_id
        }

        endpoint_url = CONF.glance.swift_endpoint_url
        if not endpoint_url:
            swift_session = swift.get_swift_session()
            try:
                endpoint_url = keystone.get_endpoint('swift',
                                                     session=swift_session)
            except exception.CatalogNotFound:
                raise exception.MissingParameterValue(_(
                    'Swift temporary URLs require a Swift endpoint URL, '
                    'but it was not found in the service catalog. You must '
                    'provide "swift_endpoint_url" as a config option.'))

        swift_account_prefix = CONF.glance.swift_account_prefix
        if swift_account_prefix and not swift_account_prefix.endswith('_'):
            swift_account_prefix = '%s_' % swift_account_prefix

        # Strip /v1/AUTH_%(tenant_id)s, if present
        endpoint_url = re.sub('/v1/%s[^/]+/?$' % swift_account_prefix, '',
                              endpoint_url)

        key = CONF.glance.swift_temp_url_key
        account = CONF.glance.swift_account
        if not account:
            swift_session = swift.get_swift_session()
            auth_ref = swift_session.auth.get_auth_ref(swift_session)
            account = '%s%s' % (swift_account_prefix, auth_ref.project_id)

        if not key:
            swift_api = swift.SwiftAPI()
            key = swift_api.get_temp_url_key()

        if not key:
            raise exception.MissingParameterValue(_(
                'Swift temporary URLs require a shared secret to be '
                'created. You must provide "swift_temp_url_key" as a '
                'config option or pre-generate the key on the project '
                'used to access Swift.'))

        url_fragments['account'] = account
        template = '/{api_version}/{account}/{container}/{object_id}'

        url_path = template.format(**url_fragments)

        return self._generate_temp_url(
            path=url_path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=key,
            method='GET',
            endpoint=endpoint_url,
            image_id=image_id
        )

    def _validate_temp_url_config(self):
        """Validate the required settings for a temporary URL."""
        if (CONF.glance.swift_temp_url_duration
                < CONF.glance.swift_temp_url_expected_download_start_delay):
            raise exception.InvalidParameterValue(_(
                '"swift_temp_url_duration" must be greater than or equal to '
                '"[glance]swift_temp_url_expected_download_start_delay" '
                'option, otherwise the Swift temporary URL may expire before '
                'the download starts.'))
        seed_num_chars = CONF.glance.swift_store_multiple_containers_seed
        if (seed_num_chars is None or seed_num_chars < 0
                or seed_num_chars > 32):
            raise exception.InvalidParameterValue(_(
                "An integer value between 0 and 32 is required for"
                " swift_store_multiple_containers_seed."))

    def _get_swift_container(self, image_id):
        """Get the Swift container the image is stored in.

        Code based on: https://opendev.org/openstack/glance_store/src/commit/
        3cd690b37dc9d935445aca0998e8aec34a3e3530/glance_store/_drivers/swift/
        store.py#L725

        Returns appropriate container name depending upon value of
        ``swift_store_multiple_containers_seed``. In single-container mode,
        which is a seed value of 0, simply returns ``swift_container``.
        In multiple-container mode, returns ``swift_container`` as the
        prefix plus a suffix determined by the multiple container seed

        examples:
            single-container mode:  'glance'
            multiple-container mode: 'glance_3a1' for image uuid 3A1xxxxxxx...

        :param image_id: UUID of image
        :returns: The name of the swift container the image is stored in
        """
        seed_num_chars = CONF.glance.swift_store_multiple_containers_seed

        if seed_num_chars > 0:
            image_id = str(image_id).lower()

            num_dashes = image_id[:seed_num_chars].count('-')
            num_chars = seed_num_chars + num_dashes
            name_suffix = image_id[:num_chars]
            new_container_name = (CONF.glance.swift_container
                                  + '_' + name_suffix)
            return new_container_name
        else:
            return CONF.glance.swift_container

    def _get_location(self, image_id):
        """Get storage URL.

        Returns the direct url representing the backend storage location,
        or None if this attribute is not shown by Glance.
        """
        image_meta = self.call('get_image', image_id)

        if not service_utils.is_image_available(self.context, image_meta):
            raise exception.ImageNotFound(image_id=image_id)

        return getattr(image_meta, 'direct_url', None)

    def _remove_expired_items_from_cache(self):
        """Remove expired items from temporary URL cache

        This function removes entries that will expire before the expected
        usage time.
        """
        max_valid_time = (
            int(time.time())
            + CONF.glance.swift_temp_url_expected_download_start_delay)
        keys_to_remove = [
            k for k, v in self._cache.items()
            if (v.url_expires_at < max_valid_time)]
        for k in keys_to_remove:
            del self._cache[k]

    # TODO(TheJulia): Here because the GlanceImageService class is not based
    # upon the base image service class.
    @property
    def is_auth_set_needed(self):
        """Property to notify the caller if it needs to set authentication."""
        return False

    @property
    def transfer_verified_checksum(self):
        """The transferred artifact checksum."""
        # FIXME(TheJulia): We should look at and see if we wire
        # this up in a future change.
        return None
