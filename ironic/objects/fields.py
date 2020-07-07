# Copyright 2015 Red Hat, Inc.
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

import ast

from oslo_versionedobjects import fields as object_fields

from ironic.common import utils


class IntegerField(object_fields.IntegerField):
    pass


class UUIDField(object_fields.UUIDField):
    pass


class StringField(object_fields.StringField):
    pass


class StringAcceptsCallable(object_fields.String):
    @staticmethod
    def coerce(obj, attr, value):
        if callable(value):
            value = value()
        return super(StringAcceptsCallable, StringAcceptsCallable).coerce(
            obj, attr, value)


class StringFieldThatAcceptsCallable(object_fields.StringField):
    """Custom StringField object that allows for functions as default

    In some cases we need to allow for dynamic defaults based on configuration
    options, this StringField object allows for a function to be passed as a
    default, and will only process it at the point the field is coerced
    """

    AUTO_TYPE = StringAcceptsCallable()

    def __repr__(self):
        default = self._default
        if (self._default != object_fields.UnspecifiedDefault
                and callable(self._default)):
            default = '<function %s>' % default.__name__
        return '%s(default=%s,nullable=%s)' % (self._type.__class__.__name__,
                                               default, self._nullable)


class DateTimeField(object_fields.DateTimeField):
    pass


class BooleanField(object_fields.BooleanField):
    pass


class ListOfStringsField(object_fields.ListOfStringsField):
    pass


class ObjectField(object_fields.ObjectField):
    pass


class ListOfObjectsField(object_fields.ListOfObjectsField):
    pass


class FlexibleDict(object_fields.FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, str):
            value = ast.literal_eval(value)
        return dict(value)


class FlexibleDictField(object_fields.AutoTypedField):
    AUTO_TYPE = FlexibleDict()

    # TODO(lucasagomes): In our code we've always translated None to {},
    # this method makes this field to work like this. But probably won't
    # be accepted as-is in the oslo_versionedobjects library
    def _null(self, obj, attr):
        if self.nullable:
            return {}
        super(FlexibleDictField, self)._null(obj, attr)


class ListOfFlexibleDictsField(object_fields.AutoTypedField):
    AUTO_TYPE = object_fields.List(FlexibleDict())


class EnumField(object_fields.EnumField):
    pass


class NotificationLevel(object_fields.Enum):
    DEBUG = 'debug'
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'

    ALL = (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    def __init__(self):
        super(NotificationLevel, self).__init__(
            valid_values=NotificationLevel.ALL)


class NotificationLevelField(object_fields.BaseEnumField):
    AUTO_TYPE = NotificationLevel()


class NotificationStatus(object_fields.Enum):
    START = 'start'
    END = 'end'
    ERROR = 'error'
    SUCCESS = 'success'

    ALL = (START, END, ERROR, SUCCESS)

    def __init__(self):
        super(NotificationStatus, self).__init__(
            valid_values=NotificationStatus.ALL)


class NotificationStatusField(object_fields.BaseEnumField):
    AUTO_TYPE = NotificationStatus()


class MACAddress(object_fields.FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return utils.validate_and_normalize_mac(value)


class MACAddressField(object_fields.AutoTypedField):
    AUTO_TYPE = MACAddress()
