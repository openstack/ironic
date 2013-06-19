#    Copyright 2013 IBM Corp.
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

import functools

from ironic.objects import chassis
from ironic.objects import node
from ironic.objects import port


def objectify(klass):
    """Decorator to convert database results into specified objects."""
    def the_decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            try:
                return klass._from_db_object(klass(), result)
            except TypeError:
                # TODO(deva): handle lists of objects better
                #             once support for those lands and is imported.
                return [klass._from_db_object(klass(), obj) for obj in result]
        return wrapper
    return the_decorator

Chassis = chassis.Chassis
Node = node.Node
Port = port.Port

__all__ = (Chassis,
           Node,
           Port,
           objectify)
