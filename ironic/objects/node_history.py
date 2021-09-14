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


@base.IronicObjectRegistry.register
class NodeHistory(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'conductor': object_fields.StringField(nullable=True),
        'event': object_fields.StringField(nullable=True),
        'user': object_fields.StringField(nullable=True),
        'node_id': object_fields.IntegerField(nullable=True),
        'event_type': object_fields.StringField(nullable=True),
        'severity': object_fields.StringField(nullable=True),
    }

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, history_ident):
        """Get a history based on its id or uuid.

        :param history_ident: The id or uuid of a history.
        :param context: Security context
        :returns: A :class:`NodeHistory` object.
        :raises: InvalidIdentity

        """
        if strutils.is_int_like(history_ident):
            return cls.get_by_id(context, history_ident)
        elif uuidutils.is_uuid_like(history_ident):
            return cls.get_by_uuid(context, history_ident)
        else:
            raise exception.InvalidIdentity(identity=history_ident)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, history_id):
        """Get a NodeHistory object by its integer ID.

        :param cls: the :class:`NodeHistory`
        :param context: Security context
        :param history_id: The ID of a history.
        :returns: A :class:`NodeHistory` object.
        :raises: NodeHistoryNotFound

        """
        db_history = cls.dbapi.get_node_history_by_id(history_id)
        history = cls._from_db_object(context, cls(), db_history)
        return history

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Get a NodeHistory object by its UUID.

        :param cls: the :class:`NodeHistory`
        :param context: Security context
        :param uuid: The UUID of a NodeHistory.
        :returns: A :class:`NodeHistory` object.
        :raises: NodeHistoryNotFound

        """
        db_history = cls.dbapi.get_node_history_by_uuid(uuid)
        history = cls._from_db_object(context, cls(), db_history)
        return history

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None):
        """Return a list of NodeHistory objects.

        :param cls: the :class:`NodeHistory`
        :param context: Security context.
        :param limit: Maximum number of resources to return in a single result.
        :param marker: Pagination marker for large data sets.
        :param sort_key: Column to sort results by.
        :param sort_dir: Direction to sort. "asc" or "desc".
        :returns: A list of :class:`NodeHistory` object.
        :raises: InvalidParameterValue

        """
        db_histories = cls.dbapi.get_node_history_list(limit=limit,
                                                       marker=marker,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_histories)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_node_id(cls, context, node_id, limit=None, marker=None,
                        sort_key=None, sort_dir=None):
        """Return a list of NodeHistory objects belongs to a given node ID.

        :param cls: the :class:`NodeHistory`
        :param context: Security context.
        :param node_id: The ID of the node.
        :param limit: Maximum number of resources to return in a single result.
        :param marker: Pagination marker for large data sets.
        :param sort_key: Column to sort results by.
        :param sort_dir: Direction to sort. "asc" or "desc".
        :returns: A list of :class:`NodeHistory` object.
        :raises: InvalidParameterValue

        """
        db_histories = cls.dbapi.get_node_history_by_node_id(
            node_id, limit=limit, marker=marker, sort_key=sort_key,
            sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_histories)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a NodeHistory record in the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: NodeHistory(context)
        """
        values = self.do_version_changes_for_db()
        db_history = self.dbapi.create_node_history(values)
        self._from_db_object(self._context, self, db_history)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the NodeHistory from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: NodeHistory(context)
        :raises: NodeHistoryNotFound
        """
        self.dbapi.destroy_node_history_by_uuid(self.uuid)
        self.obj_reset_changes()
