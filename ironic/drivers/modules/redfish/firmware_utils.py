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
import shutil
import tempfile
from urllib import parse as urlparse

import jsonschema
from oslo_log import log
from oslo_utils import fileutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import swift
from ironic.conf import CONF

LOG = log.getLogger(__name__)

_UPDATE_FIRMWARE_SCHEMA = {
    "$schema": "http://json-schema.org/schema#",
    "title": "update_firmware clean step schema",
    "type": "array",
    # list of firmware update images
    "items": {
        "type": "object",
        "required": ["url", "checksum"],
        "properties": {
            "url": {
                "description": "URL for firmware file",
                "type": "string",
                "minLength": 1
            },
            "checksum": {
                "description": "SHA1 checksum for firmware file",
                "type": "string",
                "minLength": 1
            },
            "wait": {
                "description": "optional wait time for firmware update",
                "type": "integer",
                "minimum": 1
            },
            "source":
            {
                "description": "optional firmware_source to override global "
                "setting for firmware file",
                "type": "string",
                "enum": ["http", "local", "swift"]
            }
        },
        "additionalProperties": False
    }
}
_FIRMWARE_SUBDIR = 'firmware'


def validate_update_firmware_args(firmware_images):
    """Validate ``update_firmware`` step input argument

    :param firmware_images: args to validate.
    :raises: InvalidParameterValue When argument is not valid
    """
    try:
        jsonschema.validate(firmware_images, _UPDATE_FIRMWARE_SCHEMA)
    except jsonschema.ValidationError as err:
        raise exception.InvalidParameterValue(
            _('Invalid firmware update %(firmware_images)s. Errors: %(err)s')
            % {'firmware_images': firmware_images, 'err': err})


def get_swift_temp_url(parsed_url):
    """Gets Swift temporary URL

    :param parsed_url: Parsed URL from URL in format
        swift://container/[sub-folder/]file
    :returns: Swift temporary URL
    """
    return swift.SwiftAPI().get_temp_url(
        parsed_url.netloc, parsed_url.path.lstrip('/'),
        CONF.redfish.swift_object_expiry_timeout)


def download_to_temp(node, url):
    """Downloads to temporary location from given URL

    :param node: Node for which to download to temporary location
    :param url: URL to download from
    :returns: File path of temporary location file is downloaded to
    """
    parsed_url = urlparse.urlparse(url)
    scheme = parsed_url.scheme.lower()
    if scheme not in ('http', 'swift', 'file'):
        raise exception.InvalidParameterValue(
            _('%(scheme)s is not supported for %(url)s.')
            % {'scheme': scheme, 'url': parsed_url.geturl()})

    tempdir = os.path.join(tempfile.gettempdir(), node.uuid)
    os.makedirs(tempdir, exist_ok=True)
    temp_file = os.path.join(
        tempdir,
        os.path.basename(parsed_url.path))
    LOG.debug('For node %(node)s firmware at %(url)s will be downloaded to '
              'temporary location at %(temp_file)s',
              {'node': node.uuid, 'url': url, 'temp_file': temp_file})
    if scheme == 'http':
        with open(temp_file, 'wb') as tf:
            image_service.HttpImageService().download(url, tf)
    elif scheme == 'swift':
        swift_url = get_swift_temp_url(parsed_url)
        with open(temp_file, 'wb') as tf:
            image_service.HttpImageService().download(swift_url, tf)
    elif scheme == 'file':
        with open(temp_file, 'wb') as tf:
            image_service.FileImageService().download(
                parsed_url.path, tf)

    return temp_file


def verify_checksum(node, checksum, file_path):
    """Verify checksum.

    :param node: Node for which file to verify checksum
    :param checksum: Expected checksum value
    :param file_path: File path for which to verify checksum
    :raises RedfishError: When checksum does not match
    """
    calculated_checksum = fileutils.compute_file_checksum(
        file_path, algorithm='sha1')
    if checksum != calculated_checksum:
        raise exception.RedfishError(
            _('For node %(node)s firmware file %(temp_file)s checksums do not '
              'match. Expected: %(checksum)s, calculated: '
              '%(calculated_checksum)s.')
            % {'node': node.uuid, 'temp_file': file_path, 'checksum': checksum,
               'calculated_checksum': calculated_checksum})


def stage(node, source, temp_file):
    """Stage temporary file to configured location

    :param node: Node for which to stage the file
    :param source: Where to stage the file. Corresponds to
        CONF.redfish.firmware_source.
    :param temp_file: File path of temporary file to stage
    :returns: Tuple of staged URL and source (http or swift) that needs
        cleanup of staged files afterwards.
    :raises RedfishError: If staging to HTTP server has failed.
    """
    staged_url = None
    filename = os.path.basename(temp_file)
    if source in ('http', 'local'):
        http_url = CONF.deploy.external_http_url or CONF.deploy.http_url
        staged_url = urlparse.urljoin(
            http_url, "/".join([_FIRMWARE_SUBDIR, node.uuid, filename]))
        staged_folder = os.path.join(
            CONF.deploy.http_root, _FIRMWARE_SUBDIR, node.uuid)
        staged_path = os.path.join(staged_folder, filename)
        LOG.debug('For node %(node)s temporary file %(temp_file)s will be '
                  'hard-linked or copied to %(staged_path)s and served over '
                  '%(staged_url)s',
                  {'node': node.uuid, 'temp_file': temp_file,
                   'staged_path': staged_path, 'staged_url': staged_url})
        os.makedirs(staged_folder, exist_ok=True)
        try:
            os.link(temp_file, staged_path)
            os.chmod(temp_file, CONF.redfish.file_permission)
        except OSError as oserror:
            LOG.debug("Could not hardlink file %(temp_file)s to location "
                      "%(staged_path)s. Will try to copy it. Error: %(error)s",
                      {'temp_file': temp_file, 'staged_path': staged_path,
                       'error': oserror})
            try:
                shutil.copyfile(temp_file, staged_path)
                os.chmod(staged_path, CONF.redfish.file_permission)
            except IOError as ioerror:
                raise exception.RedfishError(
                    _('For %(node)s failed to copy firmware file '
                      '%(temp_file)s to HTTP server root. Error %(error)s')
                    % {'node': node.uuid, 'temp_file': temp_file,
                       'error': ioerror})

    elif source == 'swift':
        container = CONF.redfish.swift_container
        timeout = CONF.redfish.swift_object_expiry_timeout
        swift_api = swift.SwiftAPI()
        object_name = "/".join([node.uuid, filename])
        swift_api.create_object(
            container,
            object_name,
            temp_file,
            object_headers={'X-Delete-After': str(timeout)})
        staged_url = swift_api.get_temp_url(
            container, object_name, timeout)
        LOG.debug('For node %(node)s temporary file at %(temp_file)s will be '
                  'served from Swift temporary URL %(staged_url)s',
                  {'node': node.uuid, 'temp_file': temp_file,
                   'staged_url': staged_url})

    need_cleanup = 'swift' if source == 'swift' else 'http'
    return staged_url, need_cleanup


def cleanup(node):
    """Clean up staged files

    :param node: Node for which to clean up. Should contain
        'firmware_cleanup' entry in `driver_internal_info` to indicate
        source(s) to be cleaned up.
    """
    # Cleaning up temporary just in case there is something when staging
    # to http or swift has failed.
    temp_dir = os.path.join(tempfile.gettempdir(), node.uuid)
    LOG.debug('For node %(node)s cleaning up temporary files, if any, from '
              '%(temp_dir)s.', {'node': node.uuid, 'temp_dir': temp_dir})
    shutil.rmtree(temp_dir, ignore_errors=True)

    cleanup = node.driver_internal_info.get('firmware_cleanup')
    if not cleanup:
        return

    if 'http' in cleanup:
        http_dir = os.path.join(
            CONF.deploy.http_root, _FIRMWARE_SUBDIR, node.uuid)
        LOG.debug('For node %(node)s cleaning up files from  %(http_dir)s.',
                  {'node': node.uuid, 'http_dir': http_dir})
        shutil.rmtree(http_dir, ignore_errors=True)

    if 'swift' in cleanup:
        swift_api = swift.SwiftAPI()
        container = CONF.redfish.swift_container
        LOG.debug('For node %(node)s cleaning up files from Swift container '
                  '%(container)s.',
                  {'node': node.uuid, 'container': container})
        _, objects = swift_api.connection.get_container(container)
        for o in objects:
            name = o.get('name')
            if name and name.startswith(node.uuid):
                try:
                    swift_api.delete_object(container, name)
                except exception.SwiftOperationError as error:
                    LOG.warning('For node %(node)s failed to clean up '
                                '%(object)s. Error: %(error)s',
                                {'node': node.uuid, 'object': name,
                                 'error': error})
