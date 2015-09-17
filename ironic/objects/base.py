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

"""Ironic common internal object model"""

from oslo_context import context
from oslo_log import log as logging
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.common.i18n import _
from ironic.objects import fields as object_fields


LOG = logging.getLogger('object')


class IronicObjectRegistry(object_base.VersionedObjectRegistry):
    pass


# These are decorators that mark an object's method as remotable.
# If the metaclass is configured to forward object methods to an
# indirection service, these will result in making an RPC call
# instead of directly calling the implementation in the object. Instead,
# the object implementation on the remote end will perform the
# requested action and the result will be returned here.
def remotable_classmethod(fn):
    """Decorator for remotable classmethods."""
    def wrapper(cls, context, *args, **kwargs):
        if IronicObject.indirection_api:
            result = IronicObject.indirection_api.object_class_action(
                context, cls.obj_name(), fn.__name__, cls.VERSION,
                args, kwargs)
        else:
            result = fn(cls, context, *args, **kwargs)
            if isinstance(result, IronicObject):
                result._context = context
        return result
    return classmethod(wrapper)


# See comment above for remotable_classmethod()
#
# Note that this will use either the provided context, or the one
# stashed in the object. If neither are present, the object is
# "orphaned" and remotable methods cannot be called.
def remotable(fn):
    """Decorator for remotable object methods."""
    def wrapper(self, *args, **kwargs):
        ctxt = self._context
        try:
            if isinstance(args[0], (context.RequestContext)):
                ctxt = args[0]
                args = args[1:]
        except IndexError:
            pass
        if ctxt is None:
            raise exception.OrphanedObjectError(method=fn.__name__,
                                                objtype=self.obj_name())
        if IronicObject.indirection_api:
            updates, result = IronicObject.indirection_api.object_action(
                ctxt, self, fn.__name__, args, kwargs)
            for key, value in updates.items():
                if key in self.fields:
                    field = self.fields[key]
                    self[key] = field.from_primitive(self, key, value)
            self._changed_fields = set(updates.get('obj_what_changed', []))
            return result
        else:
            return fn(self, ctxt, *args, **kwargs)
    return wrapper


# Object versioning rules
#
# Each service has its set of objects, each with a version attached. When
# a client attempts to call an object method, the server checks to see if
# the version of that object matches (in a compatible way) its object
# implementation. If so, cool, and if not, fail.
def check_object_version(server, client):
    try:
        client_major, _client_minor = client.split('.')
        server_major, _server_minor = server.split('.')
        client_minor = int(_client_minor)
        server_minor = int(_server_minor)
    except ValueError:
        raise exception.IncompatibleObjectVersion(
            _('Invalid version string'))

    if client_major != server_major:
        raise exception.IncompatibleObjectVersion(
            dict(client=client_major, server=server_major))
    if client_minor > server_minor:
        raise exception.IncompatibleObjectVersion(
            dict(client=client_minor, server=server_minor))


class IronicObject(object_base.VersionedObject):
    """Base class and object factory.

    This forms the base of all objects that can be remoted or instantiated
    via RPC. Simply defining a class that inherits from this base class
    will make it remotely instantiatable. Objects should implement the
    necessary "get" classmethod routines as well as "save" object methods
    as appropriate.
    """

    OBJ_SERIAL_NAMESPACE = 'ironic_object'
    OBJ_PROJECT_NAMESPACE = 'ironic'

    # TODO(lintan) Refactor these fields and create PersistentObject and
    # TimeStampObject like Nova when it is necessary.
    fields = {
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
    }

    def as_dict(self):
        return dict((k, getattr(self, k))
                    for k in self.fields
                    if hasattr(self, k))

    def obj_refresh(self, loaded_object):
        """Applies updates for objects that inherit from base.IronicObject.

        Checks for updated attributes in an object. Updates are applied from
        the loaded object column by column in comparison with the current
        object.
        """
        for field in self.fields:
            if (self.obj_attr_is_set(field) and
                    self[field] != loaded_object[field]):
                self[field] = loaded_object[field]


class IronicObjectSerializer(object_base.VersionedObjectSerializer):
    # Base class to use for object hydration
    OBJ_BASE_CLASS = IronicObject


def obj_to_primitive(obj):
    """Recursively turn an object into a python primitive.

    An IronicObject becomes a dict
    """
    if isinstance(obj, IronicObject):
        result = {}
        for key, value in obj.items():
            result[key] = obj_to_primitive(value)
        return result
    else:
        return obj
