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

from oslo_utils import strutils
from oslo_utils import uuidutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.common import utils
from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import notification


@base.IronicObjectRegistry.register
class Allocation(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'name': object_fields.StringField(nullable=True),
        'node_id': object_fields.IntegerField(nullable=True),
        'state': object_fields.StringField(nullable=True),
        'last_error': object_fields.StringField(nullable=True),
        'resource_class': object_fields.StringField(nullable=True),
        'traits': object_fields.ListOfStringsField(nullable=True),
        'candidate_nodes': object_fields.ListOfStringsField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'conductor_affinity': object_fields.IntegerField(nullable=True),
    }

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, allocation_ident):
        """Find an allocation by its ID, UUID or name.

        :param allocation_ident: The ID, UUID or name of an allocation.
        :param context: Security context
        :returns: An :class:`Allocation` object.
        :raises: InvalidIdentity

        """
        if strutils.is_int_like(allocation_ident):
            return cls.get_by_id(context, allocation_ident)
        elif uuidutils.is_uuid_like(allocation_ident):
            return cls.get_by_uuid(context, allocation_ident)
        elif utils.is_valid_logical_name(allocation_ident):
            return cls.get_by_name(context, allocation_ident)
        else:
            raise exception.InvalidIdentity(identity=allocation_ident)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, allocation_id):
        """Find an allocation by its integer ID.

        :param cls: the :class:`Allocation`
        :param context: Security context
        :param allocation_id: The ID of an allocation.
        :returns: An :class:`Allocation` object.
        :raises: AllocationNotFound

        """
        db_allocation = cls.dbapi.get_allocation_by_id(allocation_id)
        allocation = cls._from_db_object(context, cls(), db_allocation)
        return allocation

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find an allocation by its UUID.

        :param cls: the :class:`Allocation`
        :param context: Security context
        :param uuid: The UUID of an allocation.
        :returns: An :class:`Allocation` object.
        :raises: AllocationNotFound

        """
        db_allocation = cls.dbapi.get_allocation_by_uuid(uuid)
        allocation = cls._from_db_object(context, cls(), db_allocation)
        return allocation

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_name(cls, context, name):
        """Find an allocation based by its name.

        :param cls: the :class:`Allocation`
        :param context: Security context
        :param name: The name of an allocation.
        :returns: An :class:`Allocation` object.
        :raises: AllocationNotFound

        """
        db_allocation = cls.dbapi.get_allocation_by_name(name)
        allocation = cls._from_db_object(context, cls(), db_allocation)
        return allocation

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, filters=None, limit=None, marker=None,
             sort_key=None, sort_dir=None):
        """Return a list of Allocation objects.

        :param cls: the :class:`Allocation`
        :param context: Security context.
        :param filters: Filters to apply.
        :param limit: Maximum number of resources to return in a single result.
        :param marker: Pagination marker for large data sets.
        :param sort_key: Column to sort results by.
        :param sort_dir: Direction to sort. "asc" or "desc".
        :returns: A list of :class:`Allocation` object.
        :raises: InvalidParameterValue

        """
        db_allocations = cls.dbapi.get_allocation_list(filters=filters,
                                                       limit=limit,
                                                       marker=marker,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_allocations)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a Allocation record in the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Allocation(context)
        :raises: AllocationDuplicateName, AllocationAlreadyExists

        """
        values = self.do_version_changes_for_db()
        db_allocation = self.dbapi.create_allocation(values)
        self._from_db_object(self._context, self, db_allocation)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the Allocation from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Allocation(context)
        :raises: AllocationNotFound

        """
        self.dbapi.destroy_allocation(self.uuid)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this Allocation.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Allocation(context)
        :raises: AllocationNotFound, AllocationDuplicateName

        """
        updates = self.do_version_changes_for_db()
        updated_allocation = self.dbapi.update_allocation(self.uuid, updates)
        self._from_db_object(self._context, self, updated_allocation)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Loads updates for this Allocation.

        Loads an allocation with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded allocation column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Allocation(context)
        :raises: AllocationNotFound

        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()


@base.IronicObjectRegistry.register
class AllocationCRUDNotification(notification.NotificationBase):
    """Notification when ironic creates, updates or deletes an allocation."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('AllocationCRUDPayload')
    }


@base.IronicObjectRegistry.register
class AllocationCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'candidate_nodes': ('allocation', 'candidate_nodes'),
        'created_at': ('allocation', 'created_at'),
        'extra': ('allocation', 'extra'),
        'last_error': ('allocation', 'last_error'),
        'name': ('allocation', 'name'),
        'resource_class': ('allocation', 'resource_class'),
        'state': ('allocation', 'state'),
        'traits': ('allocation', 'traits'),
        'updated_at': ('allocation', 'updated_at'),
        'uuid': ('allocation', 'uuid')
    }

    fields = {
        'uuid': object_fields.UUIDField(nullable=True),
        'name': object_fields.StringField(nullable=True),
        'node_uuid': object_fields.StringField(nullable=True),
        'state': object_fields.StringField(nullable=True),
        'last_error': object_fields.StringField(nullable=True),
        'resource_class': object_fields.StringField(nullable=True),
        'traits': object_fields.ListOfStringsField(nullable=True),
        'candidate_nodes': object_fields.ListOfStringsField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
    }

    def __init__(self, allocation, node_uuid=None):
        super(AllocationCRUDPayload, self).__init__(node_uuid=node_uuid)
        self.populate_schema(allocation=allocation)
