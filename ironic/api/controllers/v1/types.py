# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

import re
import six

from wsme import types as wtypes

from ironic.common import exception
from ironic.common import utils


class MacAddressType(wtypes.UserType):
    """A simple MAC address type."""

    basetype = wtypes.text
    name = 'macaddress'

    @staticmethod
    def validate(value):
        if not utils.is_valid_mac(value):
            raise exception.InvalidMAC(mac=value)
        return value

    @staticmethod
    def frombasetype(value):
        return MacAddressType.validate(value)


# TODO(lucasagomes): WSME already has one UuidType implementation on trunk,
#                    so remove it on the next WSME release (> 0.5b6)
class UuidType(wtypes.UserType):
    """A simple UUID type."""

    basetype = wtypes.text
    name = 'uuid'

    @staticmethod
    def validate(value):
        if not utils.is_uuid_like(value):
            raise exception.InvalidUUID(uuid=value)
        return value

    @staticmethod
    def frombasetype(value):
        return UuidType.validate(value)


macaddress = MacAddressType()
uuid = UuidType()


# TODO(lucasagomes): WSME already has this StringType implementation on trunk,
#                    so remove it on the next WSME release (> 0.5b6)
class StringType(wtypes.UserType):
    """A simple string type. Can validate a length and a pattern.

    :param min_length: Possible minimum length
    :param max_length: Possible maximum length
    :param pattern: Possible string pattern

    Example::

    Name = StringType(min_length=1, pattern='^[a-zA-Z ]*$')

    """
    basetype = six.string_types
    name = "string"

    def __init__(self, min_length=None, max_length=None, pattern=None):
        self.min_length = min_length
        self.max_length = max_length
        if isinstance(pattern, six.string_types):
            self.pattern = re.compile(pattern)
        else:
            self.pattern = pattern

    def validate(self, value):
        if not isinstance(value, self.basetype):
            error = 'Value should be string'
            raise ValueError(error)

        if self.min_length is not None and len(value) < self.min_length:
            error = 'Value should have a minimum character requirement of %s' \
                    % self.min_length
            raise ValueError(error)

        if self.max_length is not None and len(value) > self.max_length:
            error = 'Value should have a maximum character requirement of %s' \
                    % self.max_length
            raise ValueError(error)

        if self.pattern is not None and not self.pattern.match(value):
            error = 'Value should match the pattern %s' % self.pattern.pattern
            raise ValueError(error)

        return value
