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

from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import exception


_IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                     'container_format', 'checksum', 'id',
                     'name', 'created_at', 'updated_at',
                     'deleted_at', 'deleted', 'status',
                     'min_disk', 'min_ram', 'tags', 'visibility',
                     'protected', 'file', 'schema', 'os_hash_algo',
                     'os_hash_value']


def _extract_attributes(image):
    output = {}
    for attr in _IMAGE_ATTRIBUTES:
        output[attr] = getattr(image, attr, None)

    output['properties'] = {}
    output['schema'] = image.schema

    for image_property in set(image) - set(_IMAGE_ATTRIBUTES):
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
                if isinstance(prop, str):
                    properties[attr] = jsonutils.loads(prop)
    return metadata


def parse_image_id(image_href):
    """Parse an image id from image href.

    :param image_href: href of an image
    :returns: image id parsed from image_href

    :raises InvalidImageRef: when input image href is invalid
    """
    image_href = str(image_href)
    if uuidutils.is_uuid_like(image_href):
        image_id = image_href
    elif image_href.startswith('glance://'):
        image_id = image_href.split('/')[-1]
        if not uuidutils.is_uuid_like(image_id):
            raise exception.InvalidImageRef(image_href=image_href)
    else:
        raise exception.InvalidImageRef(image_href=image_href)
    return image_id


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

    if getattr(image, 'visibility', None) == 'public' or context.is_admin:
        return True

    return (context.project_id and
            getattr(image, 'owner', None) == context.project_id)


def is_image_active(image):
    """Check the image status.

    This check is needed in case the Glance image is stuck in queued status
    or pending_delete.
    """
    return str(getattr(image, 'status', None)) == "active"


def is_glance_image(image_href):
    if not isinstance(image_href, str):
        return False
    return (image_href.startswith('glance://')
            or uuidutils.is_uuid_like(image_href))
