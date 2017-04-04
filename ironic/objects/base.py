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
import six

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

    @staticmethod
    def _from_db_object(obj, db_object):
        """Converts a database entity to a formal object.

        :param obj: An object of the class.
        :param db_object: A DB model of the object
        :return: The object of the class with the database entity added
        """

        for field in obj.fields:
            obj[field] = db_object[field]

        obj.obj_reset_changes()
        return obj

    @classmethod
    def _from_db_object_list(cls, context, db_objects):
        """Returns objects corresponding to database entities.

        Returns a list of formal objects of this class that correspond to
        the list of database entities.

        :param context: security context
        :param db_objects: A  list of DB models of the object
        :returns: A list of objects corresponding to the database entities
        """
        return [cls._from_db_object(cls(context), db_obj)
                for db_obj in db_objects]

    def _get_target_version(self):
        """Returns the target version for this object.

        If pinned, returns the version of this object corresponding to
        the pin. Otherwise, returns this (latest) version of the object.
        """
        pinned_version = None
        pin = CONF.pin_release_version
        if pin:
            version_manifest = versions.RELEASE_MAPPING[pin]['objects']
            pinned_version = version_manifest.get(self.obj_name())
        return pinned_version or self.__class__.VERSION


class IronicObjectSerializer(object_base.VersionedObjectSerializer):
    # Base class to use for object hydration
    OBJ_BASE_CLASS = IronicObject

    def serialize_entity(self, context, entity):
        if isinstance(entity, (tuple, list, set, dict)):
            entity = self._process_iterable(context, self.serialize_entity,
                                            entity)
        elif (hasattr(entity, 'obj_to_primitive')
              and callable(entity.obj_to_primitive)):
            target_version = entity._get_target_version()
            # NOTE(xek): If the version is pinned, target_version is an older
            # object version and entity's obj_make_compatible method is called
            # to backport the object before serialization.
            entity = entity.obj_to_primitive(target_version=target_version)
        elif not isinstance(entity, (bool, float, type, six.integer_types,
                                     six.string_types)) and entity:
            LOG.warning("Entity %s was not serialized.", str(entity))
        return entity
