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

import collections
import copy

from oslo_context import context
from oslo_log import log as logging
from oslo_utils import versionutils
from oslo_versionedobjects import base as object_base
import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.objects import fields as object_fields
from ironic.objects import utils as obj_utils


LOG = logging.getLogger('object')


def get_attrname(name):
    """Return the mangled name of the attribute's underlying storage."""
    return '_%s' % name


def make_class_properties(cls):
    # NOTE(danms/comstud): Inherit fields from super classes.
    # mro() returns the current class first and returns 'object' last, so
    # those can be skipped.  Also be careful to not overwrite any fields
    # that already exist.  And make sure each cls has its own copy of
    # fields and that it is not sharing the dict with a super class.
    cls.fields = dict(cls.fields)
    for supercls in cls.mro()[1:-1]:
        if not hasattr(supercls, 'fields'):
            continue
        for name, field in supercls.fields.items():
            if name not in cls.fields:
                cls.fields[name] = field
    for name, typefn in cls.fields.items():

        def getter(self, name=name):
            attrname = get_attrname(name)
            if not hasattr(self, attrname):
                self.obj_load_attr(name)
            return getattr(self, attrname)

        def setter(self, value, name=name, typefn=typefn):
            self._changed_fields.add(name)
            try:
                return setattr(self, get_attrname(name), typefn(value))
            except Exception:
                attr = "%s.%s" % (self.obj_name(), name)
                LOG.exception(_LE('Error setting %(attr)s'),
                              {'attr': attr})
                raise

        setattr(cls, name, property(getter, setter))


class IronicObjectMetaclass(type):
    """Metaclass that allows tracking of object classes."""

    # NOTE(danms): This is what controls whether object operations are
    # remoted. If this is not None, use it to remote things over RPC.
    indirection_api = None

    def __init__(cls, names, bases, dict_):
        if not hasattr(cls, '_obj_classes'):
            # This will be set in the 'IronicObject' class.
            cls._obj_classes = collections.defaultdict(list)
        else:
            # Add the subclass to IronicObject._obj_classes
            make_class_properties(cls)
            cls._obj_classes[cls.obj_name()].append(cls)


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
                    self[key] = self._attr_from_primitive(key, value)
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


@six.add_metaclass(IronicObjectMetaclass)
class IronicObject(object_base.VersionedObjectDictCompat):
    """Base class and object factory.

    This forms the base of all objects that can be remoted or instantiated
    via RPC. Simply defining a class that inherits from this base class
    will make it remotely instantiatable. Objects should implement the
    necessary "get" classmethod routines as well as "save" object methods
    as appropriate.
    """

    OBJ_SERIAL_NAMESPACE = 'ironic_object'
    # Version of this object (see rules above check_object_version())
    VERSION = '1.0'

    # The fields present in this object as key:typefn pairs. For example:
    #
    # fields = { 'foo': int,
    #            'bar': str,
    #            'baz': lambda x: str(x).ljust(8),
    #          }
    #
    # NOTE(danms): The base IronicObject class' fields will be inherited
    # by subclasses, but that is a special case. Objects inheriting from
    # other objects will not receive this merging of fields contents.
    fields = {
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
    }
    obj_extra_fields = []

    _attr_created_at_from_primitive = obj_utils.dt_deserializer
    _attr_updated_at_from_primitive = obj_utils.dt_deserializer
    _attr_created_at_to_primitive = obj_utils.dt_serializer('created_at')
    _attr_updated_at_to_primitive = obj_utils.dt_serializer('updated_at')

    def __init__(self, context, **kwargs):
        self._changed_fields = set()
        self._context = context
        self.update(kwargs)

    @classmethod
    def obj_name(cls):
        """Get canonical object name.

        This object name will be used over the wire for remote hydration.
        """
        return cls.__name__

    @classmethod
    def obj_class_from_name(cls, objname, objver):
        """Returns a class from the registry based on a name and version."""
        if objname not in cls._obj_classes:
            LOG.error(_LE('Unable to instantiate unregistered object type '
                          '%(objtype)s'), dict(objtype=objname))
            raise exception.UnsupportedObjectError(objtype=objname)

        latest = None
        compatible_match = None
        for objclass in cls._obj_classes[objname]:
            if objclass.VERSION == objver:
                return objclass

            version_bits = tuple([int(x) for x in objclass.VERSION.split(".")])
            if latest is None:
                latest = version_bits
            elif latest < version_bits:
                latest = version_bits

            if versionutils.is_compatible(objver, objclass.VERSION):
                compatible_match = objclass

        if compatible_match:
            return compatible_match

        latest_ver = '%i.%i' % latest
        raise exception.IncompatibleObjectVersion(objname=objname,
                                                  objver=objver,
                                                  supported=latest_ver)

    def _attr_from_primitive(self, attribute, value):
        """Attribute deserialization dispatcher.

        This calls self._attr_foo_from_primitive(value) for an attribute
        foo with value, if it exists, otherwise it assumes the value
        is suitable for the attribute's setter method.
        """
        handler = '_attr_%s_from_primitive' % attribute
        if hasattr(self, handler):
            return getattr(self, handler)(value)
        return value

    @classmethod
    def _obj_from_primitive(cls, context, objver, primitive):
        self = cls(context)
        self.VERSION = objver
        objdata = primitive['ironic_object.data']
        changes = primitive.get('ironic_object.changes', [])
        for name in self.fields:
            if name in objdata:
                setattr(self, name,
                        self._attr_from_primitive(name, objdata[name]))
        self._changed_fields = set([x for x in changes if x in self.fields])
        return self

    @classmethod
    def obj_from_primitive(cls, primitive, context=None):
        """Simple base-case hydration.

        This calls self._attr_from_primitive() for each item in fields.
        """
        if primitive['ironic_object.namespace'] != 'ironic':
            # NOTE(danms): We don't do anything with this now, but it's
            # there for "the future"
            raise exception.UnsupportedObjectError(
                objtype='%s.%s' % (primitive['ironic_object.namespace'],
                                   primitive['ironic_object.name']))
        objname = primitive['ironic_object.name']
        objver = primitive['ironic_object.version']
        objclass = cls.obj_class_from_name(objname, objver)
        return objclass._obj_from_primitive(context, objver, primitive)

    def __deepcopy__(self, memo):
        """Efficiently make a deep copy of this object."""

        # NOTE(danms): A naive deepcopy would copy more than we need,
        # and since we have knowledge of the volatile bits of the
        # object, we can be smarter here. Also, nested entities within
        # some objects may be uncopyable, so we can avoid those sorts
        # of issues by copying only our field data.

        nobj = self.__class__(self._context)
        for name in self.fields:
            if self.obj_attr_is_set(name):
                nval = copy.deepcopy(getattr(self, name), memo)
                setattr(nobj, name, nval)
        nobj._changed_fields = set(self._changed_fields)
        return nobj

    def obj_clone(self):
        """Create a copy."""
        return copy.deepcopy(self)

    def _attr_to_primitive(self, attribute):
        """Attribute serialization dispatcher.

        This calls self._attr_foo_to_primitive() for an attribute foo,
        if it exists, otherwise it assumes the attribute itself is
        primitive-enough to be sent over the RPC wire.
        """
        handler = '_attr_%s_to_primitive' % attribute
        if hasattr(self, handler):
            return getattr(self, handler)()
        else:
            return getattr(self, attribute)

    def obj_to_primitive(self):
        """Simple base-case dehydration.

        This calls self._attr_to_primitive() for each item in fields.
        """
        primitive = dict()
        for name in self.fields:
            if hasattr(self, get_attrname(name)):
                primitive[name] = self._attr_to_primitive(name)
        obj = {'ironic_object.name': self.obj_name(),
               'ironic_object.namespace': 'ironic',
               'ironic_object.version': self.VERSION,
               'ironic_object.data': primitive}
        if self.obj_what_changed():
            obj['ironic_object.changes'] = list(self.obj_what_changed())
        return obj

    def obj_load_attr(self, attrname):
        """Load an additional attribute from the real object.

        This should use self._conductor, and cache any data that might
        be useful for future load operations.
        """
        raise NotImplementedError(
            _("Cannot load '%(attrname)s' in the base class") %
            {'attrname': attrname})

    def save(self, context):
        """Save the changed fields back to the store.

        This is optional for subclasses, but is presented here in the base
        class for consistency among those that do.
        """
        raise NotImplementedError(_("Cannot save anything in the base class"))

    def obj_get_changes(self):
        """Returns a dict of changed fields and their new values."""
        changes = {}
        for key in self.obj_what_changed():
            changes[key] = self[key]
        return changes

    def obj_what_changed(self):
        """Returns a set of fields that have been modified."""
        return self._changed_fields

    def obj_reset_changes(self, fields=None):
        """Reset the list of fields that have been changed.

        Note that this is NOT "revert to previous values"
        """
        if fields:
            self._changed_fields -= set(fields)
        else:
            self._changed_fields.clear()

    def obj_attr_is_set(self, attrname):
        """Test object to see if attrname is present.

        Returns True if the named attribute has a value set, or
        False if not. Raises AttributeError if attrname is not
        a valid attribute for this object.
        """
        if attrname not in self.obj_fields:
            raise AttributeError(
                _("%(objname)s object has no attribute '%(attrname)s'") %
                {'objname': self.obj_name(), 'attrname': attrname})
        return hasattr(self, get_attrname(attrname))

    @property
    def obj_fields(self):
        return list(self.fields) + self.obj_extra_fields

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
            if (hasattr(self, get_attrname(field)) and
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
