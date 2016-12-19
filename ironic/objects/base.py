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

    def _convert_to_version(self, target_version):
        """Convert to the target version.

        Subclasses should redefine this method, to do the conversion
        of the object to the specified version. As a result of any
        conversion, the object changes (self.obj_what_changed()) should
        be retained.

        :param target_version: the desired version of the object
        """
        pass

    def convert_to_version(self, target_version):
        """Convert this object to the target version.

        _convert_to_version() does the actual work.

        :param target_version: the desired version of the object
        """
        self._convert_to_version(target_version)

        # NOTE(rloo): self.__class__.VERSION is the latest version that
        # is supported by this service. self.VERSION is the version of
        # this object instance -- it may get set via e.g. the
        # serialization or deserialization process, or here.
        if (self.__class__.VERSION != target_version or
            self.VERSION != self.__class__.VERSION):
            self.VERSION = target_version

    def get_target_version(self):
        """Returns the target version for this object.

        This is the version in which the object should be manipulated, e.g.
        sent over the wire via RPC or saved in the DB.

        :returns: if pinned, returns the version of this object corresponding
                  to the pin. Otherwise, returns the version of the object.
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        pin = CONF.pin_release_version
        if pin:
            version_manifest = versions.RELEASE_MAPPING[pin]['objects']
            pinned_version = version_manifest.get(self.obj_name())
            if pinned_version:
                if not versionutils.is_compatible(pinned_version,
                                                  self.__class__.VERSION):
                    LOG.error(
                        'For object "%(objname)s", the target version '
                        '"%(target)s" is not compatible with its supported '
                        'version "%(support)s". The value ("%(pin)s") of the '
                        '"pin_release_version" configuration option may be '
                        'incorrect.',
                        {'objname': self.obj_name(), 'target': pinned_version,
                         'support': self.__class__.VERSION, 'pin': pin})
                    raise ovo_exception.IncompatibleObjectVersion(
                        objname=self.obj_name(), objver=pinned_version,
                        supported=self.__class__.VERSION)
                return pinned_version

        return self.__class__.VERSION

    @staticmethod
    def _from_db_object(context, obj, db_object):
        """Converts a database entity to a formal object.

        This always converts the database entity to the latest version
        of the object. Note that the latest version is available at
        object.__class__.VERSION. object.VERSION is the version of this
        particular object instance; it is possible that it is not the latest
        version.

        :param context: security context
        :param obj: An object of the class.
        :param db_object: A DB entity of the object
        :return: The object of the class with the database entity added
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        objname = obj.obj_name()
        db_version = db_object['version']

        if db_version is None:
            # NOTE(rloo): This can only happen after we've updated the DB
            # tables to include the 'version' column but haven't saved the
            # object to the DB since the new column was added. This column is
            # added in the Pike cycle, so if the version isn't set, use the
            # version associated with the most recent release, i.e. '8.0'.
            # The objects and RPC versions haven't changed between '8.0' and
            # Ocata, which is why it is fine to use Ocata.
            # Furthermore, if this is a new object that did not exist in the
            # most recent release, we assume it is version 1.0.
            # TODO(rloo): This entire if clause can be deleted in Queens
            # since the dbsync online migration populates all the versions
            # and it must be run to completion before upgrading to Queens.
            db_version = versions.RELEASE_MAPPING['ocata']['objects'].get(
                objname, '1.0')

        if not versionutils.is_compatible(db_version, obj.__class__.VERSION):
            raise ovo_exception.IncompatibleObjectVersion(
                objname=objname, objver=db_version,
                supported=obj.__class__.VERSION)

        for field in obj.fields:
            obj[field] = db_object[field]

        obj._context = context
        obj.obj_reset_changes()

        if db_version != obj.__class__.VERSION:
            # convert to the latest version
            obj.convert_to_version(obj.__class__.VERSION)
            if obj.get_target_version() == db_version:
                # pinned, so no need to keep these changes (we'll end up
                # converting back to db_version if obj is saved)
                obj.obj_reset_changes()
            else:
                # keep these changes around because they are needed
                # when/if saving to the DB in the latest version
                pass

        return obj

    @classmethod
    def _from_db_object_list(cls, context, db_objects):
        """Returns objects corresponding to database entities.

        Returns a list of formal objects of this class that correspond to
        the list of database entities.

        :param cls: the VersionedObject class of the desired object
        :param context: security context
        :param db_objects: A  list of DB models of the object
        :returns: A list of objects corresponding to the database entities
        """
        return [cls._from_db_object(context, cls(), db_obj)
                for db_obj in db_objects]

    def do_version_changes_for_db(self):
        """Do any changes to the object before saving it in the DB.

        This determines which version of the object should be saved to the
        database, and if needed, updates the object (fields) to correspond to
        the desired version.

        The version used to save the object is determined as follows:

        * If the object is pinned, we save the object in the pinned version.
          Since it is pinned, we don't want to save in a newer version, in case
          a rolling upgrade is happening and some services are still using the
          older version of ironic, with no knowledge of this newer version.
        * If the object isn't pinned, we save the object in the latest version.

        Because the object may be converted to a different object version,
        this method should only be called just before saving the object to
        the DB.

        :returns: a dictionary of changed fields and their new values
                  (could be an empty dictionary).
        """
        target_version = self.get_target_version()

        if (target_version != self.VERSION):
            # Convert the object so we can save it in the target version.
            self.convert_to_version(target_version)
            db_version = target_version
        else:
            db_version = self.VERSION

        changes = self.obj_get_changes()
        # NOTE(rloo): Since this object doesn't keep track of the version that
        #             is saved in the DB and we don't want to make a DB call
        #             just to find out, we always update 'version' in the DB.
        changes['version'] = db_version

        return changes


class IronicObjectSerializer(object_base.VersionedObjectSerializer):
    # Base class to use for object hydration
    OBJ_BASE_CLASS = IronicObject

    def _process_object(self, context, objprim):
        """Process the object.

        This is called from within deserialize_entity(). Deserialization
        is done for any serialized entities from e.g. an RPC request; the
        deserialization process converts them to Objects.

        This converts any IronicObjects to be in their latest versions,
        so that the services (ironic-api and ironic-conductor) internally,
        always deal objects in their latest versions.

        :param objprim: a serialized entity that represents an object
        :returns: the deserialized Object
        :raises ovo_exception.IncompatibleObjectVersion
        """
        obj = super(IronicObjectSerializer, self)._process_object(
            context, objprim)
        if isinstance(obj, IronicObject):
            if obj.VERSION != obj.__class__.VERSION:
                obj.convert_to_version(obj.__class__.VERSION)
        return obj

    def serialize_entity(self, context, entity):
        """Serialize the entity.

        This serializes the entity so that it can be sent over e.g. RPC.
        A serialized entity for an IronicObject is a dictionary with keys:
        'ironic_object.namespace', 'ironic_object.data', 'ironic_object.name',
        'ironic_object.version', and 'ironic_object.changes'.

        For IronicObjects, if the service (ironic-api or ironic-conductor)
        is pinned, we want the object to be in the target/pinned version,
        which is not necessarily the latest version of the object.
        (Internally, the services deal with the latest versions of objects
        so we know that these objects are always in the latest versions.)

        :param context: security context
        :param entity: the entity to be serialized; may be an IronicObject
        :returns: the serialized entity
        :raises: ovo_exception.IncompatibleObjectVersion (via
                 .get_target_version())
        """
        if isinstance(entity, IronicObject):
            target_version = entity.get_target_version()
            if target_version != entity.VERSION:
                # NOTE(xek): If the version is pinned, target_version is an
                # older object version. We need to backport/convert to target
                # version before serialization.
                entity.convert_to_version(target_version)

        return super(IronicObjectSerializer, self).serialize_entity(
            context, entity)
