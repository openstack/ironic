# coding=utf-8
#
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
from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import notification


@base.IronicObjectRegistry.register
class Chassis(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add get() and get_by_id() and make get_by_uuid()
    #              only work with a uuid
    # Version 1.2: Add create() and destroy()
    # Version 1.3: Add list()
    VERSION = '1.3'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'description': object_fields.StringField(nullable=True),
    }

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, chassis_id):
        """Find a chassis based on its id or uuid and return a Chassis object.

        :param context: Security context
        :param chassis_id: the id *or* uuid of a chassis.
        :returns: a :class:`Chassis` object.
        """
        if strutils.is_int_like(chassis_id):
            return cls.get_by_id(context, chassis_id)
        elif uuidutils.is_uuid_like(chassis_id):
            return cls.get_by_uuid(context, chassis_id)
        else:
            raise exception.InvalidIdentity(identity=chassis_id)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, chassis_id):
        """Find a chassis based on its integer ID and return a Chassis object.

        :param cls: the :class:`Chassis`
        :param context: Security context
        :param chassis_id: the ID of a chassis.
        :returns: a :class:`Chassis` object.
        """
        db_chassis = cls.dbapi.get_chassis_by_id(chassis_id)
        chassis = cls._from_db_object(context, cls(), db_chassis)
        return chassis

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a chassis based on UUID and return a :class:`Chassis` object.

        :param cls: the :class:`Chassis`
        :param context: Security context
        :param uuid: the UUID of a chassis.
        :returns: a :class:`Chassis` object.
        """
        db_chassis = cls.dbapi.get_chassis_by_uuid(uuid)
        chassis = cls._from_db_object(context, cls(), db_chassis)
        return chassis

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None,
             sort_key=None, sort_dir=None):
        """Return a list of Chassis objects.

        :param cls: the :class:`Chassis`
        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`Chassis` object.

        """
        db_chassis = cls.dbapi.get_chassis_list(limit=limit,
                                                marker=marker,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_chassis)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a Chassis record in the DB.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        chassis before updates are made.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Chassis(context)

        """
        values = self.do_version_changes_for_db()
        db_chassis = self.dbapi.create_chassis(values)
        self._from_db_object(self._context, self, db_chassis)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the Chassis from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Chassis(context)
        """
        self.dbapi.destroy_chassis(self.uuid)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this Chassis.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Chassis(context)
        """
        updates = self.do_version_changes_for_db()
        updated_chassis = self.dbapi.update_chassis(self.uuid, updates)
        self._from_db_object(self._context, self, updated_chassis)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Loads and applies updates for this Chassis.

        Loads a :class:`Chassis` with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded chassis column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Chassis(context)
        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)


@base.IronicObjectRegistry.register
class ChassisCRUDNotification(notification.NotificationBase):
    """Notification emitted when ironic creates, updates, deletes a chassis."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('ChassisCRUDPayload')
    }


@base.IronicObjectRegistry.register
class ChassisCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'description': ('chassis', 'description'),
        'extra': ('chassis', 'extra'),
        'created_at': ('chassis', 'created_at'),
        'updated_at': ('chassis', 'updated_at'),
        'uuid': ('chassis', 'uuid')
    }

    fields = {
        'description': object_fields.StringField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, chassis, **kwargs):
        super(ChassisCRUDPayload, self).__init__(**kwargs)
        self.populate_schema(chassis=chassis)
