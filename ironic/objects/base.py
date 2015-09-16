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

from oslo_log import log as logging
from oslo_versionedobjects import base as object_base

from ironic.objects import fields as object_fields


LOG = logging.getLogger('object')


class IronicObjectRegistry(object_base.VersionedObjectRegistry):
    pass


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


class IronicObjectIndirectionAPI(object_base.VersionedObjectIndirectionAPI):
    def __init__(self):
        super(IronicObjectIndirectionAPI, self).__init__()
        # FIXME(xek): importing here due to a cyclical import error
        from ironic.conductor import rpcapi as conductor_api
        self._conductor = conductor_api.ConductorAPI()

    def object_action(self, context, objinst, objmethod, args, kwargs):
        return self._conductor.object_action(context, objinst, objmethod,
                                             args, kwargs)

    def object_class_action(self, context, objname, objmethod, objver,
                            args, kwargs):
        # NOTE(xek): This method is implemented for compatibility with
        # oslo.versionedobjects 0.10.0 and older. It will be replaced by
        # object_class_action_versions.
        versions = object_base.obj_tree_get_versions(objname)
        return self.object_class_action_versions(
            context, objname, objmethod, versions, args, kwargs)

    def object_class_action_versions(self, context, objname, objmethod,
                                     object_versions, args, kwargs):
        return self._conductor.object_class_action_versions(
            context, objname, objmethod, object_versions, args, kwargs)

    def object_backport_versions(self, context, objinst, object_versions):
        return self._conductor.object_backport_versions(context, objinst,
                                                        object_versions)


class IronicObjectSerializer(object_base.VersionedObjectSerializer):
    # Base class to use for object hydration
    OBJ_BASE_CLASS = IronicObject
