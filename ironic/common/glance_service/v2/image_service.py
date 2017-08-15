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
import time

from oslo_utils import uuidutils
from six.moves.urllib import parse as urlparse
from swiftclient import utils as swift_utils

from ironic.common import exception as exc
from ironic.common.glance_service import base_image_service
from ironic.common.glance_service import service
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.conf import CONF

TempUrlCacheElement = collections.namedtuple('TempUrlCacheElement',
                                             ['url', 'url_expires_at'])


class GlanceImageService(base_image_service.BaseImageService,
                         service.ImageService):

    # A dictionary containing cached temp URLs in namedtuples
    # in format:
    # {
    #     <image_id> : (
    #          url=<temp_url>,
    #          url_expires_at=<expiration_time>
    #     )
    # }
    _cache = {}

    def show(self, image_id):
        return self._show(image_id, method='get')

    def download(self, image_id, data=None):
        return self._download(image_id, method='data', data=data)

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

        path = swift_utils.generate_temp_url(
            path=path, seconds=seconds, key=key, method=method)

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
            have a image ID.
        """
        self._validate_temp_url_config()

        if ('id' not in image_info or not
                uuidutils.is_uuid_like(image_info['id'])):
            raise exc.ImageUnacceptable(_(
                'The given image info does not have a valid image id: %s')
                % image_info)

        image_id = image_info['id']

        url_fragments = {
            'api_version': CONF.glance.swift_api_version,
            'account': CONF.glance.swift_account,
            'container': self._get_swift_container(image_id),
            'object_id': image_id
        }

        endpoint_url = CONF.glance.swift_endpoint_url
        if CONF.deploy.object_store_endpoint_type == 'radosgw':
            chunks = urlparse.urlsplit(CONF.glance.swift_endpoint_url)
            if not chunks.path:
                endpoint_url = urlparse.urljoin(
                    endpoint_url, 'swift')
            elif chunks.path != '/swift':
                raise exc.InvalidParameterValue(
                    _('Swift endpoint URL should only contain scheme, '
                      'hostname, optional port and optional /swift path '
                      'without trailing slash; provided value is: %s')
                    % endpoint_url)
            template = '/{api_version}/{container}/{object_id}'
        else:
            template = '/{api_version}/{account}/{container}/{object_id}'

        url_path = template.format(**url_fragments)

        return self._generate_temp_url(
            path=url_path,
            seconds=CONF.glance.swift_temp_url_duration,
            key=CONF.glance.swift_temp_url_key,
            method='GET',
            endpoint=endpoint_url,
            image_id=image_id
        )

    def _validate_temp_url_config(self):
        """Validate the required settings for a temporary URL."""
        if not CONF.glance.swift_temp_url_key:
            raise exc.MissingParameterValue(_(
                'Swift temporary URLs require a shared secret to be created. '
                'You must provide "swift_temp_url_key" as a config option.'))
        if not CONF.glance.swift_endpoint_url:
            raise exc.MissingParameterValue(_(
                'Swift temporary URLs require a Swift endpoint URL. '
                'You must provide "swift_endpoint_url" as a config option.'))
        if (not CONF.glance.swift_account and
                CONF.deploy.object_store_endpoint_type == 'swift'):
            raise exc.MissingParameterValue(_(
                'Swift temporary URLs require a Swift account string. '
                'You must provide "swift_account" as a config option.'))
        if (CONF.glance.swift_temp_url_duration <
                CONF.glance.swift_temp_url_expected_download_start_delay):
            raise exc.InvalidParameterValue(_(
                '"swift_temp_url_duration" must be greater than or equal to '
                '"[glance]swift_temp_url_expected_download_start_delay" '
                'option, otherwise the Swift temporary URL may expire before '
                'the download starts.'))
        seed_num_chars = CONF.glance.swift_store_multiple_containers_seed
        if (seed_num_chars is None or seed_num_chars < 0
                or seed_num_chars > 32):
            raise exc.InvalidParameterValue(_(
                "An integer value between 0 and 32 is required for"
                " swift_store_multiple_containers_seed."))

    def _get_swift_container(self, image_id):
        """Get the Swift container the image is stored in.

        Code based on: http://git.openstack.org/cgit/openstack/glance_store/
        tree/glance_store/_drivers/swift/
        store.py?id=3cd690b37dc9d935445aca0998e8aec34a3e3530#n725

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
            new_container_name = (CONF.glance.swift_container +
                                  '_' + name_suffix)
            return new_container_name
        else:
            return CONF.glance.swift_container

    def _get_location(self, image_id):
        """Get storage URL.

        Returns the direct url representing the backend storage location,
        or None if this attribute is not shown by Glance.
        """
        image_meta = self.call('get', image_id)

        if not service_utils.is_image_available(self.context, image_meta):
            raise exc.ImageNotFound(image_id=image_id)

        return getattr(image_meta, 'direct_url', None)

    def _remove_expired_items_from_cache(self):
        """Remove expired items from temporary URL cache

        This function removes entries that will expire before the expected
        usage time.
        """
        max_valid_time = (
            int(time.time()) +
            CONF.glance.swift_temp_url_expected_download_start_delay)
        keys_to_remove = [
            k for k, v in self._cache.items()
            if (v.url_expires_at < max_valid_time)]
        for k in keys_to_remove:
            del self._cache[k]
