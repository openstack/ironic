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

from ironic.api.controllers import base
from ironic.api.controllers.v1 import utils as v1_utils
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils


LOG = log.getLogger(__name__)


class MacAddressType(atypes.UserType):
    """A simple MAC address type."""

    basetype = str
    name = 'macaddress'

    @staticmethod
    def validate(value):
        return utils.validate_and_normalize_mac(value)

    @staticmethod
    def frombasetype(value):
        if value is None:
            return None
        return MacAddressType.validate(value)


class UuidOrNameType(atypes.UserType):
    """A simple UUID or logical name type."""

    basetype = str
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


class NameType(atypes.UserType):
    """A simple logical name type."""

    basetype = str
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


class UuidType(atypes.UserType):
    """A simple UUID type."""

    basetype = str
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


class BooleanType(atypes.UserType):
    """A simple boolean type."""

    basetype = str
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


class JsonType(atypes.UserType):
    """A simple JSON type."""

    basetype = str
    name = 'json'

    def __str__(self):
        # These are the json serializable native types
        return ' | '.join(map(str, (str, int, float,
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


class ListType(atypes.UserType):
    """A simple list type."""

    basetype = str
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


class JsonPatchType(base.Base):
    """A complex type that represents a single json-patch operation."""

    path = atypes.wsattr(atypes.StringType(pattern='^(/[\\w-]+)+$'),
                         mandatory=True)
    op = atypes.wsattr(atypes.Enum(str, 'add', 'replace', 'remove'),
                       mandatory=True)
    value = atypes.wsattr(jsontype, default=atypes.Unset)

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
            raise exception.ClientSideError(msg % patch.path)

        if patch.path in patch.non_removable_attrs() and patch.op == 'remove':
            msg = _("'%s' is a mandatory attribute and can not be removed")
            raise exception.ClientSideError(msg % patch.path)

        if patch.op != 'remove':
            if patch.value is atypes.Unset:
                msg = _("'add' and 'replace' operations need a value")
                raise exception.ClientSideError(msg)

        ret = {'path': patch.path, 'op': patch.op}
        if patch.value is not atypes.Unset:
            ret['value'] = patch.value
        return ret
