# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
Common functionalities shared between different iLO modules.
"""

import os
import shutil
import tempfile
from urllib import parse as urlparse

from ironic_lib import utils as ironic_utils
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import importutils
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import images
from ironic.common import swift
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import boot_mode_utils

ilo_client = importutils.try_import('proliantutils.ilo.client')
ilo_error = importutils.try_import('proliantutils.exception')

STANDARD_LICENSE = 1
ESSENTIALS_LICENSE = 2
ADVANCED_LICENSE = 3

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'ilo_address': _("IP address or hostname of the iLO. Required."),
    'ilo_username': _("username for the iLO with administrator privileges. "
                      "Required."),
    'ilo_password': _("password for ilo_username. Required.")
}
OPTIONAL_PROPERTIES = {
    'client_port': _("port to be used for iLO operations. Optional."),
    'client_timeout': _("timeout (in seconds) for iLO operations. Optional."),
    'ca_file': _("CA certificate file to validate iLO. This "
                 "attibute is deprecated and will be removed in "
                 "future release. Optional"),
    'ilo_verify_ca': _("Either a Boolean value, a path to a CA_BUNDLE "
                       "file or directory with certificates of trusted "
                       "CAs. If set to True the driver will verify the "
                       "host certificates; if False the driver will ignore "
                       "verifying the SSL certificate. If it\'s a path the "
                       "driver will use the specified certificate or one of "
                       "the certificates in the directory. Defaults to True. "
                       "Optional")
}

SNMP_PROPERTIES = {
    'snmp_auth_user': _("User for SNMPv3. "
                        "Required for SNMP inspection"),
    'snmp_auth_prot_password': _("Authentication Protocol Passphrase. "
                                 "Required for SNMP inspection"),
    'snmp_auth_priv_password': _("Authentication Privacy Passphrase. "
                                 "Required for SNMP inspection"),
}

SNMP_OPTIONAL_PROPERTIES = {
    'snmp_auth_protocol': _("Authentication Protocol. Optional, used "
                            "for SNMP inspection. If not specified, the "
                            "default value as 'MD5' is used."),
    'snmp_auth_priv_protocol': _("Privacy Protocol. Optional, "
                                 "used for SNMP inspection. "
                                 "If not specified, the default value "
                                 "as 'DES' is used.")
}

CONSOLE_PROPERTIES = {
    'console_port': _("node's UDP port to connect to. Only required for "
                      "console access.")
}
CLEAN_PROPERTIES = {
    'ilo_change_password': _("new password for iLO. Required if the clean "
                             "step 'reset_ilo_credential' is enabled.")
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
DEFAULT_BOOT_MODE = 'LEGACY'

BOOT_MODE_GENERIC_TO_ILO = {'bios': 'legacy', 'uefi': 'uefi'}
BOOT_MODE_ILO_TO_GENERIC = dict(
    (v, k) for (k, v) in BOOT_MODE_GENERIC_TO_ILO.items())

POST_NULL_STATE = 'Null'
""" Node is in Null post state."""

POST_UNKNOWN_STATE = "Unknown"
""" Node is in Unknown post state."""

POST_RESET_STATE = "Reset"
""" Node is in Reset post state."""

POST_POWEROFF_STATE = "PowerOff"
""" Node is in PowerOff post state."""

POST_INPOST_STATE = "InPost"
""" Node is in InPost post state."""

POST_INPOSTDISCOVERY_STATE = "InPostDiscoveryComplete"
""" Node is in InPostDiscoveryComplete post state."""

POST_FINISHEDPOST_STATE = "FinishedPost"
""" Node is in FinishedPost post state."""

SUPPORTED_BOOT_MODE_LEGACY_BIOS_ONLY = 'legacy bios only'
""" Node supports only legacy BIOS boot mode."""

SUPPORTED_BOOT_MODE_UEFI_ONLY = 'uefi only'
""" Node supports only UEFI boot mode."""

SUPPORTED_BOOT_MODE_LEGACY_BIOS_AND_UEFI = 'legacy bios and uefi'
""" Node supports both legacy BIOS and UEFI boot mode."""

SUPPORTED_SECURITY_PARAMETERS = (
    ['password_complexity', 'require_login_for_ilo_rbsu', 'ipmi_over_lan',
     'secure_boot', 'require_host_authentication'])


def validate_security_parameter_values(sec_param_info):
    """Validate security parameter with valid values.

    :param sec_param_info: dict object containing the security parameter info
    :raises: MissingParameterValue, for missing fields (or values) in
             security parameter info.
    :raises: InvalidParameterValue, for unsupported security parameter
    :returns: tuple of security param, ignore and enable parameters.
    """
    info = sec_param_info or {}

    LOG.debug("Validating security param info: %s in progress", info)
    param = info.get('param')

    if not param:
        msg = (_("Security parameter info: %(info)s is missing the "
                 "required 'param' field.") % {'info': info})
        LOG.error(msg)
        raise exception.MissingParameterValue(msg)

    if param not in SUPPORTED_SECURITY_PARAMETERS:
        msg = (_("Security parameter '%(param)s' is not a valid parameter. "
                 "Supported values are: %(supported_params)s") %
               {'param': param, 'supported_params': (
                ", ".join(SUPPORTED_SECURITY_PARAMETERS))})
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)

    ignored = info.get('ignore', False)
    ignored = strutils.bool_from_string(ignored, default=False)
    enable = info.get('enable', True)
    enable = strutils.bool_from_string(enable, default=True)

    return param, enable, ignored


def copy_image_to_web_server(source_file_path, destination):
    """Copies the given image to the http web server.

    This method copies the given image to the http_root location.
    It enables read-write access to the image else the deploy fails
    as the image file at the web_server url is inaccessible.

    :param source_file_path: The absolute path of the image file
                             which needs to be copied to the
                             web server root.
    :param destination: The name of the file that
                        will contain the copied image.
    :raises: ImageUploadFailed exception if copying the source
             file to the web server fails.
    :returns: image url after the source image is uploaded.

    """

    image_url = urlparse.urljoin(CONF.deploy.http_url, destination)
    image_path = os.path.join(CONF.deploy.http_root, destination)
    try:
        shutil.copyfile(source_file_path, image_path)
    except IOError as exc:
        raise exception.ImageUploadFailed(image_name=destination,
                                          web_server=CONF.deploy.http_url,
                                          reason=exc)
    os.chmod(image_path, 0o644)
    return image_url


def remove_image_from_web_server(object_name):
    """Removes the given image from the configured web server.

    This method removes the given image from the http_root location,
    if the image exists.

    :param object_name: The name of the image file which needs to be removed
                        from the web server root.
    """
    image_path = os.path.join(CONF.deploy.http_root, object_name)
    ironic_utils.unlink_without_raise(image_path)


def copy_image_to_swift(source_file_path, destination_object_name):
    """Uploads the given image to swift.

    This method copies the given image to swift.

    :param source_file_path: The absolute path of the image file which needs
                             to be copied to swift.
    :param destination_object_name: The name of the object that will contain
                                    the copied image.
    :raises: SwiftOperationError, if any operation with Swift fails.
    :returns: temp url from swift after the source image is uploaded.

    """
    container = CONF.ilo.swift_ilo_container
    timeout = CONF.ilo.swift_object_expiry_timeout

    object_headers = {'X-Delete-After': str(timeout)}
    swift_api = swift.SwiftAPI()
    swift_api.create_object(container, destination_object_name,
                            source_file_path, object_headers=object_headers)
    temp_url = swift_api.get_temp_url(container, destination_object_name,
                                      timeout)
    LOG.debug("Uploaded image %(destination_object_name)s to %(container)s.",
              {'destination_object_name': destination_object_name,
               'container': container})
    return temp_url


def remove_image_from_swift(object_name, associated_with=None):
    """Removes the given image from swift.

    This method removes the given image name from swift. It deletes the
    image if it exists in CONF.ilo.swift_ilo_container

    :param object_name: The name of the object which needs to be removed
                        from swift.
    :param associated_with: string to depict the component/operation this
                            object is associated to.
    """
    container = CONF.ilo.swift_ilo_container
    try:
        swift_api = swift.SwiftAPI()
        swift_api.delete_object(container, object_name)
    except exception.SwiftObjectNotFoundError as e:
        LOG.info("Temporary object %(associated_with_msg)s "
                 "was already deleted from Swift. Error: %(err)s",
                 {'associated_with_msg':
                     ("associated with %s " % associated_with
                         if associated_with else ""), 'err': e})
    except exception.SwiftOperationError as e:
        LOG.exception("Error while deleting temporary swift object "
                      "%(object_name)s %(associated_with_msg)s from "
                      "%(container)s. Error: %(err)s",
                      {'object_name': object_name, 'container': container,
                       'associated_with_msg':
                           ("associated with %s" % associated_with
                               if associated_with else ""), 'err': e})


def parse_driver_info(node):
    """Gets the driver specific Node info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver.

    :param node: an ironic Node object.
    :returns: a dict containing information from driver_info (or where
        applicable, config values).
    :raises: InvalidParameterValue if any parameters are incorrect
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    info = node.driver_info
    d_info = {}

    missing_info = []
    for param in REQUIRED_PROPERTIES:
        try:
            d_info[param] = info[param]
        except KeyError:
            missing_info.append(param)
    if missing_info:
        raise exception.MissingParameterValue(_(
            "The following required iLO parameters are missing from the "
            "node's driver_info: %s") % missing_info)

    optional_info = _parse_optional_driver_info(node)
    d_info.update(optional_info)

    snmp_info = _parse_snmp_driver_info(info)
    if snmp_info:
        d_info.update(snmp_info)

    for param in CONSOLE_PROPERTIES:
        value = info.get(param)
        if value:
            # Currently there's only "console_port" parameter
            # in CONSOLE_PROPERTIES
            if param == "console_port":
                d_info[param] = utils.validate_network_port(value, param)

    return d_info


def _parse_snmp_driver_info(info):
    """Parses the SNMP related driver_info parameters.

    :param info: driver_info dictionary.
    :returns: a dictionary containing SNMP information.
    :raises exception.MissingParameterValue: if any of the mandatory
        parameter values are not provided.
    :raises exception.InvalidParameterValue: if the value provided
        for SNMP_OPTIONAL_PROPERTIES has an invalid value.
    """
    snmp_info = {}
    missing_info = []
    valid_values = {'snmp_auth_protocol': ['MD5', 'SHA'],
                    'snmp_auth_priv_protocol': ['AES', 'DES']}
    if info.get('snmp_auth_user'):
        for param in SNMP_PROPERTIES:
            try:
                snmp_info[param] = info[param]
            except KeyError:
                missing_info.append(param)
        if missing_info:
            raise exception.MissingParameterValue(_(
                "The following required SNMP parameters are missing from the "
                "node's driver_info: %s") % missing_info)

        for param in SNMP_OPTIONAL_PROPERTIES:
            value = None
            try:
                value = str(info[param]).upper()
            except KeyError:
                pass
            if value:
                if value not in valid_values[param]:
                    raise exception.InvalidParameterValue(_(
                        "Invalid value %(value)s given for driver_info "
                        "parameter %(param)s") % {'param': param,
                                                  'value': info[param]})
                snmp_info[param] = value
    else:
        snmp_info = None
    return snmp_info


def _parse_optional_driver_info(node):
    """Parses the optional driver_info parameters.

    :param node: an ironic Node object.
    :returns: a dictionary containing information of optional properties.
    :raises: InvalidParameterValue if any parameters are incorrect
    """
    info = node.driver_info
    optional_info = {}
    not_integers = []

    for param in OPTIONAL_PROPERTIES:
        if param != 'ilo_verify_ca':
            value = info.get(param, CONF.ilo.get(param))

        if param == "client_port":
            optional_info[param] = utils.validate_network_port(value, param)
        elif param == "client_timeout":
            try:
                optional_info[param] = int(value)
            except ValueError:
                not_integers.append(param)

    if not_integers:
        raise exception.InvalidParameterValue(_(
            "The following iLO parameters from the node's driver_info "
            "should be integers: %s") % not_integers)

    ca_file_value = info.get('ca_file', CONF.ilo.get('ca_file'))
    verify_ca = info.get('ilo_verify_ca', CONF.ilo.get('verify_ca'))

    if ca_file_value:
        LOG.warning("The `driver_info/ca_file` parameter is deprecated "
                    "in favor of `driver_info/ilo_verify_ca` parameter. "
                    "Please use `driver_info/ilo_verify_ca` instead of "
                    "`driver_info/ca_file` in node %(node)s "
                    "configuration.", {'node': node.uuid})

        if not os.path.isfile(ca_file_value):
            raise exception.InvalidParameterValue(_(
                'ca_file "%(value)s" is not found.') %
                {'value': ca_file_value})
        optional_info['verify_ca'] = ca_file_value
    else:
        # Check if ilo_verify_ca is a Boolean or a file/directory
        # in the file-system
        if isinstance(verify_ca, str):
            if not os.path.isdir(verify_ca) and not os.path.isfile(verify_ca):
                try:
                    verify_ca = strutils.bool_from_string(verify_ca,
                                                          strict=True)
                except ValueError:
                    raise exception.InvalidParameterValue(
                        _('Invalid value type set in driver_info/'
                          'ilo_verify_ca on node %(node)s. '
                          'The value should be a Boolean or the path '
                          'to a file/directory, not "%(value)s"'
                          ) % {'value': verify_ca, 'node': node.uuid})
        elif not isinstance(verify_ca, bool):
            raise exception.InvalidParameterValue(
                _('Invalid value type set in driver_info/ilo_verify_ca '
                  'on node %(node)s. The value should be a Boolean '
                  'or the path to a file/directory, not "%(value)s"'
                  ) % {'value': verify_ca, 'node': node.uuid})
        optional_info['verify_ca'] = verify_ca

    return optional_info


def get_ilo_object(node):
    """Gets an IloClient object from proliantutils library.

    Given an ironic node object, this method gives back a IloClient object
    to do operations on the iLO.

    :param node: an ironic node object.
    :returns: an IloClient object.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    driver_info = parse_driver_info(node)
    snmp_info = _parse_snmp_driver_info(driver_info)
    info = {}
    # This mapping is done as per what proliantutils expect the input
    # to be. This will be removed once proliantutils is fixed for this
    # in its next release.
    if snmp_info:
        info['snmp_inspection'] = True
        info['auth_user'] = snmp_info['snmp_auth_user']
        info['auth_prot_pp'] = snmp_info['snmp_auth_prot_password']
        info['auth_priv_pp'] = snmp_info['snmp_auth_priv_password']
        if snmp_info.get('snmp_auth_protocol'):
            info['auth_protocol'] = str(snmp_info['snmp_auth_protocol'])
        if snmp_info.get('snmp_auth_priv_protocol'):
            info['priv_protocol'] = str(snmp_info['snmp_auth_priv_protocol'])
    else:
        info = None
    ilo_object = ilo_client.IloClient(driver_info['ilo_address'],
                                      driver_info['ilo_username'],
                                      driver_info['ilo_password'],
                                      driver_info['client_timeout'],
                                      driver_info['client_port'],
                                      cacert=driver_info['verify_ca'],
                                      snmp_credentials=info)
    return ilo_object


def update_ipmi_properties(task):
    """Update ipmi properties to node driver_info

    :param task: a task from TaskManager.
    """
    node = task.node
    info = node.driver_info

    # updating ipmi credentials
    info['ipmi_address'] = info.get('ilo_address')
    info['ipmi_username'] = info.get('ilo_username')
    info['ipmi_password'] = info.get('ilo_password')

    if 'console_port' in info:
        info['ipmi_terminal_port'] = info['console_port']

    # saving ipmi credentials to task object
    task.node.driver_info = info


def _get_floppy_image_name(node):
    """Returns the floppy image name for a given node.

    :param node: the node for which image name is to be provided.
    """
    return "image-%s" % node.uuid


def _prepare_floppy_image(task, params):
    """Prepares the floppy image for passing the parameters.

    This method prepares a temporary vfat filesystem image. Then it adds
    a file into the image which contains the parameters to be passed to
    the ramdisk. After adding the parameters, it then uploads the file either
    to Swift in 'swift_ilo_container', setting it to auto-expire after
    'swift_object_expiry_timeout' seconds or in web server. Then it returns
    the temp url for the Swift object or the http url for the uploaded floppy
    image depending upon value of CONF.ilo.use_web_server_for_images.

    :param task: a TaskManager instance containing the node to act on.
    :param params: a dictionary containing 'parameter name'->'value' mapping
        to be passed to the deploy ramdisk via the floppy image.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: ImageUploadFailed, if copying the source file to the
             web server fails.
    :raises: SwiftOperationError, if any operation with Swift fails.
    :returns: the HTTP image URL or the Swift temp url for the floppy image.
    """
    with tempfile.NamedTemporaryFile(
            dir=CONF.tempdir) as vfat_image_tmpfile_obj:

        vfat_image_tmpfile = vfat_image_tmpfile_obj.name
        images.create_vfat_image(vfat_image_tmpfile, parameters=params)
        object_name = _get_floppy_image_name(task.node)
        if CONF.ilo.use_web_server_for_images:
            image_url = copy_image_to_web_server(vfat_image_tmpfile,
                                                 object_name)
        else:
            image_url = copy_image_to_swift(vfat_image_tmpfile, object_name)

        return image_url


def destroy_floppy_image_from_web_server(node):
    """Removes the temporary floppy image.

    It removes the floppy image created for deploy.
    :param node: an ironic node object.
    """

    object_name = _get_floppy_image_name(node)
    remove_image_from_web_server(object_name)


def attach_vmedia(node, device, url):
    """Attaches the given url as virtual media on the node.

    :param node: an ironic node object.
    :param device: the virtual media device to attach
    :param url: the http/https url to attach as the virtual media device
    :raises: IloOperationError if insert virtual media failed.
    """
    ilo_object = get_ilo_object(node)

    try:
        ilo_object.insert_virtual_media(url, device=device)
        ilo_object.set_vm_status(
            device=device, boot_option='CONNECT', write_protect='YES')
    except ilo_error.IloError as ilo_exception:
        operation = _("Inserting virtual media %s") % device
        raise exception.IloOperationError(
            operation=operation, error=ilo_exception)

    LOG.info("Attached virtual media %s successfully.", device)


def set_boot_mode(node, boot_mode):
    """Sets the node to boot using boot_mode for the next boot.

    :param node: an ironic node object.
    :param boot_mode: Next boot mode.
    :raises: IloOperationError if setting boot mode failed.
    """
    ilo_object = get_ilo_object(node)

    try:
        p_boot_mode = ilo_object.get_pending_boot_mode()
    except ilo_error.IloCommandNotSupportedError:
        p_boot_mode = DEFAULT_BOOT_MODE

    if p_boot_mode:
        if BOOT_MODE_ILO_TO_GENERIC[p_boot_mode.lower()] == boot_mode:
            LOG.info("Node %(uuid)s pending boot mode is %(boot_mode)s.",
                     {'uuid': node.uuid, 'boot_mode': boot_mode})
            return

    try:
        ilo_object.set_pending_boot_mode(
            BOOT_MODE_GENERIC_TO_ILO[boot_mode].upper())
    except ilo_error.IloError as ilo_exception:
        operation = _("Setting %s as boot mode") % boot_mode
        raise exception.IloOperationError(
            operation=operation, error=ilo_exception)

    LOG.info("Node %(uuid)s boot mode is set to %(boot_mode)s.",
             {'uuid': node.uuid, 'boot_mode': boot_mode})


def get_current_boot_mode(node):
    """Get the current boot mode for a node.

    :param node: an ironic node object.
    :raises: IloOperationError if failed to fetch boot mode.
    :raises: IloOperationNotSupported if node does not support getting pending
             boot mode.
    """
    ilo_object = get_ilo_object(node)
    operation = _("Get current boot mode")
    try:
        c_boot_mode = ilo_object.get_current_boot_mode()
        return BOOT_MODE_ILO_TO_GENERIC[c_boot_mode.lower()]
    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)


def update_boot_mode(task):
    """Update instance_info with boot mode to be used for deploy.

    This method updates instance_info with boot mode to be used for
    deploy if node properties['capabilities'] do not have boot_mode.
    It sets the boot mode on the node.

    :param task: Task object.
    :raises: IloOperationError if setting boot mode failed.
    """

    node = task.node
    boot_mode = boot_mode_utils.get_boot_mode_for_deploy(node)

    # No boot mode found. Check if default_boot_mode is defined
    if not boot_mode and (CONF.ilo.default_boot_mode in ['bios', 'uefi']):
        boot_mode = CONF.ilo.default_boot_mode
        driver_internal_info = node.driver_internal_info
        driver_internal_info['deploy_boot_mode'] = boot_mode
        node.driver_internal_info = driver_internal_info
        node.save()

    # Boot mode is computed, setting it for the deploy
    if boot_mode:
        LOG.debug("Node %(uuid)s boot mode is being set to %(boot_mode)s",
                  {'uuid': node.uuid, 'boot_mode': boot_mode})
        set_boot_mode(node, boot_mode)
        return

    # Computing boot mode based on boot mode settings on bare metal
    LOG.debug("Check pending boot mode for node %s.", node.uuid)
    ilo_object = get_ilo_object(node)

    try:
        boot_mode = ilo_object.get_pending_boot_mode()
    except ilo_error.IloCommandNotSupportedError:
        boot_mode = 'legacy'

    if boot_mode != 'UNKNOWN':
        boot_mode = BOOT_MODE_ILO_TO_GENERIC[boot_mode.lower()]

    if boot_mode == 'UNKNOWN':
        # NOTE(faizan) ILO will return this in remote cases and mostly on
        # the nodes which supports UEFI. Such nodes mostly comes with UEFI
        # as default boot mode. So we will try setting bootmode to UEFI
        # and if it fails then we fall back to BIOS boot mode.
        try:
            boot_mode = 'uefi'
            ilo_object.set_pending_boot_mode(
                BOOT_MODE_GENERIC_TO_ILO[boot_mode].upper())
        except ilo_error.IloError as ilo_exception:
            operation = _("Setting %s as boot mode") % boot_mode
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)

        LOG.debug("Node %(uuid)s boot mode is being set to %(boot_mode)s "
                  "as pending boot mode is unknown.",
                  {'uuid': node.uuid, 'boot_mode': boot_mode})

    driver_internal_info = node.driver_internal_info
    driver_internal_info['deploy_boot_mode'] = boot_mode
    node.driver_internal_info = driver_internal_info
    node.save()


def setup_vmedia(task, iso, ramdisk_options=None):
    """Attaches virtual media and sets it as boot device.

    This method attaches the given bootable ISO as virtual media, prepares the
    arguments for ramdisk in virtual media floppy.

    :param task: a TaskManager instance containing the node to act on.
    :param iso: a bootable ISO image href to attach to. Should be either
                of below:

                * A Swift object - It should be of format
                  ``swift:<object-name>``.
                  It is assumed that the image object is present in
                  CONF.ilo.swift_ilo_container;
                * A Glance image - It should be format
                  ``glance://<glance-image-uuid>``
                  or just ``<glance-image-uuid>``;
                * An HTTP URL.
    :param ramdisk_options: the options to be passed to the ramdisk in virtual
                            media floppy.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    setup_vmedia_for_boot(task, iso, ramdisk_options)

    # In UEFI boot mode, upon inserting virtual CDROM, one has to reset the
    # system to see it as a valid boot device in persistent boot devices.
    # But virtual CDROM device is always available for one-time boot.
    # During enable/disable of secure boot settings, iLO internally resets
    # the server twice. But it retains one time boot settings across internal
    # resets. Hence no impact of this change for secure boot deploy.
    manager_utils.node_set_boot_device(task, boot_devices.CDROM)


def setup_vmedia_for_boot(task, boot_iso, parameters=None):
    """Sets up the node to boot from the given ISO image.

    This method attaches the given boot_iso on the node and passes
    the required parameters to it via virtual floppy image.

    :param task: a TaskManager instance containing the node to act on.
    :param boot_iso: a bootable ISO image to attach to. Should be either
                     of below:

                     * A Swift object - It should be of format
                       ``swift:<object-name>``.
                       It is assumed that the image object is present in
                       CONF.ilo.swift_ilo_container;
                     * A Glance image - It should be format
                       ``glance://<glance-image-uuid>``
                       or just ``<glance-image-uuid>``;
                     * An HTTP URL.
    :param parameters: the parameters to pass in the virtual floppy image
                       in a dictionary.  This is optional.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: SwiftOperationError, if any operation with Swift fails.
    :raises: IloOperationError, if attaching virtual media failed.
    """
    LOG.info("Setting up node %s to boot from virtual media",
             task.node.uuid)
    if parameters:
        floppy_image_temp_url = _prepare_floppy_image(task, parameters)
        attach_vmedia(task.node, 'FLOPPY', floppy_image_temp_url)

    boot_iso_url = None
    parsed_ref = urlparse.urlparse(boot_iso)
    if parsed_ref.scheme == 'swift':
        swift_api = swift.SwiftAPI()
        container = CONF.ilo.swift_ilo_container
        object_name = parsed_ref.path
        timeout = CONF.ilo.swift_object_expiry_timeout
        boot_iso_url = swift_api.get_temp_url(
            container, object_name, timeout)
    elif service_utils.is_glance_image(boot_iso):
        boot_iso_url = (
            images.get_temp_url_for_glance_image(task.context, boot_iso))
    attach_vmedia(task.node, 'CDROM', boot_iso_url or boot_iso)


def eject_vmedia_devices(task):
    """Ejects virtual media devices.

    This method ejects virtual media floppy and cdrom.

    :param task: a TaskManager instance containing the node to act on.
    :returns: None
    :raises: IloOperationError, if some error was encountered while
        trying to eject virtual media floppy or cdrom.
    """
    ilo_object = get_ilo_object(task.node)
    for device in ('FLOPPY', 'CDROM'):
        try:
            ilo_object.eject_virtual_media(device)
        except ilo_error.IloError as ilo_exception:
            LOG.error("Error while ejecting virtual media %(device)s "
                      "from node %(uuid)s. Error: %(error)s",
                      {'device': device, 'uuid': task.node.uuid,
                       'error': ilo_exception})
            operation = _("Eject virtual media %s") % device.lower()
            raise exception.IloOperationError(operation=operation,
                                              error=ilo_exception)


def cleanup_vmedia_boot(task):
    """Cleans a node after a virtual media boot.

    This method cleans up a node after a virtual media boot. It deletes the
    floppy image if it exists in CONF.ilo.swift_ilo_container or web server.
    It also ejects both virtual media cdrom and virtual media floppy.

    :param task: a TaskManager instance containing the node to act on.
    """
    LOG.debug("Cleaning up node %s after virtual media boot", task.node.uuid)

    if not CONF.ilo.use_web_server_for_images:
        object_name = _get_floppy_image_name(task.node)
        remove_image_from_swift(object_name, 'virtual floppy')
    else:
        destroy_floppy_image_from_web_server(task.node)
    eject_vmedia_devices(task)


def get_secure_boot_mode(task):
    """Retrieves current enabled state of UEFI secure boot on the node

    Returns the current enabled state of UEFI secure boot on the node.

    :param task: a task from TaskManager.
    :raises: MissingParameterValue if a required iLO parameter is missing.
    :raises: IloOperationError on an error from IloClient library.
    :raises: IloOperationNotSupported if UEFI secure boot is not supported.
    :returns: Boolean value indicating current state of UEFI secure boot
              on the node.
    """

    operation = _("Get secure boot mode for node %s.") % task.node.uuid
    secure_boot_state = False
    ilo_object = get_ilo_object(task.node)

    try:
        current_boot_mode = ilo_object.get_current_boot_mode()
        if current_boot_mode == 'UEFI':
            secure_boot_state = ilo_object.get_secure_boot_mode()

    except ilo_error.IloCommandNotSupportedError as ilo_exception:
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=ilo_exception)
    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)

    LOG.debug("Get secure boot mode for node %(node)s returned %(value)s",
              {'value': secure_boot_state, 'node': task.node.uuid})
    return secure_boot_state


def set_secure_boot_mode(task, flag):
    """Enable or disable UEFI Secure Boot for the next boot

    Enable or disable UEFI Secure Boot for the next boot

    :param task: a task from TaskManager.
    :param flag: Boolean value. True if the secure boot to be
                       enabled in next boot.
    :raises: IloOperationError on an error from IloClient library.
    :raises: IloOperationNotSupported if UEFI secure boot is not supported.
    """

    operation = (_("Setting secure boot to %(flag)s for node %(node)s.") %
                 {'flag': flag, 'node': task.node.uuid})
    ilo_object = get_ilo_object(task.node)

    try:
        ilo_object.set_secure_boot_mode(flag)
        LOG.debug(operation)

    except ilo_error.IloCommandNotSupportedError as ilo_exception:
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=ilo_exception)

    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)


def remove_single_or_list_of_files(file_location):
    """Removes (deletes) the file or list of files.

    This method only accepts single or list of files to delete.
    If single file is passed, this method removes (deletes) the file.
    If list of files is passed, this method removes (deletes) each of the
    files iteratively.

    :param file_location: a single or a list of file paths
    """
    # file_location is a list of files
    if isinstance(file_location, list):
        for location in file_location:
            ironic_utils.unlink_without_raise(location)
    # file_location is a single file path
    elif isinstance(file_location, str):
        ironic_utils.unlink_without_raise(file_location)


def verify_image_checksum(image_location, expected_checksum):
    """Verifies checksum (md5) of image file against the expected one.

    This method generates the checksum of the image file on the fly and
    verifies it against the expected checksum provided as argument.

    :param image_location: location of image file whose checksum is verified.
    :param expected_checksum: checksum to be checked against
    :raises: ImageRefValidationFailed, if invalid file path or
             verification fails.
    """
    try:
        actual_checksum = fileutils.compute_file_checksum(image_location,
                                                          algorithm='md5')
    except IOError as e:
        LOG.error("Error opening file: %(file)s", {'file': image_location})
        raise exception.ImageRefValidationFailed(image_href=image_location,
                                                 reason=e)

    if actual_checksum != expected_checksum:
        msg = (_('Error verifying image checksum. Image %(image)s failed to '
                 'verify against checksum %(checksum)s. Actual checksum is: '
                 '%(actual_checksum)s') %
               {'image': image_location, 'checksum': expected_checksum,
                'actual_checksum': actual_checksum})
        LOG.error(msg)
        raise exception.ImageRefValidationFailed(image_href=image_location,
                                                 reason=msg)


def get_server_post_state(node):
    """Get the current state of system POST.

    :param node: an ironic node object.
    :returns: POST state of the server. The valida states are:-
        null, Unknown, Reset, PowerOff, InPost, InPostDiscoveryComplete
        and FinishedPost.
    :raises: IloOperationError on an error from IloClient library.
    :raises: IloOperationNotSupported if retrieving post state is not
        supported on the server.
    """
    ilo_object = get_ilo_object(node)
    operation = _("Get server post state for node %s.") % node.uuid
    try:
        return ilo_object.get_host_post_state()
    except ilo_error.IloCommandNotSupportedError as ilo_exception:
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=ilo_exception)
    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)


def _get_certificate_file_list(cert_file_list):
    """Get the list of certificates to use.

    :param cert_file_list: certificates file list.
    :returns: cert_file_list if it's not empty. If empty or None,
        returns the list of path configured for "webserver_verify_ca"
        configuration option if the path exists. If the path does not
        exist, returns empty list.
    :raises: InvalidParameterValue if argument provided is other than
        a list.
    """

    cfl = cert_file_list

    if not cfl:
        try:
            verify = strutils.bool_from_string(CONF.webserver_verify_ca,
                                               strict=True)
        except ValueError:
            verify = CONF.webserver_verify_ca

        if isinstance(verify, bool):
            return []

        if not os.path.exists(verify):
            LOG.error("Path to the certificate file %(path)s "
                      "does not exist.", {'path': verify})
            return []

        cfl = [verify]

    if not isinstance(cfl, list):
        raise exception.InvalidParameterValue(_(
            'List of files is expected whereas "%(atype)s" type '
            'is provided.') % {'atype': type(cfl)})

    return cfl


def add_certificates(task, cert_file_list=None):
    """Adds certificates to the node.

    Adds certificates to the node based on the driver info
    provided.

    :param task: a TaskManager instance containing the node to act on.
    :param cert_file_list: List of certificates to be added to the node.
        If None, certificates from path configured in 'webserver_verify_ca'
        will be added to the node.
    :raises: IloOperationError on an error from IloClient library.
    :raises: IloOperationNotSupported if retrieving post state is not
        supported on the server.
    :raises: InvalidParameterValue, if any of the required parameters are
            invalid.
    """

    node = task.node
    ilo_object = get_ilo_object(node)
    d_info = node.driver_info

    export_certs = d_info.get('ilo_add_certificates', True)

    if export_certs is None:
        export_certs = True
    else:
        try:
            export_certs = strutils.bool_from_string(export_certs,
                                                     strict=True)
        except ValueError:
            raise exception.InvalidParameterValue(
                _('Invalid value type set in driver_info/'
                  'ilo_add_certificates on node %(node)s. '
                  'The value should be a Boolean '
                  ' not "%(value)s"'
                  ) % {'value': export_certs, 'node': node.uuid})

    if not export_certs:
        LOG.info("Adding of certificates to the node %(node)s is not "
                 "requested. Assuming required certificates are available "
                 "on the node.", {'node': node.uuid})
        return

    cfl = _get_certificate_file_list(cert_file_list)

    if not cfl:
        LOG.debug("Not adding any certificate to the node %(node)s "
                  "as no certificates are provided", {'node': node.uuid})
        return

    try:
        # NOTE(vmud213): Add the certificates to the node which are
        # eventually being used for TLS verification by the node before
        # downloading the deploy/instance images during HTTPS boot from
        # URL.
        operation = (_("Add certificates to %(node)s from paths "
                       "%(cpath)s.") % {'cpath': cfl, 'node': node.uuid})

        ilo_object.add_tls_certificate(cfl)

        LOG.info("Successfully added certificates to the node %(node)s from "
                 "paths %(cpath)s.", {'cpath': cfl, 'node': node.uuid})
    except ilo_error.IloCommandNotSupportedInBiosError as ilo_exception:
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=ilo_exception)
    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)


def clear_certificates(task, cert_file_list=None):
    """Clears any certificates added to the node.

    Clears the certificates added to the node as part of any Ironic
    operation

    :param task: a TaskManager instance containing the node to act on.
    :param cert_file_list: List of certificates to be removed from node.
        If None, all the certificates present on the node will be removed.
    :raises: IloOperationError on an error from IloClient library.
    :raises: IloOperationNotSupported if retrieving post state is not
        supported on the server.
    """

    node = task.node
    operation = (_("Clearing certificates from node %(node)s.") %
                 {'node': node.uuid})
    # NOTE(vmud213): Exclude the certificates used to boot deploy images
    exclude_cfl = _get_certificate_file_list(None)

    try:
        ilo_object = get_ilo_object(node)
        ilo_object.remove_tls_certificate(
            cert_file_list=cert_file_list, excl_cert_file_list=exclude_cfl)
    except ilo_error.IloCommandNotSupportedInBiosError as ilo_exception:
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=ilo_exception)
    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)
    LOG.info("Cleared TLS certificates from the node %(node)s "
             "successfully from paths %(cpath)s.",
             {'node': node.uuid, 'cpath': cert_file_list})


def setup_uefi_https(task, iso, persistent=False):
    """Sets up system to boot from UEFIHTTP boot device.

    Sets the one-time/persistent boot device to UEFIHTTP based
    on the argument supplied.

    :param task: a TaskManager instance containing the node to act on.
    :param iso: ISO URL to be set to boot from.
    :param persistent: Indicates whether the system should be set to boot
        from the given device one-time or each time.
    :raises: IloOperationError on an error from IloClient library.
    :raises: IloOperationNotSupported if retrieving post state is not
        supported on the server.
    """
    node = task.node
    ilo_object = get_ilo_object(node)
    scheme = urlparse.urlparse(iso).scheme.lower()

    operation = (_("Setting up node %(node)s to boot from URL %(iso)s.") %
                 {'iso': iso, 'node': node.uuid})

    if scheme != 'https':
        msg = (_('Error setting up node %(node)s to boot from '
                 'URL %(iso)s. A secure URL is expected that is exposed '
                 'over HTTPS.') %
               {'node': node.uuid, 'iso': iso})
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=msg)

    try:
        ilo_object.set_http_boot_url(iso)
        LOG.info("Set the node %(node)s to boot from URL %(iso)s "
                 "successfully.", {'node': node.uuid, 'iso': iso})
        if not persistent:
            ilo_object.set_one_time_boot('UEFIHTTP')
        else:
            ilo_object.update_persistent_boot(['UEFIHTTP'])

    except ilo_error.IloCommandNotSupportedInBiosError as ilo_exception:
        raise exception.IloOperationNotSupported(operation=operation,
                                                 error=ilo_exception)
    except ilo_error.IloError as ilo_exception:
        raise exception.IloOperationError(operation=operation,
                                          error=ilo_exception)
