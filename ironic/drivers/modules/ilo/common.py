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

import tempfile

from oslo.config import cfg
from oslo.utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common import images
from ironic.common import swift
from ironic.common import utils
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import log as logging

ilo_client = importutils.try_import('proliantutils.ilo.ribcl')

STANDARD_LICENSE = 1
ESSENTIALS_LICENSE = 2
ADVANCED_LICENSE = 3

opts = [
    cfg.IntOpt('client_timeout',
               default=60,
               help='Timeout (in seconds) for iLO operations'),
    cfg.IntOpt('client_port',
               default=443,
               help='Port to be used for iLO operations'),
    cfg.StrOpt('swift_ilo_container',
               default='ironic_ilo_container',
               help='The Swift iLO container to store data.'),
    cfg.IntOpt('swift_object_expiry_timeout',
               default=900,
               help='Amount of time in seconds for Swift objects to '
                    'auto-expire.'),
]

CONF = cfg.CONF
CONF.register_opts(opts, group='ilo')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'ilo_address': _("IP address or hostname of the iLO. Required."),
    'ilo_username': _("username for the iLO with administrator privileges. "
                      "Required."),
    'ilo_password': _("password for ilo_username. Required.")
}
OPTIONAL_PROPERTIES = {
    'client_port': _("port to be used for iLO operations. Optional."),
    'client_timeout': _("timeout (in seconds) for iLO operations. Optional.")
}
CONSOLE_PROPERTIES = {
    'console_port': _("node's UDP port to connect to. Only required for "
                      "console access.")
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
DEFAULT_BOOT_MODE = 'LEGACY'

BOOT_MODE_GENERIC_TO_ILO = {'bios': 'legacy', 'uefi': 'uefi'}
BOOT_MODE_ILO_TO_GENERIC = dict((v, k)
                           for (k, v) in BOOT_MODE_GENERIC_TO_ILO.items())


def parse_driver_info(node):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver.

    :param node: an ironic node object.
    :returns: a dict containing information from driver_info
        and default values.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    info = node.driver_info
    d_info = {}

    error_msgs = []
    for param in REQUIRED_PROPERTIES:
        try:
            d_info[param] = info[param]
        except KeyError:
            error_msgs.append(_("'%s' not supplied to IloDriver.") % param)
    if error_msgs:
        msg = (_("The following parameters were mising while parsing "
                 "driver_info:\n%s") % "\n".join(error_msgs))
        raise exception.MissingParameterValue(msg)

    for param in OPTIONAL_PROPERTIES:
        value = info.get(param, CONF.ilo.get(param))
        try:
            value = int(value)
        except ValueError:
            error_msgs.append(_("'%s' is not an integer.") % param)
            continue
        d_info[param] = value

    for param in CONSOLE_PROPERTIES:
        value = info.get(param)
        if value:
            try:
                value = int(value)
                d_info[param] = value
            except ValueError:
                error_msgs.append(_("'%s' is not an integer.") % param)

    if error_msgs:
        msg = (_("The following errors were encountered while parsing "
                 "driver_info:\n%s") % "\n".join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    return d_info


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
    ilo_object = ilo_client.IloClient(driver_info['ilo_address'],
                                      driver_info['ilo_username'],
                                      driver_info['ilo_password'],
                                      driver_info['client_timeout'],
                                      driver_info['client_port'])
    return ilo_object


def get_ilo_license(node):
    """Gives the current installed license on the node.

    Given an ironic node object, this method queries the iLO
    for currently installed license and returns it back.

    :param node: an ironic node object.
    :returns: a constant defined in this module which
        refers to the current license installed on the node.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    :raises: IloOperationError if it failed to retrieve the
        installed licenses from the iLO.
    """
    # Get the ilo client object, and then the license from the iLO
    ilo_object = get_ilo_object(node)
    try:
        license_info = ilo_object.get_all_licenses()
    except ilo_client.IloError as ilo_exception:
        raise exception.IloOperationError(operation=_('iLO license check'),
                                          error=str(ilo_exception))

    # Check the license to see if the given license exists
    current_license_type = license_info['LICENSE_TYPE']

    if current_license_type.endswith("Advanced"):
        return ADVANCED_LICENSE
    elif current_license_type.endswith("Essentials"):
        return ESSENTIALS_LICENSE
    else:
        return STANDARD_LICENSE


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
    two files into the image - one containing the authentication token and
    the other containing the parameters to be passed to the ramdisk. Then it
    uploads the file to Swift in 'swift_ilo_container', setting it to
    auto-expire after 'swift_object_expiry_timeout' seconds. Then it returns
    the temp url for the Swift object.

    :param task: a TaskManager instance containing the node to act on.
    :param params: a dictionary containing 'parameter name'->'value' mapping
        to be passed to the deploy ramdisk via the floppy image.
    :returns: the Swift temp url for the floppy image.
    """
    with tempfile.NamedTemporaryFile() as vfat_image_tmpfile_obj:

        files_info = {}
        token_tmpfile_obj = None
        vfat_image_tmpfile = vfat_image_tmpfile_obj.name

        # If auth_strategy is noauth, then no need to write token into
        # the image file.
        if task.context.auth_token:
            token_tmpfile_obj = tempfile.NamedTemporaryFile()
            token_tmpfile = token_tmpfile_obj.name
            utils.write_to_file(token_tmpfile, task.context.auth_token)
            files_info[token_tmpfile] = 'token'

        try:
            images.create_vfat_image(vfat_image_tmpfile, files_info=files_info,
                                     parameters=params)
        finally:
            if token_tmpfile_obj:
                token_tmpfile_obj.close()

        container = CONF.ilo.swift_ilo_container
        object_name = _get_floppy_image_name(task.node)
        timeout = CONF.ilo.swift_object_expiry_timeout

        object_headers = {'X-Delete-After': timeout}
        swift_api = swift.SwiftAPI()
        swift_api.create_object(container, object_name,
                                vfat_image_tmpfile,
                                object_headers=object_headers)
        temp_url = swift_api.get_temp_url(container, object_name, timeout)

        LOG.debug("Uploaded floppy image %(object_name)s to %(container)s "
                  "for deployment.",
                  {'object_name': object_name, 'container': container})
        return temp_url


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
        ilo_object.set_vm_status(device=device, boot_option='CONNECT',
                write_protect='YES')
    except ilo_client.IloError as ilo_exception:
        operation = _("Inserting virtual media %s") % device
        raise exception.IloOperationError(operation=operation,
                error=ilo_exception)

    LOG.info(_LI("Attached virtual media %s successfully."), device)


def set_boot_mode(node, boot_mode):
    """Sets the node to boot using boot_mode for the next boot.

    :param node: an ironic node object.
    :param boot_mode: Next boot mode.
    :raises: IloOperationError if setting boot mode failed.
    """
    ilo_object = get_ilo_object(node)

    try:
        p_boot_mode = ilo_object.get_pending_boot_mode()
    except ilo_client.IloCommandNotSupportedError:
        p_boot_mode = DEFAULT_BOOT_MODE

    if BOOT_MODE_ILO_TO_GENERIC[p_boot_mode.lower()] == boot_mode:
        LOG.info(_LI("Node %(uuid)s pending boot mode is %(boot_mode)s."),
                 {'uuid': node.uuid, 'boot_mode': boot_mode})
        return

    try:
        ilo_object.set_pending_boot_mode(
                        BOOT_MODE_GENERIC_TO_ILO[boot_mode].upper())
    except ilo_client.IloError as ilo_exception:
        operation = _("Setting %s as boot mode") % boot_mode
        raise exception.IloOperationError(operation=operation,
                error=ilo_exception)

    LOG.info(_LI("Node %(uuid)s boot mode is set to %(boot_mode)s."),
             {'uuid': node.uuid, 'boot_mode': boot_mode})


def update_boot_mode_capability(task):
    """Update 'boot_mode' capability value of node's 'capabilities' property.

    :param task: Task object.

    """
    ilo_object = get_ilo_object(task.node)

    try:
        p_boot_mode = ilo_object.get_pending_boot_mode()
        if p_boot_mode == 'UNKNOWN':
            # NOTE(faizan) ILO will return this in remote cases and mostly on
            # the nodes which supports UEFI. Such nodes mostly comes with UEFI
            # as default boot mode. So we will try setting bootmode to UEFI
            # and if it fails then we fall back to BIOS boot mode.
            ilo_object.set_pending_boot_mode('UEFI')
            p_boot_mode = 'UEFI'
    except ilo_client.IloCommandNotSupportedError:
        p_boot_mode = DEFAULT_BOOT_MODE

    driver_utils.rm_node_capability(task, 'boot_mode')

    driver_utils.add_node_capability(task, 'boot_mode',
        BOOT_MODE_ILO_TO_GENERIC[p_boot_mode.lower()])


def setup_vmedia_for_boot(task, boot_iso, parameters=None):
    """Sets up the node to boot from the given ISO image.

    This method attaches the given boot_iso on the node and passes
    the required parameters to it via virtual floppy image.

    :param task: a TaskManager instance containing the node to act on.
    :param boot_iso: a bootable ISO image to attach to.  The boot iso
        should be present in either Glance or in Swift. If present in
        Glance, it should be of format 'glance:<glance-image-uuid>'.
        If present in Swift, it should be of format 'swift:<object-name>'.
        It is assumed that object is present in CONF.ilo.swift_ilo_container.
    :param parameters: the parameters to pass in the virtual floppy image
        in a dictionary.  This is optional.
    :raises: ImageCreationFailed, if it failed while creating the floppy image.
    :raises: IloOperationError, if attaching virtual media failed.
    """
    LOG.info(_LI("Setting up node %s to boot from virtual media"),
             task.node.uuid)

    if parameters:
        floppy_image_temp_url = _prepare_floppy_image(task, parameters)
        attach_vmedia(task.node, 'FLOPPY', floppy_image_temp_url)

    boot_iso_temp_url = None
    scheme, boot_iso_ref = boot_iso.split(':')
    if scheme == 'swift':
        swift_api = swift.SwiftAPI()
        container = CONF.ilo.swift_ilo_container
        object_name = boot_iso_ref
        timeout = CONF.ilo.swift_object_expiry_timeout
        boot_iso_temp_url = swift_api.get_temp_url(container, object_name,
                timeout)
    elif scheme == 'glance':
        glance_uuid = boot_iso_ref
        boot_iso_temp_url = images.get_temp_url_for_glance_image(task.context,
                glance_uuid)

    attach_vmedia(task.node, 'CDROM', boot_iso_temp_url)


def cleanup_vmedia_boot(task):
    """Cleans a node after a virtual media boot.

    This method cleans up a node after a virtual media boot. It deletes the
    floppy image if it exists in CONF.ilo.swift_ilo_container. It also
    ejects both virtual media cdrom and virtual media floppy.

    :param task: a TaskManager instance containing the node to act on.
    """
    LOG.debug("Cleaning up node %s after virtual media boot", task.node.uuid)

    container = CONF.ilo.swift_ilo_container
    object_name = _get_floppy_image_name(task.node)
    try:
        swift_api = swift.SwiftAPI()
        swift_api.delete_object(container, object_name)
    except exception.SwiftOperationError as e:
        LOG.exception(_LE("Error while deleting %(object_name)s from "
                          "%(container)s. Error: %(error)s"),
                      {'object_name': object_name, 'container': container,
                       'error': e})

    ilo_object = get_ilo_object(task.node)
    for device in ('FLOPPY', 'CDROM'):
        try:
            ilo_object.eject_virtual_media(device)
        except ilo_client.IloError as ilo_exception:
            LOG.exception(_LE("Error while ejecting virtual media %(device)s "
                              "from node %(uuid)s. Error: %(error)s"),
                          {'device': device, 'uuid': task.node.uuid,
                           'error': ilo_exception})
