#    Copyright (c) 2016 Hitachi, Ltd.
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

from oslo_utils import strutils
from oslo_utils import uuidutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import notification


@base.IronicObjectRegistry.register
class VolumeTarget(base.IronicObject,
                   object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'node_id': object_fields.IntegerField(nullable=True),
        'volume_type': object_fields.StringField(nullable=True),
        'properties': object_fields.FlexibleDictField(nullable=True),
        'boot_index': object_fields.IntegerField(nullable=True),
        'volume_id': object_fields.StringField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
    }

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, ident):
        """Find a volume target based on its ID or UUID.

        :param context: security context
        :param ident: the database primary key ID *or* the UUID of a volume
                      target
        :returns: a :class:`VolumeTarget` object
        :raises: InvalidIdentity if ident is neither an integer ID nor a UUID
        :raises: VolumeTargetNotFound if no volume target with this ident
                 exists
        """
        if strutils.is_int_like(ident):
            return cls.get_by_id(context, ident)
        elif uuidutils.is_uuid_like(ident):
            return cls.get_by_uuid(context, ident)
        else:
            raise exception.InvalidIdentity(identity=ident)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, db_id):
        """Find a volume target based on its database ID.

        :param cls: the :class:`VolumeTarget`
        :param context: security context
        :param db_id: the database primary key (integer) ID of a volume target
        :returns: a :class:`VolumeTarget` object
        :raises: VolumeTargetNotFound if no volume target with this ID exists
        """
        db_target = cls.dbapi.get_volume_target_by_id(db_id)
        target = cls._from_db_object(context, cls(), db_target)
        return target

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a volume target based on its UUID.

        :param cls: the :class:`VolumeTarget`
        :param context: security context
        :param uuid: the UUID of a volume target
        :returns: a :class:`VolumeTarget` object
        :raises: VolumeTargetNotFound if no volume target with this UUID exists
        """
        db_target = cls.dbapi.get_volume_target_by_uuid(uuid)
        target = cls._from_db_object(context, cls(), db_target)
        return target

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None,
             sort_key=None, sort_dir=None):
        """Return a list of VolumeTarget objects.

        :param context: security context
        :param limit: maximum number of resources to return in a single result
        :param marker: pagination marker for large data sets
        :param sort_key: column to sort results by
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`VolumeTarget` objects
        :raises: InvalidParameterValue if sort_key does not exist
        """
        db_targets = cls.dbapi.get_volume_target_list(limit=limit,
                                                      marker=marker,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_targets)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_node_id(cls, context, node_id, limit=None, marker=None,
                        sort_key=None, sort_dir=None):
        """Return a list of VolumeTarget objects related to a given node ID.

        :param context: security context
        :param node_id: the integer ID of the node
        :param limit: maximum number of resources to return in a single result
        :param marker: pagination marker for large data sets
        :param sort_key: column to sort results by
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`VolumeTarget` objects
        :raises: InvalidParameterValue if sort_key does not exist
        """
        db_targets = cls.dbapi.get_volume_targets_by_node_id(
            node_id,
            limit=limit,
            marker=marker,
            sort_key=sort_key,
            sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_targets)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_volume_id(cls, context, volume_id, limit=None, marker=None,
                          sort_key=None, sort_dir=None):
        """Return a list of VolumeTarget objects related to a given volume ID.

        :param context: security context
        :param volume_id: the UUID of the volume
        :param limit: maximum number of volume targets to return in a
                      single result
        :param marker: pagination marker for large data sets
        :param sort_key: column to sort results by
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`VolumeTarget` objects
        :raises: InvalidParameterValue if sort_key does not exist
        """
        db_targets = cls.dbapi.get_volume_targets_by_volume_id(
            volume_id,
            limit=limit,
            marker=marker,
            sort_key=sort_key,
            sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_targets)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a VolumeTarget record in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: VolumeTarget(context).
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same node ID and boot index
        :raises: VolumeTargetAlreadyExists if a volume target with the same
                 UUID exists
        """
        values = self.do_version_changes_for_db()
        db_target = self.dbapi.create_volume_target(values)
        self._from_db_object(self._context, self, db_target)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the VolumeTarget from the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: VolumeTarget(context).
        :raises: VolumeTargetNotFound if the volume target cannot be found
        """
        self.dbapi.destroy_volume_target(self.uuid)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this VolumeTarget.

        Updates will be made column by column based on the result
        of self.do_version_changes_for_db().

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: VolumeTarget(context).
        :raises: InvalidParameterValue if the UUID is being changed
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same node ID and boot index values
        :raises: VolumeTargetNotFound if the volume target cannot be found
        """
        updates = self.do_version_changes_for_db()
        updated_target = self.dbapi.update_volume_target(self.uuid, updates)
        self._from_db_object(self._context, self, updated_target)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Loads updates for this VolumeTarget.

        Load a volume target with the same UUID from the database
        and check for updated attributes. If there are any updates,
        they are applied from the loaded volume target, column by column.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: VolumeTarget(context).
        :raises: VolumeTargetNotFound if the volume target cannot be found
        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()


@base.IronicObjectRegistry.register
class VolumeTargetCRUDNotification(notification.NotificationBase):
    """Notification emitted at CRUD of a volume target."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('VolumeTargetCRUDPayload')
    }


@base.IronicObjectRegistry.register
class VolumeTargetCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial Version
    VERSION = '1.0'

    SCHEMA = {
        'boot_index': ('target', 'boot_index'),
        'extra': ('target', 'extra'),
        'properties': ('target', 'properties'),
        'volume_id': ('target', 'volume_id'),
        'volume_type': ('target', 'volume_type'),
        'created_at': ('target', 'created_at'),
        'updated_at': ('target', 'updated_at'),
        'uuid': ('target', 'uuid'),
    }

    fields = {
        'boot_index': object_fields.IntegerField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'node_uuid': object_fields.UUIDField(),
        'properties': object_fields.FlexibleDictField(nullable=True),
        'volume_id': object_fields.StringField(nullable=True),
        'volume_type': object_fields.StringField(nullable=True),
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField(),
    }

    def __init__(self, target, node_uuid):
        super(VolumeTargetCRUDPayload, self).__init__(node_uuid=node_uuid)
        self.populate_schema(target=target)
