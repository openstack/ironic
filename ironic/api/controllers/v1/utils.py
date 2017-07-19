# Copyright 2013 Red Hat, Inc.
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

import inspect

import jsonpatch
from oslo_config import cfg
from oslo_utils import uuidutils
import pecan
from pecan import rest
import six
from six.moves import http_client
from webob import static
import wsme

from ironic.api.controllers.v1 import versions
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic import objects


CONF = cfg.CONF


JSONPATCH_EXCEPTIONS = (jsonpatch.JsonPatchException,
                        jsonpatch.JsonPointerException,
                        KeyError)


# Minimum API version to use for certain verbs
MIN_VERB_VERSIONS = {
    # v1.4 added the MANAGEABLE state and two verbs to move nodes into
    # and out of that state. Reject requests to do this in older versions
    states.VERBS['manage']: versions.MINOR_4_MANAGEABLE_STATE,
    states.VERBS['provide']: versions.MINOR_4_MANAGEABLE_STATE,

    states.VERBS['inspect']: versions.MINOR_6_INSPECT_STATE,
    states.VERBS['abort']: versions.MINOR_13_ABORT_VERB,
    states.VERBS['clean']: versions.MINOR_15_MANUAL_CLEAN,
    states.VERBS['adopt']: versions.MINOR_17_ADOPT_VERB,
}

V31_FIELDS = [
    'boot_interface',
    'console_interface',
    'deploy_interface',
    'inspect_interface',
    'management_interface',
    'power_interface',
    'raid_interface',
    'vendor_interface',
]


def validate_limit(limit):
    if limit is None:
        return CONF.api.max_limit

    if limit <= 0:
        raise wsme.exc.ClientSideError(_("Limit must be positive"))

    return min(CONF.api.max_limit, limit)


def validate_sort_dir(sort_dir):
    if sort_dir not in ['asc', 'desc']:
        raise wsme.exc.ClientSideError(_("Invalid sort direction: %s. "
                                         "Acceptable values are "
                                         "'asc' or 'desc'") % sort_dir)
    return sort_dir


def apply_jsonpatch(doc, patch):
    for p in patch:
        if p['op'] == 'add' and p['path'].count('/') == 1:
            if p['path'].lstrip('/') not in doc:
                msg = _('Adding a new attribute (%s) to the root of '
                        'the resource is not allowed')
                raise wsme.exc.ClientSideError(msg % p['path'])
    return jsonpatch.apply_patch(doc, jsonpatch.JsonPatch(patch))


def get_patch_values(patch, path):
    """Get the patch values corresponding to the specified path.

    If there are multiple values specified for the same path
    (for example the patch is [{'op': 'add', 'path': '/name', 'value': 'abc'},
                               {'op': 'add', 'path': '/name', 'value': 'bca'}])
    return all of them in a list (preserving order).

    :param patch: HTTP PATCH request body.
    :param path: the path to get the patch values for.
    :returns: list of values for the specified path in the patch.
    """
    return [p['value'] for p in patch
            if p['path'] == path and p['op'] != 'remove']


def is_path_removed(patch, path):
    """Returns whether the patch includes removal of the path (or subpath of).

    :param patch: HTTP PATCH request body.
    :param path: the path to check.
    :returns: True if path or subpath being removed, False otherwise.
    """
    path = path.rstrip('/')
    for p in patch:
        if ((p['path'] == path or p['path'].startswith(path + '/')) and
                p['op'] == 'remove'):
            return True


def is_path_updated(patch, path):
    """Returns whether the patch includes operation on path (or its subpath).

    :param patch: HTTP PATCH request body.
    :param path: the path to check.
    :returns: True if path or subpath being patched, False otherwise.
    """
    path = path.rstrip('/')
    for p in patch:
        return p['path'] == path or p['path'].startswith(path + '/')


def allow_node_logical_names():
    # v1.5 added logical name aliases
    return pecan.request.version.minor >= versions.MINOR_5_NODE_NAME


def get_rpc_node(node_ident):
    """Get the RPC node from the node uuid or logical name.

    :param node_ident: the UUID or logical name of a node.

    :returns: The RPC Node.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: NodeNotFound if the node is not found.
    """
    # Check to see if the node_ident is a valid UUID.  If it is, treat it
    # as a UUID.
    if uuidutils.is_uuid_like(node_ident):
        return objects.Node.get_by_uuid(pecan.request.context, node_ident)

    # We can refer to nodes by their name, if the client supports it
    if allow_node_logical_names():
        if is_valid_logical_name(node_ident):
            return objects.Node.get_by_name(pecan.request.context, node_ident)
        raise exception.InvalidUuidOrName(name=node_ident)

    # Ensure we raise the same exception as we did for the Juno release
    raise exception.NodeNotFound(node=node_ident)


def get_rpc_portgroup(portgroup_ident):
    """Get the RPC portgroup from the portgroup UUID or logical name.

    :param portgroup_ident: the UUID or logical name of a portgroup.

    :returns: The RPC portgroup.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: PortgroupNotFound if the portgroup is not found.
    """
    # Check to see if the portgroup_ident is a valid UUID.  If it is, treat it
    # as a UUID.
    if uuidutils.is_uuid_like(portgroup_ident):
        return objects.Portgroup.get_by_uuid(pecan.request.context,
                                             portgroup_ident)

    # We can refer to portgroups by their name
    if utils.is_valid_logical_name(portgroup_ident):
        return objects.Portgroup.get_by_name(pecan.request.context,
                                             portgroup_ident)
    raise exception.InvalidUuidOrName(name=portgroup_ident)


def is_valid_node_name(name):
    """Determine if the provided name is a valid node name.

    Check to see that the provided node name is valid, and isn't a UUID.

    :param: name: the node name to check.
    :returns: True if the name is valid, False otherwise.
    """
    return is_valid_logical_name(name) and not uuidutils.is_uuid_like(name)


def is_valid_logical_name(name):
    """Determine if the provided name is a valid hostname."""
    if pecan.request.version.minor < versions.MINOR_10_UNRESTRICTED_NODE_NAME:
        return utils.is_hostname_safe(name)
    else:
        return utils.is_valid_logical_name(name)


def vendor_passthru(ident, method, topic, data=None, driver_passthru=False):
    """Call a vendor passthru API extension.

    Call the vendor passthru API extension and process the method response
    to set the right return code for methods that are asynchronous or
    synchronous; Attach the return value to the response object if it's
    being served statically.

    :param ident: The resource identification. For node's vendor passthru
        this is the node's UUID, for driver's vendor passthru this is the
        driver's name.
    :param method: The vendor method name.
    :param topic: The RPC topic.
    :param data: The data passed to the vendor method. Defaults to None.
    :param driver_passthru: Boolean value. Whether this is a node or
        driver vendor passthru. Defaults to False.
    :returns: A WSME response object to be returned by the API.

    """
    if not method:
        raise wsme.exc.ClientSideError(_("Method not specified"))

    if data is None:
        data = {}

    http_method = pecan.request.method.upper()
    params = (pecan.request.context, ident, method, http_method, data, topic)
    if driver_passthru:
        response = pecan.request.rpcapi.driver_vendor_passthru(*params)
    else:
        response = pecan.request.rpcapi.vendor_passthru(*params)

    status_code = http_client.ACCEPTED if response['async'] else http_client.OK
    return_value = response['return']
    response_params = {'status_code': status_code}

    # Attach the return value to the response object
    if response.get('attach'):
        if isinstance(return_value, six.text_type):
            # If unicode, convert to bytes
            return_value = return_value.encode('utf-8')
        file_ = wsme.types.File(content=return_value)
        pecan.response.app_iter = static.FileIter(file_.file)
        # Since we've attached the return value to the response
        # object the response body should now be empty.
        return_value = None
        response_params['return_type'] = None

    return wsme.api.Response(return_value, **response_params)


def check_for_invalid_fields(fields, object_fields):
    """Check for requested non-existent fields.

    Check if the user requested non-existent fields.

    :param fields: A list of fields requested by the user
    :object_fields: A list of fields supported by the object.
    :raises: InvalidParameterValue if invalid fields were requested.

    """
    invalid_fields = set(fields) - set(object_fields)
    if invalid_fields:
        raise exception.InvalidParameterValue(
            _('Field(s) "%s" are not valid') % ', '.join(invalid_fields))


def check_allow_specify_fields(fields):
    """Check if fetching a subset of the resource attributes is allowed.

    Version 1.8 of the API allows fetching a subset of the resource
    attributes, this method checks if the required version is being
    requested.
    """
    if (fields is not None and pecan.request.version.minor <
            versions.MINOR_8_FETCHING_SUBSET_OF_FIELDS):
        raise exception.NotAcceptable()


def check_allowed_fields(fields):
    """Check if fetching a particular field is allowed.

    This method checks if the required version is being requested for fields
    that are only allowed to be fetched in a particular API version.
    """
    if fields is None:
        return
    if 'network_interface' in fields and not allow_network_interface():
        raise exception.NotAcceptable()
    if 'resource_class' in fields and not allow_resource_class():
        raise exception.NotAcceptable()
    if not allow_dynamic_interfaces():
        if set(V31_FIELDS).intersection(set(fields)):
            raise exception.NotAcceptable()
    if 'storage_interface' in fields and not allow_storage_interface():
        raise exception.NotAcceptable()


def check_allowed_portgroup_fields(fields):
    """Check if fetching a particular field of a portgroup is allowed.

    This method checks if the required version is being requested for fields
    that are only allowed to be fetched in a particular API version.
    """
    if fields is None:
        return
    if (('mode' in fields or 'properties' in fields) and
            not allow_portgroup_mode_properties()):
        raise exception.NotAcceptable()


def check_allow_management_verbs(verb):
    min_version = MIN_VERB_VERSIONS.get(verb)
    if min_version is not None and pecan.request.version.minor < min_version:
        raise exception.NotAcceptable()


def check_for_invalid_state_and_allow_filter(provision_state):
    """Check if filtering nodes by provision state is allowed.

    Version 1.9 of the API allows filter nodes by provision state.
    """
    if provision_state is not None:
        if (pecan.request.version.minor <
                versions.MINOR_9_PROVISION_STATE_FILTER):
            raise exception.NotAcceptable()
        valid_states = states.machine.states
        if provision_state not in valid_states:
            raise exception.InvalidParameterValue(
                _('Provision state "%s" is not valid') % provision_state)


def check_allow_specify_driver(driver):
    """Check if filtering nodes by driver is allowed.

    Version 1.16 of the API allows filter nodes by driver.
    """
    if (driver is not None and pecan.request.version.minor <
            versions.MINOR_16_DRIVER_FILTER):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_16_DRIVER_FILTER})


def check_allow_specify_resource_class(resource_class):
    """Check if filtering nodes by resource_class is allowed.

    Version 1.21 of the API allows filtering nodes by resource_class.
    """
    if (resource_class is not None and pecan.request.version.minor <
            versions.MINOR_21_RESOURCE_CLASS):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_21_RESOURCE_CLASS})


def check_allow_filter_driver_type(driver_type):
    """Check if filtering drivers by classic/dynamic is allowed.

    Version 1.30 of the API allows this.
    """
    if driver_type is not None and not allow_dynamic_drivers():
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_30_DYNAMIC_DRIVERS})


def check_allow_driver_detail(detail):
    """Check if getting detailed driver info is allowed.

    Version 1.30 of the API allows this.
    """
    if detail is not None and not allow_dynamic_drivers():
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_30_DYNAMIC_DRIVERS})


def initial_node_provision_state():
    """Return node state to use by default when creating new nodes.

    Previously the default state for new nodes was AVAILABLE.
    Starting with API 1.11 it is ENROLL.
    """
    return (states.AVAILABLE
            if pecan.request.version.minor < versions.MINOR_11_ENROLL_STATE
            else states.ENROLL)


def allow_raid_config():
    """Check if RAID configuration is allowed for the node.

    Version 1.12 of the API allows RAID configuration for the node.
    """
    return pecan.request.version.minor >= versions.MINOR_12_RAID_CONFIG


def allow_soft_power_off():
    """Check if Soft Power Off is allowed for the node.

    Version 1.27 of the API allows Soft Power Off, including Soft Reboot, for
    the node.
    """
    return pecan.request.version.minor >= versions.MINOR_27_SOFT_POWER_OFF


def allow_inject_nmi():
    """Check if Inject NMI is allowed for the node.

    Version 1.29 of the API allows Inject NMI for the node.
    """
    return pecan.request.version.minor >= versions.MINOR_29_INJECT_NMI


def allow_links_node_states_and_driver_properties():
    """Check if links are displayable.

    Version 1.14 of the API allows the display of links to node states
    and driver properties.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_14_LINKS_NODESTATES_DRIVERPROPERTIES)


def allow_port_internal_info():
    """Check if accessing internal_info is allowed for the port.

    Version 1.18 of the API exposes internal_info readonly field for the port.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_18_PORT_INTERNAL_INFO)


def allow_port_advanced_net_fields():
    """Check if we should return local_link_connection and pxe_enabled fields.

    Version 1.19 of the API added support for these new fields in port object.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_19_PORT_ADVANCED_NET_FIELDS)


def allow_network_interface():
    """Check if we should support network_interface node field.

    Version 1.20 of the API added support for network interfaces.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_20_NETWORK_INTERFACE)


def allow_resource_class():
    """Check if we should support resource_class node field.

    Version 1.21 of the API added support for resource_class.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_21_RESOURCE_CLASS)


def allow_ramdisk_endpoints():
    """Check if heartbeat and lookup endpoints are allowed.

    Version 1.22 of the API introduced them.
    """
    return pecan.request.version.minor >= versions.MINOR_22_LOOKUP_HEARTBEAT


def allow_portgroups():
    """Check if we should support portgroup operations.

    Version 1.23 of the API added support for PortGroups.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_23_PORTGROUPS)


def allow_portgroups_subcontrollers():
    """Check if portgroups can be used as subcontrollers.

    Version 1.24 of the API added support for Portgroups as
    subcontrollers
    """
    return (pecan.request.version.minor >=
            versions.MINOR_24_PORTGROUPS_SUBCONTROLLERS)


def allow_remove_chassis_uuid():
    """Check if chassis_uuid can be removed from node.

    Version 1.25 of the API added support for chassis_uuid
    removal
    """
    return (pecan.request.version.minor >=
            versions.MINOR_25_UNSET_CHASSIS_UUID)


def allow_portgroup_mode_properties():
    """Check if mode and properties can be added to/queried from a portgroup.

    Version 1.26 of the API added mode and properties fields to portgroup
    object.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_26_PORTGROUP_MODE_PROPERTIES)


def allow_vifs_subcontroller():
    """Check if node/vifs can be used.

    Version 1.28 of the API added support for VIFs to be
    attached to Nodes.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_28_VIFS_SUBCONTROLLER)


def allow_dynamic_drivers():
    """Check if dynamic driver API calls are allowed.

    Version 1.30 of the API added support for all of the driver
    composition related calls in the /v1/drivers API.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_30_DYNAMIC_DRIVERS)


def allow_dynamic_interfaces():
    """Check if dynamic interface fields are allowed.

    Version 1.31 of the API added support for viewing and setting the fields
    in ``V31_FIELDS`` on the node object.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_31_DYNAMIC_INTERFACES)


def allow_volume():
    """Check if volume connectors and targets are allowed.

    Version 1.32 of the API added support for volume connectors and targets
    """
    return pecan.request.version.minor >= versions.MINOR_32_VOLUME


def allow_storage_interface():
    """Check if we should support storage_interface node field.

    Version 1.33 of the API added support for storage interfaces.
    """
    return (pecan.request.version.minor >=
            versions.MINOR_33_STORAGE_INTERFACE)


def allow_port_physical_network():
    """Check if port physical network field is allowed.

    Version 1.34 of the API added the physical network field to the port
    object.  We also check whether the target version of the Port object
    supports the physical_network field as this may not be the case during a
    rolling upgrade.
    """
    return ((pecan.request.version.minor >=
             versions.MINOR_34_PORT_PHYSICAL_NETWORK) and
            objects.Port.supports_physical_network())


def get_controller_reserved_names(cls):
    """Get reserved names for a given controller.

    Inspect the controller class and return the reserved names within
    it. Reserved names are names that can not be used as an identifier
    for a resource because the names are either being used as a custom
    action or is the name of a nested controller inside the given class.

    :param cls: The controller class to be inspected.
    """
    reserved_names = [
        name for name, member in inspect.getmembers(cls)
        if isinstance(member, rest.RestController)]

    if hasattr(cls, '_custom_actions'):
        reserved_names += cls._custom_actions.keys()

    return reserved_names
