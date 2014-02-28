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
import logging

from oslo.config import cfg
import six
import six.moves.urllib.parse as urlparse

from ironic.common import exception
from ironic.openstack.common import jsonutils
from ironic.openstack.common import timeutils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def generate_glance_url():
    """Generate the URL to glance."""
    return "%s://%s:%d" % (CONF.glance.glance_protocol,
                           CONF.glance.glance_host,
                           CONF.glance.glance_port)


def generate_image_url(image_ref):
    """Generate an image URL from an image_ref."""
    return "%s/images/%s" % (generate_glance_url(), image_ref)


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
    """Returns image with timestamp fields converted to datetime objects."""
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = timeutils.parse_isotime(image_meta[attr])
    return image_meta

_CONVERT_PROPS = ('block_device_mapping', 'mappings')


def _convert(metadata, method):
    metadata = copy.deepcopy(metadata)
    properties = metadata.get('properties')
    if properties:
        for attr in _CONVERT_PROPS:
            if attr in properties:
                prop = properties[attr]
                if method == 'from':
                    if isinstance(prop, six.string_types):
                        properties[attr] = jsonutils.loads(prop)
                if method == 'to':
                    if not isinstance(prop, six.string_types):
                        properties[attr] = jsonutils.dumps(prop)
    return metadata


def _remove_read_only(image_meta):
    IMAGE_ATTRIBUTES = ['status', 'updated_at', 'created_at', 'deleted_at']
    output = copy.deepcopy(image_meta)
    for attr in IMAGE_ATTRIBUTES:
        if attr in output:
            del output[attr]
    return output


def _get_api_server():
    """Shuffle a list of CONF.glance_api_servers and return an iterator
    that will cycle through the list, looping around to the beginning
    if necessary.
    """
    api_server = CONF.glance.glance_api_servers or \
        CONF.glance.glance_host + ':' + str(CONF.glance.glance_port)
    if '//' not in api_server:
        api_server = 'http://' + api_server
    url = urlparse.urlparse(api_server)
    port = url.port or 80
    host = url.netloc.split(':', 1)[0]
    use_ssl = (url.scheme == 'https')
    return host, port, use_ssl


def parse_image_ref(image_href):
    """Parse an image href into composite parts.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, host, port)

    :raises ValueError
    """
    if '/' not in str(image_href):
        image_id = image_href
        (glance_host, glance_port, use_ssl) = _get_api_server()
        return (image_id, glance_host, glance_port, use_ssl)
    else:
        try:
            url = urlparse.urlparse(image_href)
            if url.scheme == 'glance':
                (glance_host, glance_port, use_ssl) = _get_api_server()
                image_id = image_href.split('/')[-1]
            else:
                glance_port = url.port or 80
                glance_host = url.netloc.split(':', 1)[0]
                image_id = url.path.split('/')[-1]
                use_ssl = (url.scheme == 'https')
            return (image_id, glance_host, glance_port, use_ssl)
        except ValueError:
            raise exception.InvalidImageRef(image_href=image_href)


def extract_query_params(params, version):
    _params = {}
    accepted_params = ('filters', 'marker', 'limit',
                       'sort_key', 'sort_dir')
    for param in accepted_params:
        if params.get(param):
            _params[param] = params.get(param)
    # ensure filters is a dict
    _params.setdefault('filters', {})

    # NOTE(vish): don't filter out private images
    # NOTE(ghe): in v2, not passing any visibility doesn't filter prvate images
    if version == 1:
        _params['filters'].setdefault('is_public', 'none')

    return _params


def translate_to_glance(image_meta):
    image_meta = _convert(image_meta, 'to')
    image_meta = _remove_read_only(image_meta)
    return image_meta


def translate_from_glance(image):
    image_meta = _extract_attributes(image)
    image_meta = _convert_timestamps_to_datetimes(image_meta)
    image_meta = _convert(image_meta, 'from')
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
