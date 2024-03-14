# Copyright 2016 Hewlett Packard Enterprise Development Company LP
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
Firmware file processor
"""

import functools
import os
import re
import shutil
import tempfile
import types
from urllib import parse as urlparse

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import swift
from ironic.drivers.modules.ilo import common as ilo_common

# Supported components for firmware update when invoked through manual clean
# step, ``update_firmware``.
SUPPORTED_ILO_FIRMWARE_UPDATE_COMPONENTS = ['ilo', 'cpld', 'power_pic', 'bios',
                                            'chassis']

# Mandatory fields to be provided as part of firmware image update
# with manual clean step
FIRMWARE_IMAGE_INFO_FIELDS = {'url', 'checksum'}

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

proliantutils_error = importutils.try_import('proliantutils.exception')
proliantutils_utils = importutils.try_import('proliantutils.utils')


def verify_firmware_update_args(func):
    """Verifies the firmware update arguments."""
    @functools.wraps(func)
    def wrapper(self, task, **kwargs):
        """Wrapper around ``update_firmware`` call.

        :param task: a TaskManager object.
        :raises: InvalidParameterValue if validation fails for input arguments
                 of firmware update.
        """
        firmware_update_mode = kwargs.get('firmware_update_mode')
        firmware_images = kwargs.get('firmware_images')

        if firmware_update_mode != 'ilo':
            msg = (_("Invalid firmware update mode '%(mode)s' provided for "
                     "node: %(node)s. 'ilo' is the only supported firmware "
                     "update mode.")
                   % {'mode': firmware_update_mode, 'node': task.node.uuid})
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

        if not firmware_images:
            msg = _("Firmware images cannot be an empty list or None.")
            LOG.error(msg)
            raise exception.InvalidParameterValue(msg)

        return func(self, task, **kwargs)

    return wrapper


def _validate_ilo_component(component):
    """Validates component with supported values.

    :param component: name of the component to be validated.
    :raises: InvalidParameterValue, for unsupported firmware component
    """
    if component not in SUPPORTED_ILO_FIRMWARE_UPDATE_COMPONENTS:
        msg = (_("Component '%(component)s' for firmware update is not "
                 "supported in 'ilo' based firmware update. Supported "
                 "values are: %(supported_components)s") %
               {'component': component, 'supported_components': (
                ", ".join(SUPPORTED_ILO_FIRMWARE_UPDATE_COMPONENTS))})
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)


def _validate_sum_components(components):
    """Validates components' file extension with supported values.

    :param components: A list of components to be updated.
    :raises: InvalidParameterValue, for unsupported firmware component
    """
    not_supported = []
    for component in components:
        if not re.search('\\.(scexe|exe|rpm)$', component):
            not_supported.append(component)

    if not_supported:
        msg = (_("The component files '%s' provided are not supported in "
                 "'SUM' based firmware update. The valid file extensions are "
                 "'scexe', 'exe', 'rpm'.") %
               ', '.join(x for x in not_supported))
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)


def get_and_validate_firmware_image_info(firmware_image_info,
                                         firmware_update_mode):
    """Validates the firmware image info and returns the retrieved values.

    :param firmware_image_info: dict object containing the firmware image info
    :raises: MissingParameterValue, for missing fields (or values) in
             image info.
    :raises: InvalidParameterValue, for unsupported firmware component
    :returns: tuple of firmware url, checksum, component when the firmware
        update is ilo based.
    """
    image_info = firmware_image_info or {}

    LOG.debug("Validating firmware image info: %s ... in progress", image_info)
    missing_fields = []
    for field in FIRMWARE_IMAGE_INFO_FIELDS:
        if not image_info.get(field):
            missing_fields.append(field)

    if firmware_update_mode == 'ilo' and not image_info.get('component'):
        missing_fields.append('component')

    if missing_fields:
        msg = (_("Firmware image info: %(image_info)s is missing the "
                 "required %(missing)s field/s.") %
               {'image_info': image_info,
                'missing': ", ".join(missing_fields)})
        LOG.error(msg)
        raise exception.MissingParameterValue(msg)

    if firmware_update_mode == 'sum':
        component = image_info.get('components')
        if component:
            _validate_sum_components(component)
    else:
        component = image_info['component'].lower()
        _validate_ilo_component(component)
        LOG.debug("Validating firmware image info: %s ... done", image_info)
        return image_info['url'], image_info['checksum'], component


class FirmwareProcessor(object):
    """Firmware file processor

    This class helps in downloading the firmware file from url, extracting
    the firmware file (if its in compact format) and makes it ready for
    firmware update operation. In future, methods can be added as and when
    required to extend functionality for different firmware file types.
    """
    def __init__(self, url):
        # :attribute ``self.parsed_url``: structure returned by urlparse
        self._fine_tune_fw_processor(url)

    def _fine_tune_fw_processor(self, url):
        """Fine tunes the firmware processor object based on specified url

        :param url: url of firmware file
        :raises: InvalidParameterValue, for unsupported firmware url
        """
        parsed_url = urlparse.urlparse(url)
        self.parsed_url = parsed_url

        url_scheme = parsed_url.scheme
        if url_scheme == 'file':
            self._download_fw_to = types.MethodType(
                _download_file_based_fw_to, self)
        elif url_scheme in ('http', 'https'):
            self._download_fw_to = types.MethodType(
                _download_http_based_fw_to, self)
        elif url_scheme == 'swift':
            self._download_fw_to = types.MethodType(
                _download_swift_based_fw_to, self)
        else:
            raise exception.InvalidParameterValue(
                _('This method does not support URL scheme %(url_scheme)s. '
                  'Invalid URL %(url)s. The supported firmware URL schemes '
                  'are "file", "http", "https" and "swift"') %
                {'url': url, 'url_scheme': url_scheme})

    def process_fw_on(self, node, expected_checksum):
        """Processes the firmware file from the url

        This is the template method which downloads the firmware file from
        url, verifies checksum and extracts the firmware and makes it ready
        for firmware update operation. ``_download_fw_to`` method is set in
        the firmware processor object creation factory method,
        ``get_fw_processor()``, based on the url type.
        :param node: a single Node.
        :param expected_checksum: checksum to be checked against.
        :returns: wrapper object of raw firmware image location
        :raises: IloOperationError, on failure to process firmware file.
        :raises: ImageDownloadFailed, on failure to download the original file.
        :raises: ImageRefValidationFailed, on failure to verify the checksum.
        :raises: SwiftOperationError, if upload to Swift fails.
        :raises: ImageUploadFailed, if upload to web server fails.
        """
        filename = os.path.basename(self.parsed_url.path)
        # create a temp directory where firmware file will be downloaded
        temp_dir = tempfile.mkdtemp()
        target_file = os.path.join(temp_dir, filename)

        # Note(deray): Operations performed in here:
        #
        #    1. Download the firmware file to the target file.
        #    2. Verify the checksum of the downloaded file.
        #    3. Extract the raw firmware file from its compact format
        #
        try:
            LOG.debug("For firmware update, downloading firmware file "
                      "%(src_file)s to: %(target_file)s ...",
                      {'src_file': self.parsed_url.geturl(),
                       'target_file': target_file})
            self._download_fw_to(target_file)
            LOG.debug("For firmware update, verifying checksum of file: "
                      "%(target_file)s ...", {'target_file': target_file})
            ilo_common.verify_image_checksum(target_file, expected_checksum)
            # Extracting raw firmware file from target_file ...
            fw_image_location_obj, is_different_file = (_extract_fw_from_file(
                node, target_file))
        except exception.IronicException:
            with excutils.save_and_reraise_exception():
                # delete the target file along with temp dir and
                # re-raise the exception
                shutil.rmtree(temp_dir, ignore_errors=True)

        # Note(deray): In case of raw (no need for extraction) firmware files,
        # the same firmware file is returned from the extract method.
        # Hence, don't blindly delete the firmware file which gets passed on
        # to extraction operation after successful extract. Check whether the
        # file is same or not and then go ahead deleting it.
        if is_different_file:
            # delete the entire downloaded content along with temp dir.
            shutil.rmtree(temp_dir, ignore_errors=True)

        LOG.info("Final processed firmware location: %s",
                 fw_image_location_obj.fw_image_location)
        return fw_image_location_obj


def _download_file_based_fw_to(self, target_file):
    """File based firmware file downloader (copier)

    It copies the file (url) to temporary location (file location).
    Original firmware file location (url) is expected in the format
    "file:///tmp/.."
    :param target_file: destination file for copying the original firmware
                        file.
    :raises: ImageDownloadFailed, on failure to copy the original file.
    """
    src_file = self.parsed_url.path
    with open(target_file, 'wb') as fd:
        image_service.FileImageService().download(src_file, fd)


def _download_http_based_fw_to(self, target_file):
    """HTTP based firmware file downloader

    It downloads the file (url) to temporary location (file location).
    Original firmware file location (url) is expected in the format
    "http://.."
    :param target_file: destination file for downloading the original firmware
                        file.
    :raises: ImageDownloadFailed, on failure to download the original file.
    """
    src_file = self.parsed_url.geturl()
    with open(target_file, 'wb') as fd:
        image_service.HttpImageService().download(src_file, fd)


def get_swift_url(parsed_url):
    """Gets swift temp url.

    It generates a temp url for the swift based firmware url to the target
    file. Expecting url as swift://containername/objectname.

    :param parsed_url: Parsed url object.
    :raises: SwiftOperationError, on failure to get url from swift.
    """
    # Extract container name
    container = parsed_url.netloc
    # Extract the object name from the path of the form:
    #    ``/objectname`` OR
    #    ``/pseudo-folder/objectname``
    # stripping the leading '/' character.
    objectname = parsed_url.path.lstrip('/')
    timeout = CONF.ilo.swift_object_expiry_timeout
    # Generate temp url using swift API
    return swift.SwiftAPI().get_temp_url(container, objectname, timeout)


def _download_swift_based_fw_to(self, target_file):
    """Swift based firmware file downloader

    It downloads the firmware file via http based downloader to the target
    file. Expecting url as swift://containername/objectname
    :param target_file: destination file for downloading the original firmware
                        file.
    :raises: ImageDownloadFailed, on failure to download the original file.
    """
    # set the parsed_url attribute to the newly created tempurl from swift and
    # delegate the downloading job to the http_based downloader
    self.parsed_url = urlparse.urlparse(get_swift_url(self.parsed_url))
    _download_http_based_fw_to(self, target_file)


def _extract_fw_from_file(node, target_file):
    """Extracts firmware image file.

    Extracts the firmware image file thru proliantutils and uploads it to the
    conductor webserver, if needed.
    :param node: an Ironic node object.
    :param target_file: firmware file to be extracted from
    :returns: tuple of:
                a) wrapper object of raw firmware image location
                b) a boolean, depending upon whether the raw firmware file was
                   already in raw format(same file remains, no need to extract)
                   or compact format (thereby extracted and hence different
                   file). If uploaded then, then also its a different file.
    :raises: ImageUploadFailed, if upload to web server fails.
    :raises: SwiftOperationError, if upload to Swift fails.
    :raises: IloOperationError, on failure to process firmware file.
    """
    ilo_object = ilo_common.get_ilo_object(node)

    try:
        # Note(deray): Based upon different iLO firmwares, the firmware file
        # which needs to be updated has to be either an http/https or a simple
        # file location. If it has to be a http/https location, then conductor
        # will take care of uploading the firmware file to web server or
        # swift (providing a temp url).
        fw_image_location, to_upload, is_extracted = (
            proliantutils_utils.process_firmware_image(target_file,
                                                       ilo_object))
    except (proliantutils_error.InvalidInputError,
            proliantutils_error.ImageExtractionFailed) as proliantutils_exc:
        operation = _("Firmware file extracting as part of manual cleaning")
        raise exception.IloOperationError(operation=operation,
                                          error=proliantutils_exc)

    is_different_file = is_extracted
    fw_image_filename = os.path.basename(fw_image_location)
    fw_image_location_obj = FirmwareImageLocation(fw_image_location,
                                                  fw_image_filename)
    if to_upload:
        is_different_file = True
        try:
            if CONF.ilo.use_web_server_for_images:
                # upload firmware image file to conductor webserver
                LOG.debug("For firmware update on node %(node)s, hosting "
                          "firmware file %(firmware_image)s on web server ...",
                          {'firmware_image': fw_image_location,
                           'node': node.uuid})
                fw_image_uploaded_url = ilo_common.copy_image_to_web_server(
                    fw_image_location, fw_image_filename)

                fw_image_location_obj.fw_image_location = fw_image_uploaded_url
                fw_image_location_obj.remove = types.MethodType(
                    _remove_webserver_based_me, fw_image_location_obj)
            else:
                # upload firmware image file to swift
                LOG.debug("For firmware update on node %(node)s, hosting "
                          "firmware file %(firmware_image)s on swift ...",
                          {'firmware_image': fw_image_location,
                           'node': node.uuid})
                fw_image_uploaded_url = ilo_common.copy_image_to_swift(
                    fw_image_location, fw_image_filename)

                fw_image_location_obj.fw_image_location = fw_image_uploaded_url
                fw_image_location_obj.remove = types.MethodType(
                    _remove_swift_based_me, fw_image_location_obj)
        finally:
            if is_extracted:
                # Note(deray): remove the file `fw_image_location` irrespective
                # of status of uploading (success or failure) and only if
                # extracted (and not passed as in plain binary format). If the
                # file is passed in binary format, then the invoking method
                # takes care of handling the deletion of the file.
                ilo_common.remove_single_or_list_of_files(fw_image_location)

        LOG.debug("For firmware update on node %(node)s, hosting firmware "
                  "file: %(fw_image_location)s ... done. Hosted firmware "
                  "file: %(fw_image_uploaded_url)s",
                  {'fw_image_location': fw_image_location, 'node': node.uuid,
                   'fw_image_uploaded_url': fw_image_uploaded_url})
    else:
        fw_image_location_obj.remove = types.MethodType(
            _remove_file_based_me, fw_image_location_obj)

    return fw_image_location_obj, is_different_file


class FirmwareImageLocation(object):
    """Firmware image location class

    This class acts as a wrapper class for the firmware image location.
    It primarily helps in removing the firmware files from their respective
    locations, made available for firmware update operation.
    """

    def __init__(self, fw_image_location, fw_image_filename):
        """Keeps hold of image location and image filename"""
        self.fw_image_location = fw_image_location
        self.fw_image_filename = fw_image_filename

    def remove(self):
        """Exposed method to remove the wrapped firmware file

        This method gets overridden by the remove method for the respective
        type of firmware file location it wraps.
        """
        pass


def _remove_file_based_me(self):
    """Removes file based firmware image location"""
    ilo_common.remove_single_or_list_of_files(self.fw_image_location)


def _remove_swift_based_me(self):
    """Removes swift based firmware image location (by its object name)"""
    ilo_common.remove_image_from_swift(self.fw_image_filename,
                                       "firmware update")


def _remove_webserver_based_me(self):
    """Removes webserver based firmware image location (by its file name)"""
    ilo_common.remove_image_from_web_server(self.fw_image_filename)
