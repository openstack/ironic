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

import copy
from http import client as http_client
import inspect
import io
import re
import string

import jsonpatch
import jsonschema
from jsonschema import exceptions as json_schema_exc
import os_traits
from oslo_config import cfg
from oslo_policy import policy as oslo_policy
from oslo_utils import uuidutils
from pecan import rest

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import versions
from ironic.common import args
from ironic.common import exception
from ironic.common import faults
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states
from ironic.common import utils
from ironic.conductor import steps as conductor_steps
from ironic import objects
from ironic.objects import fields as ofields


CONF = cfg.CONF


_JSONPATCH_EXCEPTIONS = (jsonpatch.JsonPatchConflict,
                         jsonpatch.JsonPatchException,
                         jsonpatch.JsonPointerException,
                         KeyError,
                         IndexError)


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
    states.VERBS['rescue']: versions.MINOR_38_RESCUE_INTERFACE,
    states.VERBS['unrescue']: versions.MINOR_38_RESCUE_INTERFACE,
    states.VERBS['deploy']: versions.MINOR_73_DEPLOY_UNDEPLOY_VERBS,
    states.VERBS['undeploy']: versions.MINOR_73_DEPLOY_UNDEPLOY_VERBS,
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

STANDARD_TRAITS = os_traits.get_traits()
CUSTOM_TRAIT_PATTERN = "^%s[A-Z0-9_]+$" % os_traits.CUSTOM_NAMESPACE
CUSTOM_TRAIT_REGEX = re.compile(CUSTOM_TRAIT_PATTERN)

TRAITS_SCHEMA = {
    'type': 'string', 'minLength': 1, 'maxLength': 255,
    'anyOf': [
        {'pattern': CUSTOM_TRAIT_PATTERN},
        {'enum': STANDARD_TRAITS},
    ]
}

LOCAL_LINK_BASE_SCHEMA = {
    'type': 'object',
    'properties': {
        'port_id': {'type': 'string'},
        'switch_id': {'type': 'string'},
        'hostname': {'type': 'string'},
        'switch_info': {'type': 'string'},
        'network_type': {'type': 'string',
                         'enum': ['managed', 'unmanaged']},
    },
    'additionalProperties': False
}

LOCAL_LINK_SCHEMA = copy.deepcopy(LOCAL_LINK_BASE_SCHEMA)
# set mandatory fields for a local link
LOCAL_LINK_SCHEMA['required'] = ['port_id', 'switch_id']

LOCAL_LINK_SMART_NIC_SCHEMA = copy.deepcopy(LOCAL_LINK_BASE_SCHEMA)
# set mandatory fields for a smart nic
LOCAL_LINK_SMART_NIC_SCHEMA['required'] = ['port_id', 'hostname']

# no other mandatory fields for a network_type=unmanaged link
LOCAL_LINK_UNMANAGED_SCHEMA = copy.deepcopy(LOCAL_LINK_BASE_SCHEMA)
LOCAL_LINK_UNMANAGED_SCHEMA['properties']['network_type']['enum'] = [
    'unmanaged']
LOCAL_LINK_UNMANAGED_SCHEMA['required'] = ['network_type']

LOCAL_LINK_CONN_SCHEMA = {'anyOf': [
    LOCAL_LINK_SCHEMA,
    LOCAL_LINK_SMART_NIC_SCHEMA,
    LOCAL_LINK_UNMANAGED_SCHEMA,
    {'type': 'object', 'additionalProperties': False},
]}

DEPLOY_STEP_SCHEMA = {
    'type': 'object',
    'properties': {
        'args': {'type': 'object'},
        'interface': {
            'type': 'string',
            'enum': list(conductor_steps.DEPLOYING_INTERFACE_PRIORITY)
        },
        'priority': {'anyOf': [
            {'type': 'integer', 'minimum': 0},
            {'type': 'string', 'minLength': 1, 'pattern': '^[0-9]+$'}
        ]},
        'step': {'type': 'string', 'minLength': 1},
    },
    'required': ['interface', 'step', 'args', 'priority'],
    'additionalProperties': False,
}


def local_link_normalize(name, value):
    if not value:
        return value

    # Check switch_id is either a valid mac address or
    # OpenFlow datapath_id and normalize it.
    try:
        value['switch_id'] = utils.validate_and_normalize_mac(
            value['switch_id'])
    except exception.InvalidMAC:
        try:
            value['switch_id'] = utils.validate_and_normalize_datapath_id(
                value['switch_id'])
        except exception.InvalidDatapathID:
            raise exception.InvalidSwitchID(switch_id=value['switch_id'])
    except KeyError:
        # In Smart NIC case 'switch_id' is optional.
        pass

    return value


LOCAL_LINK_VALIDATOR = args.and_valid(
    args.schema(LOCAL_LINK_CONN_SCHEMA),
    local_link_normalize
)


LOCAL_LINK_SMART_NIC_VALIDATOR = args.schema(LOCAL_LINK_SMART_NIC_SCHEMA)


def object_to_dict(obj, include_created_at=True, include_updated_at=True,
                   include_uuid=True, link_resource=None,
                   link_resource_args=None, fields=None):
    """Helper function to convert RPC objects to REST API dicts.

    :param obj:
        RPC object to convert to a dict
    :param include_created_at:
        Whether to include standard base class attribute created_at
    :param include_updated_at:
        Whether to include standard base class attribute updated_at
    :param include_uuid:
        Whether to include standard base class attribute uuid
    :param link_resource:
        When specified, generate a ``links`` value with a ``self`` and
        ``bookmark`` using this resource name
    :param link_resource_args:
        Resource arguments to be added to generated links. When not specified,
        the object ``uuid`` will be used.
    :param fields:
        Key names for dict values to populate directly from object attributes
    :returns: A dict containing values from the object
    """
    url = api.request.public_url
    to_dict = {}

    all_fields = []

    if include_uuid:
        all_fields.append('uuid')
    if include_created_at:
        all_fields.append('created_at')
    if include_updated_at:
        all_fields.append('updated_at')

    if fields:
        all_fields.extend(fields)

    for field in all_fields:
        value = to_dict[field] = getattr(obj, field)
        empty_value = None
        if isinstance(obj.fields[field], ofields.ListOfStringsField):
            empty_value = []
        elif isinstance(obj.fields[field], ofields.FlexibleDictField):
            empty_value = {}
        elif isinstance(obj.fields[field], ofields.DateTimeField):
            if value:
                value = value.isoformat()

        if value is not None:
            to_dict[field] = value
        else:
            to_dict[field] = empty_value

    if link_resource:
        if not link_resource_args:
            link_resource_args = obj.uuid
        to_dict['links'] = [
            link.make_link('self', url, link_resource, link_resource_args),
            link.make_link('bookmark', url, link_resource, link_resource_args,
                           bookmark=True)
        ]

    return to_dict


def populate_node_uuid(obj, to_dict):
    """Look up the node referenced in the object and populate a dict.

    The node is fetched with the object ``node_id`` attribute and the
    dict ``node_uuid`` value is populated with the node uuid

    :param obj:
        object to get the node_id attribute
    :param to_dict:
        dict to populate with a ``node_uuid`` value
    :raises:
        exception.NodeNotFound if the node is not found
    """
    if not obj.node_id:
        to_dict['node_uuid'] = None
        return
    to_dict['node_uuid'] = objects.Node.get_by_id(
        api.request.context,
        obj.node_id).uuid


def replace_node_uuid_with_id(to_dict):
    """Replace ``node_uuid`` dict value with ``node_id``

    ``node_id`` is found by fetching the node by uuid lookup.

    :param to_dict: Dict to set ``node_id`` value on
    :returns: The node object from the lookup
    :raises: NodeNotFound with status_code set to 400 BAD_REQUEST
        when node is not found.
    """
    try:
        node = objects.Node.get_by_uuid(api.request.context,
                                        to_dict.pop('node_uuid'))
        to_dict['node_id'] = node.id
        # if they cannot get the node, then this will error
        # helping guard access to all users of this method as
        # users which may have rights at a minimum need to be able
        # to see the node they are trying to do something with.
        check_owner_policy('node', 'baremetal:node:get', node['owner'],
                           node['lessee'], conceal_node=node.uuid)

    except exception.NodeNotFound as e:
        # Change error code because 404 (NotFound) is inappropriate
        # response for requests acting on non-nodes
        e.code = http_client.BAD_REQUEST  # BadRequest
        raise
    return node


def replace_node_id_with_uuid(to_dict):
    """Replace ``node_id`` dict value with ``node_uuid``

    ``node_uuid`` is found by fetching the node by id lookup.

    :param to_dict: Dict to set ``node_uuid`` value on
    :returns: The node object from the lookup
    :raises: NodeNotFound with status_code set to 400 BAD_REQUEST
        when node is not found.
    """
    try:
        node = objects.Node.get_by_id(api.request.context,
                                      to_dict.pop('node_id'))
        to_dict['node_uuid'] = node.uuid
    except exception.NodeNotFound as e:
        # Change error code because 404 (NotFound) is inappropriate
        # response for requests acting on non-nodes
        e.code = http_client.BAD_REQUEST  # BadRequest
        raise
    return node


def patch_update_changed_fields(from_dict, rpc_object, fields,
                                schema, id_map=None):
    """Update rpc object based on changed fields in a dict.

    Only fields which have a corresponding schema field are updated when
    changed. Other values can be updated using the id_map.

    :param from_dict: Dict containing changed field values
    :param rpc_object: Object to update changed fields on
    :param fields: Field names on the rpc object
    :param schema: jsonschema to get field names of the dict
    :param id_map: Optional dict mapping object field names to
        arbitrary values when there is no matching field in the schema
    """
    schema_fields = schema['properties']

    def _patch_val(field, patch_val):
        if field in rpc_object and rpc_object[field] != patch_val:
            rpc_object[field] = patch_val

    for field in fields:
        if id_map and field in id_map:
            _patch_val(field, id_map[field])
        elif field in schema_fields:
            _patch_val(field, from_dict.get(field))


def patched_validate_with_schema(patched_dict, schema, validator=None):
    """Validate a patched dict object against a validator or schema.

    This function has the side-effect of deleting any dict value which
    is not in the schema. This allows database-loaded objects to be pruned
    of their internal values before validation.

    :param patched_dict: dict representation of the object with patch
        updates applied
    :param schema: Any dict key not in the schema will be deleted from the
        dict. If no validator is specified then the resulting ``patched_dict``
        will be validated agains the schema
    :param validator: Optional validator to use if there is extra validation
        required beyond the schema
    :raises: exception.Invalid if validation fails
    """
    schema_fields = schema['properties']
    for field in set(patched_dict):
        if field not in schema_fields:
            patched_dict.pop(field, None)
    if not validator:
        validator = args.schema(schema)
    validator('patch', patched_dict)


def patch_validate_allowed_fields(patch, allowed_fields):
    """Validate that a patch list only modifies allowed fields.

    :param patch: List of patch dicts to validate
    :param allowed_fields: List of fields which are allowed to be patched
    :returns: The list of fields which will be patched
    :raises: exception.Invalid if any patch changes a field not in
        ``allowed_fields``
    """
    fields = set()
    for p in patch:
        path = p['path'].split('/')[1]
        if path not in allowed_fields:
            msg = _("Cannot patch %s. Only the following can be updated: %s")
            raise exception.Invalid(
                msg % (p['path'], ', '.join(allowed_fields)))
        fields.add(path)
    return fields


def sanitize_dict(to_sanitize, fields):
    """Removes sensitive and unrequested data.

    Will only keep the fields specified in the ``fields`` parameter (plus
    the ``links`` field).

    :param to_sanitize: dict to sanitize
    :param fields:
        list of fields to preserve, or ``None`` to preserve them all
    :type fields: list of str
    """
    if fields is None:
        return

    for key in set(to_sanitize):
        if key not in fields and key != 'links':
            to_sanitize.pop(key, None)


def validate_limit(limit):
    if limit is None:
        return CONF.api.max_limit

    if limit <= 0:
        raise exception.ClientSideError(_("Limit must be positive"))

    return min(CONF.api.max_limit, limit)


def validate_sort_dir(sort_dir):
    if sort_dir not in ['asc', 'desc']:
        raise exception.ClientSideError(_("Invalid sort direction: %s. "
                                          "Acceptable values are "
                                          "'asc' or 'desc'") % sort_dir)
    return sort_dir


def apply_jsonpatch(doc, patch):
    """Apply a JSON patch, one operation at a time.

    If the patch fails to apply, this allows us to determine which operation
    failed, making the error message a little less cryptic.

    :param doc: The JSON document to patch.
    :param patch: The JSON patch to apply.
    :returns: The result of the patch operation.
    :raises: PatchError if the patch fails to apply.
    :raises: exception.ClientSideError if the patch adds a new root attribute.
    """
    # Prevent removal of root attributes.
    for p in patch:
        if p['op'] == 'add' and p['path'].count('/') == 1:
            if p['path'].lstrip('/') not in doc:
                msg = _('Adding a new attribute (%s) to the root of '
                        'the resource is not allowed')
                raise exception.ClientSideError(msg % p['path'])

    # Apply operations one at a time, to improve error reporting.
    for patch_op in patch:
        try:
            doc = jsonpatch.apply_patch(doc, jsonpatch.JsonPatch([patch_op]))
        except _JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch_op, reason=e)
    return doc


def get_patch_values(patch, path):
    """Get the patch values corresponding to the specified path.

    If there are multiple values specified for the same path, for example
    ::

        [{'op': 'add', 'path': '/name', 'value': 'abc'},
         {'op': 'add', 'path': '/name', 'value': 'bca'}]

    return all of them in a list (preserving order)

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
        if ((p['path'] == path or p['path'].startswith(path + '/'))
                and p['op'] == 'remove'):
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
    return api.request.version.minor >= versions.MINOR_5_NODE_NAME


def _get_with_suffix(get_func, ident, exc_class):
    """Helper to get a resource taking into account API .json suffix."""
    try:
        return get_func(ident)
    except exc_class:
        if not api.request.environ['HAS_JSON_SUFFIX']:
            raise

        # NOTE(dtantsur): strip .json prefix to maintain compatibility
        # with the guess_content_type_from_ext feature. Try to return it
        # back if the resulting resource was not found.
        return get_func(ident + '.json')


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
        return objects.Node.get_by_uuid(api.request.context, node_ident)
    # We can refer to nodes by their name, if the client supports it
    if allow_node_logical_names():
        if is_valid_logical_name(node_ident):
            return objects.Node.get_by_name(api.request.context, node_ident)
        raise exception.InvalidUuidOrName(name=node_ident)

    # Ensure we raise the same exception as we did for the Juno release
    raise exception.NodeNotFound(node=node_ident)


def get_rpc_node_with_suffix(node_ident):
    """Get the RPC node from the node uuid or logical name.

    If HAS_JSON_SUFFIX flag is set in the pecan environment, try also looking
    for node_ident with '.json' suffix. Otherwise identical to get_rpc_node.

    :param node_ident: the UUID or logical name of a node.

    :returns: The RPC Node.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: NodeNotFound if the node is not found.
    """
    return _get_with_suffix(get_rpc_node, node_ident, exception.NodeNotFound)


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
        return objects.Portgroup.get_by_uuid(api.request.context,
                                             portgroup_ident)

    # We can refer to portgroups by their name
    if utils.is_valid_logical_name(portgroup_ident):
        return objects.Portgroup.get_by_name(api.request.context,
                                             portgroup_ident)
    raise exception.InvalidUuidOrName(name=portgroup_ident)


def get_rpc_portgroup_with_suffix(portgroup_ident):
    """Get the RPC portgroup from the portgroup UUID or logical name.

    If HAS_JSON_SUFFIX flag is set in the pecan environment, try also looking
    for portgroup_ident with '.json' suffix. Otherwise identical
    to get_rpc_portgroup.

    :param portgroup_ident: the UUID or logical name of a portgroup.

    :returns: The RPC portgroup.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: PortgroupNotFound if the portgroup is not found.
    """
    return _get_with_suffix(get_rpc_portgroup, portgroup_ident,
                            exception.PortgroupNotFound)


def get_rpc_allocation(allocation_ident):
    """Get the RPC allocation from the allocation UUID or logical name.

    :param allocation_ident: the UUID or logical name of an allocation.

    :returns: The RPC allocation.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: AllocationNotFound if the allocation is not found.
    """
    # Check to see if the allocation_ident is a valid UUID.  If it is, treat it
    # as a UUID.
    if uuidutils.is_uuid_like(allocation_ident):
        return objects.Allocation.get_by_uuid(api.request.context,
                                              allocation_ident)

    # We can refer to allocations by their name
    if utils.is_valid_logical_name(allocation_ident):
        return objects.Allocation.get_by_name(api.request.context,
                                              allocation_ident)
    raise exception.InvalidUuidOrName(name=allocation_ident)


def get_rpc_allocation_with_suffix(allocation_ident):
    """Get the RPC allocation from the allocation UUID or logical name.

    If HAS_JSON_SUFFIX flag is set in the pecan environment, try also looking
    for allocation_ident with '.json' suffix. Otherwise identical
    to get_rpc_allocation.

    :param allocation_ident: the UUID or logical name of an allocation.

    :returns: The RPC allocation.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: AllocationNotFound if the allocation is not found.
    """
    return _get_with_suffix(get_rpc_allocation, allocation_ident,
                            exception.AllocationNotFound)


def get_rpc_deploy_template(template_ident):
    """Get the RPC deploy template from the UUID or logical name.

    :param template_ident: the UUID or logical name of a deploy template.

    :returns: The RPC deploy template.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: DeployTemplateNotFound if the deploy template is not found.
    """
    # Check to see if the template_ident is a valid UUID.  If it is, treat it
    # as a UUID.
    if uuidutils.is_uuid_like(template_ident):
        return objects.DeployTemplate.get_by_uuid(api.request.context,
                                                  template_ident)

    # We can refer to templates by their name
    if utils.is_valid_logical_name(template_ident):
        return objects.DeployTemplate.get_by_name(api.request.context,
                                                  template_ident)
    raise exception.InvalidUuidOrName(name=template_ident)


def get_rpc_deploy_template_with_suffix(template_ident):
    """Get the RPC deploy template from the UUID or logical name.

    If HAS_JSON_SUFFIX flag is set in the pecan environment, try also looking
    for template_ident with '.json' suffix. Otherwise identical
    to get_rpc_deploy_template.

    :param template_ident: the UUID or logical name of a deploy template.

    :returns: The RPC deploy template.
    :raises: InvalidUuidOrName if the name or uuid provided is not valid.
    :raises: DeployTemplateNotFound if the deploy template is not found.
    """
    return _get_with_suffix(get_rpc_deploy_template, template_ident,
                            exception.DeployTemplateNotFound)


def is_valid_node_name(name):
    """Determine if the provided name is a valid node name.

    Check to see that the provided node name is valid, and isn't a UUID.

    :param name: the node name to check.
    :returns: True if the name is valid, False otherwise.
    """
    return is_valid_logical_name(name) and not uuidutils.is_uuid_like(name)


def is_valid_logical_name(name):
    """Determine if the provided name is a valid hostname."""
    if api.request.version.minor < versions.MINOR_10_UNRESTRICTED_NODE_NAME:
        return utils.is_hostname_safe(name)
    else:
        return utils.is_valid_logical_name(name)


class PassthruResponse(object):
    """Object to hold the "response" from a passthru call"""
    def __init__(self, obj, status_code=None):
        #: Store the result object from the view
        self.obj = obj

        #: Store an optional status_code
        self.status_code = status_code


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
        raise exception.ClientSideError(_("Method not specified"))

    if data is None:
        data = {}

    http_method = api.request.method.upper()
    params = (api.request.context, ident, method, http_method, data, topic)
    if driver_passthru:
        response = api.request.rpcapi.driver_vendor_passthru(*params)
    else:
        response = api.request.rpcapi.vendor_passthru(*params)

    status_code = http_client.ACCEPTED if response['async'] else http_client.OK
    return_value = response['return']

    # Attach the return value to the response object
    if response.get('attach'):
        if isinstance(return_value, str):
            # If unicode, convert to bytes
            return_value = return_value.encode('utf-8')
        return_value = io.BytesIO(return_value)

    return PassthruResponse(return_value, status_code=status_code)


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
    if (fields is not None and api.request.version.minor
            < versions.MINOR_8_FETCHING_SUBSET_OF_FIELDS):
        raise exception.NotAcceptable()


VERSIONED_FIELDS = {
    'driver_internal_info': versions.MINOR_3_DRIVER_INTERNAL_INFO,
    'name': versions.MINOR_5_NODE_NAME,
    'inspection_finished_at': versions.MINOR_6_INSPECT_STATE,
    'inspection_started_at': versions.MINOR_6_INSPECT_STATE,
    'clean_step': versions.MINOR_7_NODE_CLEAN,
    'raid_config': versions.MINOR_12_RAID_CONFIG,
    'target_raid_config': versions.MINOR_12_RAID_CONFIG,
    'network_interface': versions.MINOR_20_NETWORK_INTERFACE,
    'resource_class': versions.MINOR_21_RESOURCE_CLASS,
    'storage_interface': versions.MINOR_33_STORAGE_INTERFACE,
    'traits': versions.MINOR_37_NODE_TRAITS,
    'rescue_interface': versions.MINOR_38_RESCUE_INTERFACE,
    'bios_interface': versions.MINOR_40_BIOS_INTERFACE,
    'fault': versions.MINOR_42_FAULT,
    'deploy_step': versions.MINOR_44_NODE_DEPLOY_STEP,
    'conductor_group': versions.MINOR_46_NODE_CONDUCTOR_GROUP,
    'automated_clean': versions.MINOR_47_NODE_AUTOMATED_CLEAN,
    'protected': versions.MINOR_48_NODE_PROTECTED,
    'protected_reason': versions.MINOR_48_NODE_PROTECTED,
    'conductor': versions.MINOR_49_CONDUCTORS,
    'owner': versions.MINOR_50_NODE_OWNER,
    'description': versions.MINOR_51_NODE_DESCRIPTION,
    'allocation_uuid': versions.MINOR_52_ALLOCATION,
    'events': versions.MINOR_54_EVENTS,
    'retired': versions.MINOR_61_NODE_RETIRED,
    'retired_reason': versions.MINOR_61_NODE_RETIRED,
    'lessee': versions.MINOR_65_NODE_LESSEE,
    'network_data': versions.MINOR_66_NODE_NETWORK_DATA,
    'boot_mode': versions.MINOR_75_NODE_BOOT_MODE,
    'secure_boot': versions.MINOR_75_NODE_BOOT_MODE,
    'shard': versions.MINOR_82_NODE_SHARD,
    'parent_node': versions.MINOR_83_PARENT_CHILD_NODES,
    'firmware_interface': versions.MINOR_86_FIRMWARE_INTERFACE
}

for field in V31_FIELDS:
    VERSIONED_FIELDS[field] = versions.MINOR_31_DYNAMIC_INTERFACES


def allow_field(field):
    """Check if a field is allowed in the current version."""
    return api.request.version.minor >= VERSIONED_FIELDS[field]


def disallowed_fields():
    """Generator of fields not allowed in the current request."""
    for field in VERSIONED_FIELDS:
        if not allow_field(field):
            yield field


def check_allowed_fields(fields):
    """Check if fetching a particular field is allowed.

    This method checks if the required version is being requested for fields
    that are only allowed to be fetched in a particular API version.
    """
    if fields is None:
        return
    for field in disallowed_fields():
        if field in fields:
            raise exception.NotAcceptable()


def check_allowed_portgroup_fields(fields):
    """Check if fetching a particular field of a portgroup is allowed.

    This method checks if the required version is being requested for fields
    that are only allowed to be fetched in a particular API version.
    """
    if fields is None:
        return
    if (('mode' in fields or 'properties' in fields)
            and not allow_portgroup_mode_properties()):
        raise exception.NotAcceptable()


def check_allow_management_verbs(verb):
    min_version = MIN_VERB_VERSIONS.get(verb)
    if min_version is not None and api.request.version.minor < min_version:
        raise exception.NotAcceptable()


def check_for_invalid_state_and_allow_filter(provision_state):
    """Check if filtering nodes by provision state is allowed.

    Version 1.9 of the API allows filter nodes by provision state.
    """
    if provision_state is not None:
        if (api.request.version.minor
                < versions.MINOR_9_PROVISION_STATE_FILTER):
            raise exception.NotAcceptable()
        valid_states = states.machine.states
        if provision_state not in valid_states:
            raise exception.InvalidParameterValue(
                _('Provision state "%s" is not valid') % provision_state)


def check_allow_specify_driver(driver):
    """Check if filtering nodes by driver is allowed.

    Version 1.16 of the API allows filter nodes by driver.
    """
    if (driver is not None and api.request.version.minor
            < versions.MINOR_16_DRIVER_FILTER):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_16_DRIVER_FILTER})


def check_allow_specify_resource_class(resource_class):
    """Check if filtering nodes by resource_class is allowed.

    Version 1.21 of the API allows filtering nodes by resource_class.
    """
    if (resource_class is not None and api.request.version.minor
            < versions.MINOR_21_RESOURCE_CLASS):
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


_CONFIG_DRIVE_SCHEMA = {
    'anyOf': [
        {
            'type': 'object',
            'properties': {
                'meta_data': {'type': 'object'},
                'network_data': {'type': 'object'},
                'user_data': {
                    'type': ['object', 'array', 'string', 'null']
                },
                'vendor_data': {'type': 'object'},
            },
            'additionalProperties': False
        },
        {
            'type': ['string', 'null']
        }
    ]
}


# Include newlines and spaces since they're common in base64 values.
_B64_ALPHABET = frozenset(string.ascii_letters + string.digits + '+/=\n\r\t ')


def check_allow_configdrive(target, configdrive=None):
    if not configdrive:
        return

    allowed_targets = [states.ACTIVE]
    if allow_node_rebuild_with_configdrive():
        allowed_targets.append(states.REBUILD)

    if target not in allowed_targets:
        msg = (_('Adding a config drive is only supported when setting '
                 'provision state to %s') % ', '.join(allowed_targets))
        raise exception.ClientSideError(
            msg, status_code=http_client.BAD_REQUEST)

    try:
        jsonschema.validate(configdrive, _CONFIG_DRIVE_SCHEMA)
    except json_schema_exc.ValidationError as e:
        msg = _('Invalid configdrive format: %s') % e
        raise exception.ClientSideError(
            msg, status_code=http_client.BAD_REQUEST)

    if isinstance(configdrive, dict):
        if not allow_build_configdrive():
            msg = _('Providing a JSON object for configdrive is only supported'
                    ' starting with API version %(base)s.%(opr)s') % {
                        'base': versions.BASE_VERSION,
                        'opr': versions.MINOR_56_BUILD_CONFIGDRIVE}
            raise exception.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)
        if ('vendor_data' in configdrive
                and not allow_configdrive_vendor_data()):
            msg = _('Providing vendor_data in configdrive is only supported'
                    ' starting with API version %(base)s.%(opr)s') % {
                        'base': versions.BASE_VERSION,
                        'opr': versions.MINOR_59_CONFIGDRIVE_VENDOR_DATA}
            raise exception.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)
    else:
        # : is not a valid base64 symbol, so we can use this simple check
        if '://' in configdrive:
            return

        # This is not 100% robust but it does solve the case of invalid
        # JSON assumed to be a base64 string.
        letters = set(configdrive)
        if letters - _B64_ALPHABET:
            msg = _('Invalid configdrive format: it is neither a JSON, nor '
                    'a URL, nor a base64 string')
            raise exception.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)


def check_allow_filter_by_fault(fault):
    """Check if filtering nodes by fault is allowed.

    Version 1.42 of the API allows filtering nodes by fault.
    """
    if (fault is not None and api.request.version.minor
            < versions.MINOR_42_FAULT):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") % {'base': versions.BASE_VERSION,
                                             'opr': versions.MINOR_42_FAULT})

    if fault is not None and fault not in faults.VALID_FAULTS:
        msg = (_('Unrecognized fault "%(fault)s" is specified, allowed faults '
                 'are %(valid_faults)s') %
               {'fault': fault, 'valid_faults': faults.VALID_FAULTS})
        raise exception.ClientSideError(
            msg, status_code=http_client.BAD_REQUEST)


def check_allow_filter_by_conductor_group(conductor_group):
    """Check if filtering nodes by conductor_group is allowed.

    Version 1.46 of the API allows filtering nodes by conductor_group.
    """
    if (conductor_group is not None and api.request.version.minor
            < versions.MINOR_46_NODE_CONDUCTOR_GROUP):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_46_NODE_CONDUCTOR_GROUP})


def check_allow_filter_by_owner(owner):
    """Check if filtering nodes by owner is allowed.

    Version 1.50 of the API allows filtering nodes by owner.
    """
    if (owner is not None and api.request.version.minor
            < versions.MINOR_50_NODE_OWNER):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_50_NODE_OWNER})


def check_allow_filter_by_lessee(lessee):
    """Check if filtering nodes by lessee is allowed.

    Version 1.62 of the API allows filtering nodes by lessee.
    """
    if (lessee is not None and api.request.version.minor
            < versions.MINOR_65_NODE_LESSEE):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_65_NODE_LESSEE})


def check_allow_filter_by_shard(shard):
    """Check if filtering nodes by shard is allowed.

    Version 1.82 of the API allows filtering nodes by shard.
    """
    if (shard is not None and api.request.version.minor
            < versions.MINOR_82_NODE_SHARD):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_82_NODE_SHARD})


def check_allow_child_node_params(include_children=None,
                                  parent_node=None):
    if ((include_children is not None
         or parent_node is not None)
            and api.request.version.minor
            < versions.MINOR_83_PARENT_CHILD_NODES):
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_83_PARENT_CHILD_NODES})


def initial_node_provision_state():
    """Return node state to use by default when creating new nodes.

    Previously the default state for new nodes was AVAILABLE.
    Starting with API 1.11 it is ENROLL.
    """
    return (states.AVAILABLE
            if api.request.version.minor < versions.MINOR_11_ENROLL_STATE
            else states.ENROLL)


def allow_raid_config():
    """Check if RAID configuration is allowed for the node.

    Version 1.12 of the API allows RAID configuration for the node.
    """
    return api.request.version.minor >= versions.MINOR_12_RAID_CONFIG


def allow_soft_power_off():
    """Check if Soft Power Off is allowed for the node.

    Version 1.27 of the API allows Soft Power Off, including Soft Reboot, for
    the node.
    """
    return api.request.version.minor >= versions.MINOR_27_SOFT_POWER_OFF


def allow_inject_nmi():
    """Check if Inject NMI is allowed for the node.

    Version 1.29 of the API allows Inject NMI for the node.
    """
    return api.request.version.minor >= versions.MINOR_29_INJECT_NMI


def allow_links_node_states_and_driver_properties():
    """Check if links are displayable.

    Version 1.14 of the API allows the display of links to node states
    and driver properties.
    """
    return (api.request.version.minor
            >= versions.MINOR_14_LINKS_NODESTATES_DRIVERPROPERTIES)


def allow_port_internal_info():
    """Check if accessing internal_info is allowed for the port.

    Version 1.18 of the API exposes internal_info readonly field for the port.
    """
    return (api.request.version.minor
            >= versions.MINOR_18_PORT_INTERNAL_INFO)


def allow_port_advanced_net_fields():
    """Check if we should return local_link_connection and pxe_enabled fields.

    Version 1.19 of the API added support for these new fields in port object.
    """
    return (api.request.version.minor
            >= versions.MINOR_19_PORT_ADVANCED_NET_FIELDS)


def allow_ramdisk_endpoints():
    """Check if heartbeat and lookup endpoints are allowed.

    Version 1.22 of the API introduced them.
    """
    return api.request.version.minor >= versions.MINOR_22_LOOKUP_HEARTBEAT


def allow_portgroups():
    """Check if we should support portgroup operations.

    Version 1.23 of the API added support for PortGroups.
    """
    return (api.request.version.minor
            >= versions.MINOR_23_PORTGROUPS)


def allow_portgroups_subcontrollers():
    """Check if portgroups can be used as subcontrollers.

    Version 1.24 of the API added support for Portgroups as
    subcontrollers
    """
    return (api.request.version.minor
            >= versions.MINOR_24_PORTGROUPS_SUBCONTROLLERS)


def allow_remove_chassis_uuid():
    """Check if chassis_uuid can be removed from node.

    Version 1.25 of the API added support for chassis_uuid
    removal
    """
    return (api.request.version.minor
            >= versions.MINOR_25_UNSET_CHASSIS_UUID)


def allow_portgroup_mode_properties():
    """Check if mode and properties can be added to/queried from a portgroup.

    Version 1.26 of the API added mode and properties fields to portgroup
    object.
    """
    return (api.request.version.minor
            >= versions.MINOR_26_PORTGROUP_MODE_PROPERTIES)


def allow_vifs_subcontroller():
    """Check if node/vifs can be used.

    Version 1.28 of the API added support for VIFs to be
    attached to Nodes.
    """
    return (api.request.version.minor
            >= versions.MINOR_28_VIFS_SUBCONTROLLER)


def allow_dynamic_drivers():
    """Check if dynamic driver API calls are allowed.

    Version 1.30 of the API added support for all of the driver
    composition related calls in the /v1/drivers API.
    """
    return (api.request.version.minor
            >= versions.MINOR_30_DYNAMIC_DRIVERS)


def allow_dynamic_interfaces():
    """Check if dynamic interface fields are allowed.

    Version 1.31 of the API added support for viewing and setting the fields
    in ``V31_FIELDS`` on the node object.
    """
    return (api.request.version.minor
            >= versions.MINOR_31_DYNAMIC_INTERFACES)


def allow_volume():
    """Check if volume connectors and targets are allowed.

    Version 1.32 of the API added support for volume connectors and targets
    """
    return api.request.version.minor >= versions.MINOR_32_VOLUME


def allow_storage_interface():
    """Check if we should support storage_interface node and driver fields.

    Version 1.33 of the API added support for storage interfaces.
    """
    return (api.request.version.minor
            >= versions.MINOR_33_STORAGE_INTERFACE)


def allow_port_physical_network():
    """Check if port physical network field is allowed.

    Version 1.34 of the API added the physical network field to the port
    object.  We also check whether the target version of the Port object
    supports the physical_network field as this may not be the case during a
    rolling upgrade.
    """
    return ((api.request.version.minor
             >= versions.MINOR_34_PORT_PHYSICAL_NETWORK)
            and objects.Port.supports_physical_network())


def allow_node_rebuild_with_configdrive():
    """Check if we should support node rebuild with configdrive.

    Version 1.35 of the API added support for node rebuild with configdrive.
    """
    return (api.request.version.minor
            >= versions.MINOR_35_REBUILD_CONFIG_DRIVE)


def allow_agent_version_in_heartbeat():
    """Check if agent version is allowed to be passed into heartbeat.

    Version 1.36 of the API added the ability for agents to pass their version
    information to Ironic on heartbeat.
    """
    return (api.request.version.minor
            >= versions.MINOR_36_AGENT_VERSION_HEARTBEAT)


def allow_rescue_interface():
    """Check if we should support rescue and unrescue operations and interface.

    Version 1.38 of the API added support for rescue and unrescue.
    """
    return api.request.version.minor >= versions.MINOR_38_RESCUE_INTERFACE


def allow_bios_interface():
    """Check if we should support bios interface and endpoints.

    Version 1.40 of the API added support for bios interface.
    """
    return api.request.version.minor >= versions.MINOR_40_BIOS_INTERFACE


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
        reserved_names += list(cls._custom_actions)

    return reserved_names


def allow_traits():
    """Check if traits are allowed for the node.

    Version 1.37 of the API allows traits for the node.
    """
    return api.request.version.minor >= versions.MINOR_37_NODE_TRAITS


def allow_inspect_wait_state():
    """Check if inspect wait is allowed for the node.

    Version 1.39 of the API adds 'inspect wait' state to substitute
    'inspecting' state during asynchronous hardware inspection.
    """
    return api.request.version.minor >= versions.MINOR_39_INSPECT_WAIT


def allow_inspect_abort():
    """Check if inspection abort is allowed.

    Version 1.41 of the API added support for inspection abort
    """
    return api.request.version.minor >= versions.MINOR_41_INSPECTION_ABORT


def allow_detail_query():
    """Check if passing a detail=True query string is allowed.

    Version 1.43 allows a user to pass the detail query string to
    list the resource with all the fields.
    """
    return api.request.version.minor >= versions.MINOR_43_ENABLE_DETAIL_QUERY


def allow_query_bios():
    """Check if BIOS queries should be allowed based on version"""

    return api.request.version.minor >= versions.MINOR_74_BIOS_REGISTRY


def allow_reset_interfaces():
    """Check if passing a reset_interfaces query string is allowed."""
    return api.request.version.minor >= versions.MINOR_45_RESET_INTERFACES


def allow_node_history():
    """Check if node history access is permitted by API version."""
    return api.request.version.minor >= versions.MINOR_78_NODE_HISTORY


def allow_node_inventory():
    """Check if node inventory is allowed."""
    return api.request.version.minor >= versions.MINOR_81_NODE_INVENTORY


def get_request_return_fields(fields, detail, default_fields,
                              check_detail_version=allow_detail_query,
                              check_fields_version=None):
    """Calculate fields to return from an API request

    The fields query and detail=True query can not be passed into a request at
    the same time. To use the detail query we need to be on a version of the
    API greater than expected, likewise some APIs require a certain version for
    the fields query. This function raises an InvalidParameterValue exception
    if any of these conditions are not met.

    If these checks pass then this function will return either the fields
    passed in or the default fields provided.

    :param fields: The fields query passed into the API request.
    :param detail: The detail query passed into the API request.
    :param default_fields: The default fields to return if fields=None and
        detail=None.
    :param check_detail_version: Function to check if detail query is allowed
        based on the version.
    :param check_fields_version: Function to check if fields query is allowed
        based on the version.
    :raises: InvalidParameterValue if there is an invalid combination of query
        strings or API version.
    :returns: 'fields' passed in value or 'default_fields'
    """

    if detail is not None and not check_detail_version():
        raise exception.InvalidParameterValue(
            "Invalid query parameter ?detail=%s received." % detail)

    if (fields is not None and callable(check_fields_version)
            and not check_fields_version()):
        raise exception.InvalidParameterValue(
            "Invalid query parameter ?fields=%s received." % fields)

    if fields is not None and detail:
        raise exception.InvalidParameterValue(
            "Can not specify ?detail=True and fields in the same request.")

    if fields is None and not detail:
        return default_fields
    return fields


def allow_expose_conductors():
    """Check if accessing conductor endpoints is allowed.

    Version 1.49 of the API exposed conductor endpoints and conductor field
    for the node.
    """
    return api.request.version.minor >= versions.MINOR_49_CONDUCTORS


def check_allow_filter_by_conductor(conductor):
    """Check if filtering nodes by conductor is allowed.

    Version 1.49 of the API allows filtering nodes by conductor.
    """
    if conductor is not None and not allow_expose_conductors():
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_49_CONDUCTORS})


def allow_allocations():
    """Check if accessing allocation endpoints is allowed.

    Version 1.52 of the API exposed allocation endpoints and allocation_uuid
    field for the node.
    """
    return api.request.version.minor >= versions.MINOR_52_ALLOCATION


def allow_port_is_smartnic():
    """Check if port is_smartnic field is allowed.

    Version 1.53 of the API added is_smartnic field to the port object.
    """
    return ((api.request.version.minor
             >= versions.MINOR_53_PORT_SMARTNIC)
            and objects.Port.supports_is_smartnic())


def allow_expose_events():
    """Check if accessing events endpoint is allowed.

    Version 1.54 of the API added the events endpoint.
    """
    return api.request.version.minor >= versions.MINOR_54_EVENTS


def allow_deploy_templates():
    """Check if accessing deploy template endpoints is allowed.

    Version 1.55 of the API exposed deploy template endpoints.
    """
    return api.request.version.minor >= versions.MINOR_55_DEPLOY_TEMPLATES


def check_policy(policy_name):
    """Check if the specified policy is authorised for this request.

    :policy_name: Name of the policy to check.
    :raises: HTTPForbidden if the policy forbids access.
    """
    # NOTE(lbragstad): Mapping context attributes into a target dictionary is
    # effectively a noop from an authorization perspective because the values
    # we're comparing are coming from the same place.
    cdict = api.request.context.to_policy_values()

    policy.authorize(policy_name, cdict, api.request.context)


def check_policy_true(policy_name):
    """Check if the specified policy is authorised for this request.

    :policy_name: Name of the policy to check.
    :returns: True if policy is matched, otherwise false.
    """
    # NOTE(lbragstad): Mapping context attributes into a target dictionary is
    # effectively a noop from an authorization perspective because the values
    # we're comparing are coming from the same place.
    cdict = api.request.context.to_policy_values()
    return policy.check_policy(policy_name, cdict, api.request.context)


def check_owner_policy(object_type, policy_name, owner, lessee=None,
                       conceal_node=False):
    """Check if the policy authorizes this request on an object.

    :param: object_type: type of object being checked
    :param: policy_name: Name of the policy to check.
    :param: owner: the owner
    :param: lessee: the lessee
    :param: conceal_node: the UUID of the node IF we should
                          conceal the existence of the node with a
                          404 Error instead of a 403 Error.

    :raises: HTTPForbidden if the policy forbids access.
    """
    cdict = api.request.context.to_policy_values()
    target_dict = dict(cdict)
    target_dict[object_type + '.owner'] = owner
    if lessee:
        target_dict[object_type + '.lessee'] = lessee
    try:
        policy.authorize(policy_name, target_dict, api.request.context)
    except exception.HTTPForbidden:
        if conceal_node:
            # The caller does NOT have access to the node and we've been told
            # we should return a 404 instead of HTTPForbidden.
            raise exception.NodeNotFound(node=conceal_node)
        else:
            raise


def check_node_policy_and_retrieve(policy_name, node_ident,
                                   with_suffix=False):
    """Check if the specified policy authorizes this request on a node.

    :param: policy_name: Name of the policy to check.
    :param: node_ident: the UUID or logical name of a node.
    :param: with_suffix: whether the RPC node should include the suffix

    :raises: HTTPForbidden if the policy forbids access.
    :raises: NodeNotFound if the node is not found.
    :return: RPC node identified by node_ident
    """
    conceal_node = False
    try:
        if with_suffix:
            rpc_node = get_rpc_node_with_suffix(node_ident)
        else:
            rpc_node = get_rpc_node(node_ident)
    except exception.NodeNotFound:
        raise
    # Project scoped users will get a 404 where as system
    # scoped should get a 403
    cdict = api.request.context.to_policy_values()
    if cdict.get('project_id', False):
        conceal_node = node_ident
    try:
        # Always check the ability to see the node BEFORE anything else.
        check_owner_policy('node', 'baremetal:node:get', rpc_node['owner'],
                           rpc_node['lessee'], conceal_node=conceal_node)
    except exception.NotAuthorized:
        raise exception.NodeNotFound(node=node_ident)
    # If we've reached here, we can see the node and we have
    # access to view it.
    check_owner_policy('node', policy_name,
                       rpc_node['owner'], rpc_node['lessee'],
                       conceal_node=False)
    return rpc_node


def check_allocation_policy_and_retrieve(policy_name, allocation_ident):
    """Check if the specified policy authorizes request on allocation.

    :param: policy_name: Name of the policy to check.
    :param: allocation_ident: the UUID or logical name of a node.

    :raises: HTTPForbidden if the policy forbids access.
    :raises: AllocationNotFound if the node is not found.
    :return: RPC node identified by node_ident
    """
    try:
        rpc_allocation = get_rpc_allocation_with_suffix(
            allocation_ident)
        # If the user is not allowed to view the allocation, then
        # we need to check that and respond with a 404.
        check_owner_policy('allocation', 'baremetal:allocation:get',
                           rpc_allocation['owner'])
    except exception.NotAuthorized:
        raise exception.AllocationNotFound(allocation=allocation_ident)
    # The primary policy check for allocation.
    check_owner_policy('allocation', policy_name, rpc_allocation['owner'])
    return rpc_allocation


def check_multiple_node_policies_and_retrieve(policy_names,
                                              node_ident,
                                              with_suffix=False):
    """Check if the specified policies authorize this request on a node.

    :param: policy_names: List of policy names to check.
    :param: node_ident: the UUID or logical name of a node.
    :param: with_suffix: whether the RPC node should include the suffix

    :raises: HTTPForbidden if the policy forbids access.
    :raises: NodeNotFound if the node is not found.
    :return: RPC node identified by node_ident
    """
    rpc_node = None
    for policy_name in policy_names:
        if rpc_node is None:
            rpc_node = check_node_policy_and_retrieve(policy_names[0],
                                                      node_ident,
                                                      with_suffix)
        else:
            check_owner_policy('node', policy_name,
                               rpc_node['owner'], rpc_node['lessee'])
    return rpc_node


def check_list_policy(object_type, owner=None):
    """Check if the list policy authorizes this request on an object.

    :param: object_type: type of object being checked
    :param: owner: owner filter for list query, if any

    :raises: HTTPForbidden if the policy forbids access.
    :return: owner that should be used for list query, if needed
    """
    cdict = api.request.context.to_policy_values()
    try:
        policy.authorize('baremetal:%s:list_all' % object_type,
                         cdict, api.request.context)
    except (exception.HTTPForbidden, oslo_policy.InvalidScope):
        # In the event the scoped policy fails, falling back to the
        # policy governing a filtered view.
        project_owner = cdict.get('project_id')
        if (not project_owner or (owner and owner != project_owner)):
            raise
        policy.authorize('baremetal:%s:list' % object_type,
                         cdict, api.request.context)
        return project_owner
    return owner


def check_port_policy_and_retrieve(policy_name, port_ident, portgroup=False):
    """Check if the specified policy authorizes this request on a port.

    :param: policy_name: Name of the policy to check.
    :param: port_ident: The name, uuid, or other valid ID value to find
                        a port or portgroup by.

    :raises: HTTPForbidden if the policy forbids access.
    :raises: NodeNotFound if the node is not found.
    :return: RPC port identified by port_ident associated node
    """
    context = api.request.context
    cdict = context.to_policy_values()
    owner = None
    lessee = None
    try:
        if not portgroup:
            rpc_port = objects.Port.get(context, port_ident)
        else:
            rpc_port = objects.Portgroup.get(context, port_ident)
    except (exception.PortNotFound, exception.PortgroupNotFound):
        # don't expose non-existence of port unless requester
        # has generic access to policy
        raise

    target_dict = dict(cdict)
    try:
        rpc_node = objects.Node.get_by_id(context, rpc_port.node_id)
        owner = rpc_node['owner']
        lessee = rpc_node['lessee']
    except exception.NodeNotFound:
        # There is no spoon, err, node.
        rpc_node = None
        pass
    target_dict = dict(cdict)
    target_dict['node.owner'] = owner
    target_dict['node.lessee'] = lessee
    try:
        policy.authorize('baremetal:node:get', target_dict, context)
    except exception.NotAuthorized:
        if not portgroup:
            raise exception.PortNotFound(port=port_ident)
        else:
            raise exception.PortgroupNotFound(portgroup=port_ident)

    policy.authorize(policy_name, target_dict, context)

    return rpc_port, rpc_node


def check_port_list_policy(portgroup=False, parent_node=None,
                           parent_portgroup=None):
    """Check if the specified policy authorizes this request on a port.

    :param portgroup: Boolean value, default false, indicating if the list
                      policy check is for a portgroup as the policy names
                      are different between ports and portgroups.
    :param parent_node: The UUID of a node, if any, to apply a policy
                        check to as well before applying other policy
                        check operations.
    :param parent_portgroup: The UUID of the parent portgroup if the list
                             of ports was retrieved via the
                             /v1/portgroups/<uuid>/ports.

    :raises: HTTPForbidden if the policy forbids access.
    :return: owner that should be used for list query, if needed
    """

    cdict = api.request.context.to_policy_values()

    # No node is associated with this request, yet.
    rpc_node = None
    conceal_linked_node = None

    if parent_portgroup:
        # lookup the portgroup via the db, and then set parent_node
        rpc_portgroup = objects.Portgroup.get_by_uuid(api.request.context,
                                                      parent_portgroup)
        rpc_node = objects.Node.get_by_id(api.request.context,
                                          rpc_portgroup.node_id)
        parent_node = rpc_node.uuid

    if parent_node and not rpc_node:
        try:
            rpc_node = objects.Node.get_by_uuid(api.request.context,
                                                parent_node)
            conceal_linked_node = rpc_node.uuid
        except exception.NotFound:
            # NOTE(TheJulia): This only covers portgroups since
            # you can't go from ports to other items.
            raise exception.PortgroupNotFound(portgroup=parent_portgroup)

    if parent_node:
        try:
            check_owner_policy(
                'node', 'baremetal:node:get',
                rpc_node.owner, rpc_node.lessee,
                conceal_node=conceal_linked_node)
        except exception.NotAuthorized:
            if parent_portgroup:
                # If this call was invoked with a parent portgroup
                # then we need to signal the parent portgroup was not
                # found.
                raise exception.PortgroupNotFound(
                    portgroup=parent_portgroup)
            if parent_node:
                # This should likely never be hit, because
                # the existence of a parent node should
                # trigger the node not found exception to be
                # explicitly raised.
                raise exception.NodeNotFound(
                    node=parent_node)
            raise

    try:
        if not portgroup:
            policy.authorize('baremetal:port:list_all',
                             cdict, api.request.context)
        else:
            policy.authorize('baremetal:portgroup:list_all',
                             cdict, api.request.context)
    except exception.HTTPForbidden:
        owner = cdict.get('project_id')
        if not owner:
            raise
        if not portgroup:
            policy.authorize('baremetal:port:list',
                             cdict, api.request.context)
        else:
            policy.authorize('baremetal:portgroup:list',
                             cdict, api.request.context)
        return owner


def check_volume_list_policy(parent_node=None):
    """Check if the specified policy authorizes this request on a volume.

    :param parent_node: The UUID of a node, if any, to apply a policy
                        check to as well before applying other policy
                        check operations.

    :raises: HTTPForbidden if the policy forbids access.
    :return: owner that should be used for list query, if needed
    """

    cdict = api.request.context.to_policy_values()

    # No node is associated with this request, yet.
    rpc_node = None
    conceal_linked_node = None

    if parent_node:
        try:
            rpc_node = objects.Node.get_by_uuid(api.request.context,
                                                parent_node)
            conceal_linked_node = rpc_node.uuid
        except exception.NotFound:
            raise exception.NodeNotFound(node=parent_node)
    if parent_node:
        try:
            check_owner_policy(
                'node', 'baremetal:node:get',
                rpc_node.owner, rpc_node.lessee,
                conceal_node=conceal_linked_node)
        except exception.NotAuthorized:
            if parent_node:
                # This should likely never be hit, because
                # the existence of a parent node should
                # trigger the node not found exception to be
                # explicitly raised.
                raise exception.NodeNotFound(
                    node=parent_node)
            raise

    try:
        policy.authorize('baremetal:volume:list_all',
                         cdict, api.request.context)
    except exception.HTTPForbidden:
        project_id = cdict.get('project_id')
        if not project_id:
            raise
        policy.authorize('baremetal:volume:list',
                         cdict, api.request.context)
        return project_id


def check_volume_policy_and_retrieve(policy_name, vol_ident, target=False):
    """Check if the specified policy authorizes this request on a volume.

    :param: policy_name: Name of the policy to check.
    :param: vol_ident: The name, uuid, or other valid ID value to find
                        a volume target or connector by.
    :param: target: Boolean value to indicate if the check is for a volume
                    target or connector. Default value is False, implying
                    connector.

    :raises: HTTPForbidden if the policy forbids access.
    :raises: VolumeConnectorNotFound if the node is not found.
    :raises: VolumeTargetNotFound if the node is not found.
    :return: RPC port identified by port_ident associated node
    """
    context = api.request.context
    cdict = context.to_policy_values()
    owner = None
    lessee = None
    try:
        if not target:
            rpc_vol = objects.VolumeConnector.get(context, vol_ident)
        else:
            rpc_vol = objects.VolumeTarget.get(context, vol_ident)
    except (exception.VolumeConnectorNotFound, exception.VolumeTargetNotFound):
        # don't expose non-existence of volume unless requester
        # has generic access to policy
        raise

    target_dict = dict(cdict)
    try:
        rpc_node = objects.Node.get_by_id(context, rpc_vol.node_id)
        owner = rpc_node['owner']
        lessee = rpc_node['lessee']
    except exception.NodeNotFound:
        pass
    target_dict = dict(cdict)
    target_dict['node.owner'] = owner
    target_dict['node.lessee'] = lessee
    try:
        policy.authorize('baremetal:node:get', target_dict, context)
    except exception.NotAuthorized:
        if not target:
            raise exception.VolumeConnectorNotFound(connector=vol_ident)
        else:
            raise exception.VolumeTargetNotFound(target=vol_ident)

    policy.authorize(policy_name, target_dict, context)

    return rpc_vol, rpc_node


def allow_build_configdrive():
    """Check if building configdrive is allowed.

    Version 1.56 of the API added support for building configdrive.
    """
    return api.request.version.minor >= versions.MINOR_56_BUILD_CONFIGDRIVE


def allow_configdrive_vendor_data():
    """Check if configdrive can contain a vendor_data key.

    Version 1.59 of the API added support for configdrive vendor_data.
    """
    return (api.request.version.minor
            >= versions.MINOR_59_CONFIGDRIVE_VENDOR_DATA)


def allow_allocation_update():
    """Check if updating an existing allocation is allowed or not.

    Version 1.57 of the API added support for updating an allocation.
    """
    return api.request.version.minor >= versions.MINOR_57_ALLOCATION_UPDATE


def allow_allocation_backfill():
    """Check if backfilling allocations is allowed.

    Version 1.58 of the API added support for backfilling allocations.
    """
    return api.request.version.minor >= versions.MINOR_58_ALLOCATION_BACKFILL


def allow_allocation_owner():
    """Check if allocation owner field is allowed.

    Version 1.60 of the API added the owner field to the allocation object.
    """
    return api.request.version.minor >= versions.MINOR_60_ALLOCATION_OWNER


def allow_agent_token():
    """Check if agent token is available."""
    return api.request.version.minor >= versions.MINOR_62_AGENT_TOKEN


def allow_local_link_connection_network_type():
    """Check if network_type is allowed in ports link_local_connection"""
    return (api.request.version.minor
            >= versions.MINOR_64_LOCAL_LINK_CONNECTION_NETWORK_TYPE)


def allow_verify_ca_in_heartbeat():
    """Check if heartbeat accepts agent_verify_ca."""
    return api.request.version.minor >= versions.MINOR_68_HEARTBEAT_VERIFY_CA


def allow_deploy_steps():
    """Check if deploy_steps are available."""
    return api.request.version.minor >= versions.MINOR_69_DEPLOY_STEPS


def allow_status_in_heartbeat():
    """Check if heartbeat accepts agent_status and agent_status_message."""
    return api.request.version.minor >= versions.MINOR_72_HEARTBEAT_STATUS


def allow_unhold_verb():
    """Check if the unhold verb may be passed to the API"""
    return api.request.version.minor >= versions.MINOR_85_UNHOLD_VERB


def check_allow_deploy_steps(target, deploy_steps):
    """Check if deploy steps are allowed"""

    if not deploy_steps:
        return

    if not allow_deploy_steps():
        raise exception.NotAcceptable(_(
            "Request not acceptable. The minimal required API version "
            "should be %(base)s.%(opr)s") %
            {'base': versions.BASE_VERSION,
             'opr': versions.MINOR_69_DEPLOY_STEPS})

    allowed_states = (states.ACTIVE, states.REBUILD)
    if target not in allowed_states:
        msg = (_('"deploy_steps" is only valid when setting target '
                 'provision state to %s or %s') % allowed_states)
        raise exception.ClientSideError(
            msg, status_code=http_client.BAD_REQUEST)


def check_allow_clean_disable_ramdisk(target, disable_ramdisk):
    if disable_ramdisk is None:
        return
    elif api.request.version.minor < versions.MINOR_70_CLEAN_DISABLE_RAMDISK:
        raise exception.NotAcceptable(
            _("disable_ramdisk is not acceptable in this API version"))
    elif target != "clean":
        raise exception.BadRequest(
            _("disable_ramdisk is supported only with manual cleaning"))


def allow_shards_endpoint():
    """Check if shards endpoint is available."""
    return api.request.version.minor >= versions.MINOR_82_NODE_SHARD


def new_continue_inspection_endpoint():
    """Check if /v1/continue_inspection endpoint is explicitly requested."""
    return api.request.version.minor >= versions.MINOR_84_CONTINUE_INSPECTION


def allow_continue_inspection_endpoint():
    """Check if /v1/continue_inspection endpoint is available.

    As a special exception, we allow it in the base version so that the API
    can be used as a drop-in replacement for the Inspector's API.
    """
    return (new_continue_inspection_endpoint()
            or api.request.version.minor == versions.MINOR_1_INITIAL_VERSION)


def allow_firmware_interface():
    """Check if we should support firmware interface and endpoints.

    Version 1.84 of the API added support for firmware interface.
    """
    return api.request.version.minor >= versions.MINOR_86_FIRMWARE_INTERFACE
