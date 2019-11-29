# coding: utf-8
#
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
import json

from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import wsme
from wsme import types as wtypes

from ironic.api.controllers.v1 import utils as v1_utils
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils


LOG = log.getLogger(__name__)


class MacAddressType(wtypes.UserType):
    """A simple MAC address type."""

    basetype = wtypes.text
    name = 'macaddress'

    @staticmethod
    def validate(value):
        return utils.validate_and_normalize_mac(value)

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return MacAddressType.validate(value)


class UuidOrNameType(wtypes.UserType):
    """A simple UUID or logical name type."""

    basetype = wtypes.text
    name = 'uuid_or_name'

    @staticmethod
    def validate(value):
        if not (uuidutils.is_uuid_like(value)
                or v1_utils.is_valid_logical_name(value)):
            raise exception.InvalidUuidOrName(name=value)
        return value

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return UuidOrNameType.validate(value)


class NameType(wtypes.UserType):
    """A simple logical name type."""

    basetype = wtypes.text
    name = 'name'

    @staticmethod
    def validate(value):
        if not v1_utils.is_valid_logical_name(value):
            raise exception.InvalidName(name=value)
        return value

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return NameType.validate(value)


class UuidType(wtypes.UserType):
    """A simple UUID type."""

    basetype = wtypes.text
    name = 'uuid'

    @staticmethod
    def validate(value):
        if not uuidutils.is_uuid_like(value):
            raise exception.InvalidUUID(uuid=value)
        return value

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return UuidType.validate(value)


class BooleanType(wtypes.UserType):
    """A simple boolean type."""

    basetype = wtypes.text
    name = 'boolean'

    @staticmethod
    def validate(value):
        try:
            return strutils.bool_from_string(value, strict=True)
        except ValueError as e:
            # raise Invalid to return 400 (BadRequest) in the API
            raise exception.Invalid(str(e))

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return BooleanType.validate(value)


class JsonType(wtypes.UserType):
    """A simple JSON type."""

    basetype = wtypes.text
    name = 'json'

    def __str__(self):
        # These are the json serializable native types
        return ' | '.join(map(str, (wtypes.text, int, float,
                                    BooleanType, list, dict, None)))

    @staticmethod
    def validate(value):
        try:
            json.dumps(value)
        except TypeError:
            raise exception.Invalid(_('%s is not JSON serializable') % value)
        else:
            return value

    @staticmethod
    def frombasetype(value):
        return JsonType.validate(value)


class ListType(wtypes.UserType):
    """A simple list type."""

    basetype = wtypes.text
    name = 'list'

    @staticmethod
    def validate(value):
        """Validate and convert the input to a ListType.

        :param value: A comma separated string of values
        :returns: A list of unique values (lower-cased), maintaining the
                  same order
        """
        items = []
        for v in str(value).split(','):
            v_norm = v.strip().lower()
            if v_norm and v_norm not in items:
                items.append(v_norm)
        return items

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return ListType.validate(value)


macaddress = MacAddressType()
uuid_or_name = UuidOrNameType()
name = NameType()
uuid = UuidType()
boolean = BooleanType()
listtype = ListType()
# Can't call it 'json' because that's the name of the stdlib module
jsontype = JsonType()


class JsonPatchType(wtypes.Base):
    """A complex type that represents a single json-patch operation."""

    path = wtypes.wsattr(wtypes.StringType(pattern='^(/[\\w-]+)+$'),
                         mandatory=True)
    op = wtypes.wsattr(wtypes.Enum(str, 'add', 'replace', 'remove'),
                       mandatory=True)
    value = wsme.wsattr(jsontype, default=wtypes.Unset)

    # The class of the objects being patched. Override this in subclasses.
    # Should probably be a subclass of ironic.api.controllers.base.APIBase.
    _api_base = None

    # Attributes that are not required for construction, but which may not be
    # removed if set. Override in subclasses if needed.
    _extra_non_removable_attrs = set()

    # Set of non-removable attributes, calculated lazily.
    _non_removable_attrs = None

    @staticmethod
    def internal_attrs():
        """Returns a list of internal attributes.

        Internal attributes can't be added, replaced or removed. This
        method may be overwritten by derived class.

        """
        return ['/created_at', '/id', '/links', '/updated_at', '/uuid']

    @classmethod
    def non_removable_attrs(cls):
        """Returns a set of names of attributes that may not be removed.

        Attributes whose 'mandatory' property is True are automatically added
        to this set. To add additional attributes to the set, override the
        field _extra_non_removable_attrs in subclasses, with a set of the form
        {'/foo', '/bar'}.
        """
        if cls._non_removable_attrs is None:
            cls._non_removable_attrs = cls._extra_non_removable_attrs.copy()
            if cls._api_base:
                fields = inspect.getmembers(cls._api_base,
                                            lambda a: not inspect.isroutine(a))
                for name, field in fields:
                    if getattr(field, 'mandatory', False):
                        cls._non_removable_attrs.add('/%s' % name)
        return cls._non_removable_attrs

    @staticmethod
    def validate(patch):
        _path = '/' + patch.path.split('/')[1]
        if _path in patch.internal_attrs():
            msg = _("'%s' is an internal attribute and can not be updated")
            raise wsme.exc.ClientSideError(msg % patch.path)

        if patch.path in patch.non_removable_attrs() and patch.op == 'remove':
            msg = _("'%s' is a mandatory attribute and can not be removed")
            raise wsme.exc.ClientSideError(msg % patch.path)

        if patch.op != 'remove':
            if patch.value is wsme.Unset:
                msg = _("'add' and 'replace' operations need a value")
                raise wsme.exc.ClientSideError(msg)

        ret = {'path': patch.path, 'op': patch.op}
        if patch.value is not wsme.Unset:
            ret['value'] = patch.value
        return ret


class LocalLinkConnectionType(wtypes.UserType):
    """A type describing local link connection."""

    basetype = wtypes.DictType
    name = 'locallinkconnection'

    local_link_mandatory_fields = {'port_id', 'switch_id'}
    smart_nic_mandatory_fields = {'port_id', 'hostname'}
    mandatory_fields_list = [local_link_mandatory_fields,
                             smart_nic_mandatory_fields]
    optional_field = {'switch_info'}
    valid_fields = set.union(optional_field, *mandatory_fields_list)

    @staticmethod
    def validate(value):
        """Validate and convert the input to a LocalLinkConnectionType.

        :param value: A dictionary of values to validate, switch_id is a MAC
            address or an OpenFlow based datapath_id, switch_info is an
            optional field. Required Smart NIC fields are port_id and hostname.

        For example::

         {
            'switch_id': mac_or_datapath_id(),
            'port_id': 'Ethernet3/1',
            'switch_info': 'switch1'
         }

        Or for Smart NIC::

         {
            'port_id': 'rep0-0',
            'hostname': 'host1-bf'
         }

        :returns: A dictionary.
        :raises: Invalid if some of the keys in the dictionary being validated
            are unknown, invalid, or some required ones are missing.
        """
        wtypes.DictType(wtypes.text, wtypes.text).validate(value)

        keys = set(value)

        # This is to workaround an issue when an API object is initialized from
        # RPC object, in which dictionary fields that are set to None become
        # empty dictionaries
        if not keys:
            return value

        invalid = keys - LocalLinkConnectionType.valid_fields
        if invalid:
            raise exception.Invalid(_('%s are invalid keys') % (invalid))

        # Check any mandatory fields sets are present
        for mandatory_set in LocalLinkConnectionType.mandatory_fields_list:
            if mandatory_set <= keys:
                break
        else:
            msg = _('Missing mandatory keys. Required keys are '
                    '%(required_fields)s. Or in case of Smart NIC '
                    '%(smart_nic_required_fields)s. '
                    'Submitted keys are %(keys)s .') % {
                'required_fields':
                    LocalLinkConnectionType.local_link_mandatory_fields,
                'smart_nic_required_fields':
                    LocalLinkConnectionType.smart_nic_mandatory_fields,
                'keys': keys}
            raise exception.Invalid(msg)

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

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return LocalLinkConnectionType.validate(value)

    @staticmethod
    def validate_for_smart_nic(value):
        """Validates Smart NIC field are present 'port_id' and 'hostname'

        :param value: local link information of type Dictionary.
        :return: True if both fields 'port_id' and 'hostname' are present
            in 'value', False otherwise.
        """
        wtypes.DictType(wtypes.text, wtypes.text).validate(value)
        keys = set(value)

        if LocalLinkConnectionType.smart_nic_mandatory_fields <= keys:
            return True
        return False


locallinkconnectiontype = LocalLinkConnectionType()


class VifType(JsonType):

    basetype = wtypes.text
    name = 'viftype'

    mandatory_fields = {'id'}

    @staticmethod
    def validate(value):
        super(VifType, VifType).validate(value)
        keys = set(value)
        # Check all mandatory fields are present
        missing = VifType.mandatory_fields - keys
        if missing:
            msg = _('Missing mandatory keys: %s') % ', '.join(list(missing))
            raise exception.Invalid(msg)
        UuidOrNameType.validate(value['id'])

        return value

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return VifType.validate(value)


viftype = VifType()


class EventType(wtypes.UserType):
    """A simple Event type."""

    basetype = wtypes.DictType
    name = 'event'

    def _validate_network_port_event(value):
        """Validate network port event fields.

        :param value: A event dict
        :returns: value
        :raises: Invalid if network port event not in proper format
        """

        validators = {
            'port_id': UuidType.validate,
            'mac_address': MacAddressType.validate,
            'status': wtypes.text,
            'device_id': UuidType.validate,
            'binding:host_id': UuidType.validate,
            'binding:vnic_type': wtypes.text
        }

        keys = set(value)
        net_keys = set(validators)
        net_mandatory_fields = {'port_id', 'mac_address', 'status'}

        # Check all keys are valid for network port event
        invalid = keys.difference(EventType.mandatory_fields.union(net_keys))
        if invalid:
            raise exception.Invalid(_('%s are invalid keys') %
                                    ', '.join(invalid))

        # Check all mandatory fields for network port event is present
        missing = net_mandatory_fields.difference(keys)
        if missing:
            raise exception.Invalid(_('Missing mandatory keys: %s')
                                    % ', '.join(missing))

        # Check all values are of expected type
        for key in net_keys:
            if key in value:
                try:
                    validators[key](value[key])
                except Exception as e:
                    msg = (_('Event validation failure for %(key)s. '
                             '%(message)s') % {'key': key, 'message': e})
                    raise exception.Invalid(msg)

        return value

    mandatory_fields = {'event'}
    event_validators = {
        'network.bind_port': _validate_network_port_event,
        'network.unbind_port': _validate_network_port_event,
        'network.delete_port': _validate_network_port_event,
    }
    valid_events = set(event_validators)

    @staticmethod
    def validate(value):
        """Validate the input

        :param value: A event dict
        :returns: value
        :raises: Invalid if event not in proper format
        """

        wtypes.DictType(wtypes.text, wtypes.text).validate(value)
        keys = set(value)

        # Check all mandatory fields are present
        missing = EventType.mandatory_fields.difference(keys)
        if missing:
            raise exception.Invalid(_('Missing mandatory keys: %s') %
                                    ', '.join(missing))

        # Check event is a supported event
        if value['event'] not in EventType.valid_events:
            raise exception.Invalid(
                _('%(event)s is not one of valid events: %(valid_events)s.') %
                {'event': value['event'],
                 'valid_events': ', '.join(EventType.valid_events)})

        return EventType.event_validators[value['event']](value)


eventtype = EventType()
