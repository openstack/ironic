# Copyright 2012 OpenStack Foundation
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

import copy
import itertools
import random

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
import six.moves.urllib.parse as urlparse

from ironic.common import exception
from ironic.common import image_service
from ironic.common import keystone

CONF = cfg.CONF

_GLANCE_API_SERVER = None
""" iterator that cycles (indefinitely) over glance API servers. """


def _extract_attributes(image):
    IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                        'container_format', 'checksum', 'id',
                        'name', 'created_at', 'updated_at',
                        'deleted_at', 'deleted', 'status',
                        'min_disk', 'min_ram', 'is_public']

    IMAGE_ATTRIBUTES_V2 = ['tags', 'visibility', 'protected',
                           'file', 'schema']

    output = {}
    for attr in IMAGE_ATTRIBUTES:
        output[attr] = getattr(image, attr, None)

    output['properties'] = getattr(image, 'properties', {})

    if hasattr(image, 'schema') and 'v2' in image['schema']:
        IMAGE_ATTRIBUTES = IMAGE_ATTRIBUTES + IMAGE_ATTRIBUTES_V2
        for attr in IMAGE_ATTRIBUTES_V2:
            output[attr] = getattr(image, attr, None)
        output['schema'] = image['schema']

        for image_property in set(image.keys()) - set(IMAGE_ATTRIBUTES):
            output['properties'][image_property] = image[image_property]

    return output


def _convert_timestamps_to_datetimes(image_meta):
    """Convert timestamps to datetime objects

    Returns image metadata with timestamp fields converted to naive UTC
    datetime objects.
    """
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = timeutils.normalize_time(
                timeutils.parse_isotime(image_meta[attr]))
    return image_meta

_CONVERT_PROPS = ('block_device_mapping', 'mappings')


def _convert(metadata):
    metadata = copy.deepcopy(metadata)
    properties = metadata.get('properties')
    if properties:
        for attr in _CONVERT_PROPS:
            if attr in properties:
                prop = properties[attr]
                if isinstance(prop, six.string_types):
                    properties[attr] = jsonutils.loads(prop)
    return metadata


def _get_api_server_iterator():
    """Return iterator over shuffled API servers.

    Shuffle a list of CONF.glance.glance_api_servers and return an iterator
    that will cycle through the list, looping around to the beginning if
    necessary.

    If CONF.glance.glance_api_servers isn't set, we fall back to using this
    as the server: CONF.glance.glance_host:CONF.glance.glance_port.
    If CONF.glance.glance_host is also not set, fetch the endpoint from the
    service catalog.

    :returns: iterator that cycles (indefinitely) over shuffled glance API
              servers.
    """
    api_servers = []

    if not CONF.glance.glance_api_servers and not CONF.glance.glance_host:
        session = keystone.get_session('glance',
                                       auth=keystone.get_auth('glance'))
        api_servers = [keystone.get_service_url(session, service_type='image',
                                                endpoint_type='public')]
    else:
        configured_servers = (CONF.glance.glance_api_servers or
                              ['%s:%s' % (CONF.glance.glance_host,
                                          CONF.glance.glance_port)])
        for api_server in configured_servers:
            if '//' not in api_server:
                api_server = '%s://%s' % (CONF.glance.glance_protocol,
                                          api_server)
            api_servers.append(api_server)
        random.shuffle(api_servers)
    return itertools.cycle(api_servers)


def _get_api_server():
    """Return a Glance API server.

    :returns: for an API server, the tuple (host-or-IP, port, use_ssl), where
        use_ssl is True to use the 'https' scheme, and False to use 'http'.
    """
    global _GLANCE_API_SERVER

    if not _GLANCE_API_SERVER:
        _GLANCE_API_SERVER = _get_api_server_iterator()
    return six.next(_GLANCE_API_SERVER)


def parse_image_ref(image_href):
    """Parse an image href.

    :param image_href: href of an image
    :returns: a tuple (image ID, glance URL, whether to use SSL)

    :raises ValueError: when input image href is invalid
    """
    if '/' not in six.text_type(image_href):
        endpoint = _get_api_server()
        return (image_href, endpoint, endpoint.startswith('https'))
    else:
        try:
            url = urlparse.urlparse(image_href)
            if url.scheme == 'glance':
                endpoint = _get_api_server()
                image_id = image_href.split('/')[-1]
                return (image_id, endpoint, endpoint.startswith('https'))
            else:
                glance_port = url.port or 80
                glance_host = url.netloc.split(':', 1)[0]
                image_id = url.path.split('/')[-1]
                use_ssl = (url.scheme == 'https')
                endpoint = '%s://%s:%s' % (url.scheme, glance_host,
                                           glance_port)
                return (image_id, endpoint, use_ssl)
        except ValueError:
            raise exception.InvalidImageRef(image_href=image_href)


def translate_from_glance(image):
    image_meta = _extract_attributes(image)
    image_meta = _convert_timestamps_to_datetimes(image_meta)
    image_meta = _convert(image_meta)
    return image_meta


def is_image_available(context, image):
    """Check image availability.

    This check is needed in case Nova and Glance are deployed
    without authentication turned on.
    """
    # The presence of an auth token implies this is an authenticated
    # request and we need not handle the noauth use-case.
    if hasattr(context, 'auth_token') and context.auth_token:
        return True
    if image.is_public or context.is_admin:
        return True
    properties = image.properties
    if context.project_id and ('owner_id' in properties):
        return str(properties['owner_id']) == str(context.project_id)

    if context.project_id and ('project_id' in properties):
        return str(properties['project_id']) == str(context.project_id)

    try:
        user_id = properties['user_id']
    except KeyError:
        return False

    return str(user_id) == str(context.user_id)


def is_glance_image(image_href):
    if not isinstance(image_href, six.string_types):
        return False
    return (image_href.startswith('glance://') or
            uuidutils.is_uuid_like(image_href))


def is_image_href_ordinary_file_name(image_href):
    """Check if image_href is a ordinary file name.

    This method judges if image_href is a ordinary file name or not,
    which is a file supposed to be stored in share file system.
    The ordinary file name is neither glance image href
    nor image service href.

    :returns: True if image_href is ordinary file name, False otherwise.
    """
    return not (is_glance_image(image_href) or
                urlparse.urlparse(image_href).scheme.lower() in
                image_service.protocol_mapping)
