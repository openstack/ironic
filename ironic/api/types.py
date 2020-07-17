# coding: utf-8
#
# Copyright 2020 Red Hat, Inc.
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

from wsme.types import ArrayType  # noqa
from wsme.types import Base  # noqa
from wsme.types import DictType  # noqa
from wsme.types import Enum  # noqa
from wsme.types import File  # noqa
from wsme.types import IntegerType  # noqa
from wsme.types import iscomplex  # noqa
from wsme.types import isusertype  # noqa
from wsme.types import list_attributes  # noqa
from wsme.types import registry  # noqa
from wsme.types import StringType  # noqa
from wsme.types import text  # noqa
from wsme.types import Unset  # noqa
from wsme.types import UnsetType  # noqa
from wsme.types import UserType  # noqa
from wsme.types import validate_value  # noqa
from wsme.types import wsattr  # noqa
from wsme.types import wsproperty  # noqa


class Response(object):
    """Object to hold the "response" from a view function"""
    def __init__(self, obj, status_code=None, error=None,
                 return_type=Unset):
        #: Store the result object from the view
        self.obj = obj

        #: Store an optional status_code
        self.status_code = status_code

        #: Return error details
        #: Must be a dictionnary with the following keys: faultcode,
        #: faultstring and an optional debuginfo
        self.error = error

        #: Return type
        #: Type of the value returned by the function
        #: If the return type is wsme.types.Unset it will be ignored
        #: and the default return type will prevail.
        self.return_type = return_type
