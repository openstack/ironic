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

from oslo_log import log
from oslo_utils import versionutils
from oslo_versionedobjects import base as object_base
from oslo_versionedobjects import exception as ovo_exception

from ironic.common import release_mappings as versions
from ironic.conf import CONF
from ironic import objects
from ironic.objects import fields as object_fields

LOG = log.getLogger(__name__)


def max_version(versions):
    """Return the maximum version in the list.

    :param versions: a list of (string) versions; assumed to have at
                     least one entry
    :returns: the maximum version (string)
    """
    if len(versions) == 1:
        return versions[0]

    int_versions = []
    for v in versions:
        int_versions.append(versionutils.convert_version_to_int(v))
    max_val = max(int_versions)
    ind = int_versions.index(max_val)
    return versions[ind]


class IronicObjectRegistry(object_base.VersionedObjectRegistry):
    def registration_hook(self, cls, index):
        # NOTE(jroll): blatantly stolen from nova
        # NOTE(danms): This is called when an object is registered,
        # and is responsible for maintaining ironic.objects.$OBJECT
        # as the highest-versioned implementation of a given object.
        version = versionutils.convert_version_to_tuple(cls.VERSION)
        if not hasattr(objects, cls.obj_name()):
            setattr(objects, cls.obj_name(), cls)
        else:
            cur_version = versionutils.convert_version_to_tuple(
                getattr(objects, cls.obj_name()).VERSION)
            if version >= cur_version:
                setattr(objects, cls.obj_name(), cls)


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
        """Return the object represented as a dict.

        The returned object is JSON-serialisable.
        """

        def _attr_as_dict(field):
            """Return an attribute as a dict, handling nested objects."""
            attr = getattr(self, field)
            if isinstance(attr, IronicObject):
                attr = attr.as_dict()
            return attr

        return dict((k, _attr_as_dict(k))
                    for k in self.fields
                    if self.obj_attr_is_set(k))

    def obj_refresh(self, loaded_object):
        """Applies updates for objects that inherit from base.IronicObject.

        Checks for updated attributes in an object. Updates are applied from
        the loaded object column by column in comparison with the current
        object.
        """
        for field in self.fields:
            if (self.obj_attr_is_set(field)
                    and self[field] != loaded_object[field]):
                self[field] = loaded_object[field]

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Subclasses should redefine this method, to do the conversion of the
        object to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        The remove_unavailable_fields flag is used to distinguish these two
        cases:

        1) For serialization/deserialization, we need to remove the unavailable
           fields, because the service receiving the object may not know about
           these fields. remove_unavailable_fields is set to True in this case.

        2) For DB interactions, we need to set the unavailable fields to their
           appropriate values so that these fields are saved in the DB. (If
           they are not set, the VersionedObject magic will not know to
           save/update them to the DB.) remove_unavailable_fields is set to
           False in this case.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """
        pass

    def convert_to_version(self, target_version,
                           remove_unavailable_fields=True):
        """Convert this object to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        The remove_unavailable_fields flag is used to distinguish these two
        cases:

        1) For serialization/deserialization, we need to remove the unavailable
           fields, because the service receiving the object may not know about
           these fields. remove_unavailable_fields is set to True in this case.

        2) For DB interactions, we need to set the unavailable fields to their
           appropriate values so that these fields are saved in the DB. (If
           they are not set, the VersionedObject magic will not know to
           save/update them to the DB.) remove_unavailable_fields is set to
           False in this case.

        _convert_to_version() does the actual work.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """
        if self.VERSION != target_version:
            self._convert_to_version(
                target_version,
                remove_unavailable_fields=remove_unavailable_fields)
            if remove_unavailable_fields:
                # NOTE(rloo): We changed the object, but don't keep track of
                # any of these changes, since it is inaccurate anyway (because
                # it doesn't keep track of any 'changed' unavailable fields).
                self.obj_reset_changes()

        # NOTE(rloo): self.__class__.VERSION is the latest version that
        # is supported by this service. self.VERSION is the version of
        # this object instance -- it may get set via e.g. the
        # serialization or deserialization process, or here.
        if (self.__class__.VERSION != target_version
            or self.VERSION != self.__class__.VERSION):
            self.VERSION = target_version

    @classmethod
    def get_target_version(cls):
        """Returns the target version for this object.

        This is the version in which the object should be manipulated, e.g.
        sent over the wire via RPC or saved in the DB.

        :returns: if pinned, returns the version of this object corresponding
                  to the pin. Otherwise, returns the version of the object.
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        pin = CONF.pin_release_version
        if not pin:
            return cls.VERSION

        version_manifest = versions.RELEASE_MAPPING[pin]['objects']
        pinned_versions = version_manifest.get(cls.obj_name())
        if pinned_versions:
            pinned_version = max_version(pinned_versions)
            if not versionutils.is_compatible(pinned_version,
                                              cls.VERSION):
                LOG.error(
                    'For object "%(objname)s", the target version '
                    '"%(target)s" is not compatible with its supported '
                    'version "%(support)s". The value ("%(pin)s") of the '
                    '"pin_release_version" configuration option may be '
                    'incorrect.',
                    {'objname': cls.obj_name(), 'target': pinned_version,
                     'support': cls.VERSION, 'pin': pin})
                raise ovo_exception.IncompatibleObjectVersion(
                    objname=cls.obj_name(), objver=pinned_version,
                    supported=cls.VERSION)
            return pinned_version

        return cls.VERSION

    @classmethod
    def supports_version(cls, version):
        """Return whether this object supports a particular version.

        Check the requested version against the object's target version. The
        target version may not be the latest version during an upgrade, when
        object versions are pinned.

        :param version: A tuple representing the version to check
        :returns: Whether the version is supported
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        target_version = cls.get_target_version()
        target_version = versionutils.convert_version_to_tuple(target_version)
        return target_version >= version

    def _set_from_db_object(self, context, db_object, fields=None):
        """Sets object fields.

        :param context: security context
        :param db_object: A DB entity of the object
        :param fields: list of fields to set on obj from values from db_object.
        """
        fields = fields or self.fields
        for field in fields:
            setattr(self, field, db_object[field])

    @staticmethod
    def _from_db_object(context, obj, db_object, fields=None):
        """Converts a database entity to a formal object.

        This always converts the database entity to the latest version
        of the object. Note that the latest version is available at
        object.__class__.VERSION. object.VERSION is the version of this
        particular object instance; it is possible that it is not the latest
        version.

        :param context: security context
        :param obj: An object of the class.
        :param db_object: A DB entity of the object
        :param fields: list of fields to set on obj from values from db_object.
        :return: The object of the class with the database entity added
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        objname = obj.obj_name()
        db_version = db_object['version']

        if not versionutils.is_compatible(db_version, obj.__class__.VERSION):
            raise ovo_exception.IncompatibleObjectVersion(
                objname=objname, objver=db_version,
                supported=obj.__class__.VERSION)

        obj._set_from_db_object(context, db_object, fields)

        obj._context = context

        # NOTE(rloo). We now have obj, a versioned object that corresponds to
        # its DB representation. A versioned object has an internal attribute
        # ._changed_fields; this is a list of changed fields -- used, e.g.,
        # when saving the object to the DB (only those changed fields are
        # saved to the DB). The obj.obj_reset_changes() clears this list
        # since we didn't actually make any modifications to the object that
        # we want saved later.
        obj.obj_reset_changes()

        if db_version != obj.__class__.VERSION:
            # convert to the latest version
            obj.VERSION = db_version
            obj.convert_to_version(obj.__class__.VERSION,
                                   remove_unavailable_fields=False)

        return obj

    @classmethod
    def _from_db_object_list(cls, context, db_objects, fields=None):
        """Returns objects corresponding to database entities.

        Returns a list of formal objects of this class that correspond to
        the list of database entities.

        :param cls: the VersionedObject class of the desired object
        :param context: security context
        :param db_objects: A  list of DB models of the object
        :param fields: A list of field names to comprise lower level
                       objects.
        :returns: A list of objects corresponding to the database entities
        """
        return [cls._from_db_object(context, cls(), db_obj, fields=fields)
                for db_obj in db_objects]

    def do_version_changes_for_db(self):
        """Change the object to the version needed for the database.

        If needed, this changes the object (modifies object fields) to be in
        the correct version for saving to the database.

        The version used to save the object in the DB is determined as follows:

        * If the object is pinned, we save the object in the pinned version.
          Since it is pinned, we must not save in a newer version, in case
          a rolling upgrade is happening and some services are still using the
          older version of ironic, with no knowledge of this newer version.
        * If the object isn't pinned, we save the object in the latest version.

        Because the object may be converted to a different object version, this
        method must only be called just before saving the object to the DB.

        :returns: a dictionary of changed fields and their new values
                  (could be an empty dictionary). These are the fields/values
                  of the object that would be saved to the DB.
        """
        target_version = self.get_target_version()

        if target_version != self.VERSION:
            # Convert the object so we can save it in the target version.
            self.convert_to_version(target_version,
                                    remove_unavailable_fields=False)

        changes = self.obj_get_changes()
        # NOTE(rloo): Since this object doesn't keep track of the version that
        #             is saved in the DB and we don't want to make a DB call
        #             just to find out, we always update 'version' in the DB.
        changes['version'] = self.VERSION

        return changes


class IronicObjectListBase(object_base.ObjectListBase):

    def as_dict(self):
        """Return the object represented as a dict.

        The returned object is JSON-serialisable.
        """
        return {'objects': [obj.as_dict() for obj in self.objects]}


class IronicObjectSerializer(object_base.VersionedObjectSerializer):
    # Base class to use for object hydration
    OBJ_BASE_CLASS = IronicObject

    def __init__(self, is_server=False):
        """Initialization.

        :param is_server: True if the service using this Serializer is a
            server (i.e. an ironic-conductor). Default is False for clients
            (such as ironic-api).
        """
        super(IronicObjectSerializer, self).__init__()
        self.is_server = is_server

    def _process_object(self, context, objprim):
        """Process the object.

        This is called from within deserialize_entity(). Deserialization
        is done for any serialized entities from e.g. an RPC request; the
        deserialization process converts them to Objects.

        This converts any IronicObjects to be in their latest versions,
        so that internally, the services (ironic-api and ironic-conductor)
        always deal with objects in their latest versions.

        :param objprim: a serialized entity that represents an object
        :returns: the deserialized Object
        :raises ovo_exception.IncompatibleObjectVersion
        """
        obj = super(IronicObjectSerializer, self)._process_object(
            context, objprim)
        if isinstance(obj, IronicObject):
            if obj.VERSION != obj.__class__.VERSION:
                # NOTE(rloo): if deserializing at API (client) side,
                # we don't want any changes
                obj.convert_to_version(
                    obj.__class__.VERSION,
                    remove_unavailable_fields=not self.is_server)
        return obj

    def serialize_entity(self, context, entity):
        """Serialize the entity.

        This serializes the entity so that it can be sent over e.g. RPC.
        A serialized entity for an IronicObject is a dictionary with keys:
        'ironic_object.namespace', 'ironic_object.data', 'ironic_object.name',
        'ironic_object.version', and 'ironic_object.changes'.

        We assume that the client (ironic-API) is always talking to a
        server (ironic-conductor) that is running the same or a newer
        release than the client. The client doesn't need to downgrade
        any IronicObjects when sending them over RPC. The server, on
        the other hand, will need to do so if the server is pinned and
        the target version of an IronicObject is older than the latest
        version of that Object.

        (Internally, the services deal with the latest versions of objects
        so we know that these objects are always in the latest versions.)

        :param context: security context
        :param entity: the entity to be serialized; may be an IronicObject
        :returns: the serialized entity
        :raises: ovo_exception.IncompatibleObjectVersion (via
                 .get_target_version())
        """
        if self.is_server and isinstance(entity, IronicObject):
            target_version = entity.get_target_version()
            if target_version != entity.VERSION:
                # NOTE(xek): If the version is pinned, target_version is an
                # older object version. We need to backport/convert to target
                # version before serialization.
                entity.convert_to_version(target_version,
                                          remove_unavailable_fields=True)

        return super(IronicObjectSerializer, self).serialize_entity(
            context, entity)
