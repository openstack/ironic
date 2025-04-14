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

from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import image_service as service
from ironic.common import keystone
from ironic.conf import CONF

_IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                     'container_format', 'checksum', 'id',
                     'name', 'created_at', 'updated_at',
                     'deleted_at', 'deleted', 'status',
                     'min_disk', 'min_ram', 'tags', 'visibility',
                     'protected', 'file', 'schema', 'os_hash_algo',
                     'os_hash_value']


LOG = log.getLogger(__name__)
_GLANCE_SESSION = None


def _extract_attributes(image):
    output = {}
    # copies attributes from the openstacksdk Image object
    # to a dictionary
    for attr in _IMAGE_ATTRIBUTES:
        output[attr] = getattr(image, attr, None)

    # copy the properties over to start so that image properties
    # are not nested in another properties key
    output['properties'] = getattr(image, 'properties', {})
    output['schema'] = image.schema

    # attributes already copied so we copy the rest into properties
    copied = set(_IMAGE_ATTRIBUTES)
    copied.add('properties')

    for image_property in set(image) - copied:
        # previously with glanceclient only set things
        # were on the object that came back but the SDK
        # defines every possible attribute so we need to filter
        if image[image_property]:
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
    # NOTE: Any support for private/shared images in Ironic requires a secure
    # way for ironic to know the original requester:
    #  - If we trust node[instance_info][project_id], we are susceptible to a
    #    node.owner stealing another project's private image by lying in
    #    instance_info.
    #  - As of 2025.1, the project_id attached to the auth context at this
    #    point is more likely to be the nova-computes service user rather
    #    than the original requester. This is a missing feature from the
    #    Ironic/Nova virt driver.

    auth_token = getattr(context, 'auth_token', None)
    conductor_project_id = get_conductor_project_id()
    image_visibility = getattr(image, 'visibility', None)
    image_owner = getattr(image, 'owner', None)
    image_id = getattr(image, 'id', 'unknown')
    image_shared_member_list = get_image_member_list(image_id, context)
    is_admin = 'admin' in getattr(context, 'roles', [])
    project = getattr(context, 'project', 'unknown')

    # If an auth token is present and the config allows access via auth token,
    #  allow image access.
    # NOTE(satoshi): This config should be removed in the H (2026.2) cycle
    if CONF.allow_image_access_via_auth_token and auth_token:
        # We return true here since we want the *user* request context to
        # be able to be used.
        return True
    # If the image visibility is public or community, allow access.
    if image_visibility in ['public', 'community']:
        return True
    # If the user is an admin and the config allows ignoring project checks for
    #  admin tasks, allow access.
    if is_admin and CONF.ignore_project_check_for_admin_tasks:
        return True
    # If the image is private and the owner is the conductor project,
    #  allow access.
    if image_visibility == 'private' and image_owner == conductor_project_id:
        return True
    # If the image is shared and the conductor_project_id is in the shared
    # member list, allow access
    if image_visibility == 'shared'\
            and conductor_project_id in image_shared_member_list:
        return True
    LOG.info(
        'Access to %s owned by %s denied to requester %s',
        image_id, image_owner, project
    )
    return False


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


def get_conductor_project_id():
    global _GLANCE_SESSION
    if not _GLANCE_SESSION:
        _GLANCE_SESSION = keystone.get_session('glance')
    session = _GLANCE_SESSION
    service_auth = keystone.get_auth('glance')

    try:
        if service_auth and hasattr(service_auth, 'get_project_id'):
            return service_auth.get_project_id(session)
        elif hasattr(session, 'get_project_id') and session.auth:
            return session.get_project_id()
    except Exception as e:
        LOG.debug("Error getting conductor project ID: %s", str(e))
    return None


def get_image_member_list(image_id, context):
    try:
        glance_service = service.GlanceImageService(context=context)
        members = glance_service.client.image.members(image_id)
        return [
            member['member_id']
            for member in members
        ]
    except Exception as e:
        LOG.error("Unable to retrieve image members for image %s: %s",
                  image_id, e)
        return []
