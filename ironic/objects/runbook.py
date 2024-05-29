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

from oslo_versionedobjects import base as object_base

from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import notification


@base.IronicObjectRegistry.register
class Runbook(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=False),
        'name': object_fields.StringField(nullable=False),
        'steps': object_fields.ListOfFlexibleDictsField(nullable=False),
        'disable_ramdisk': object_fields.BooleanField(default=False),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'public': object_fields.BooleanField(default=False),
        'owner': object_fields.StringField(nullable=True),
    }

    def create(self, context=None):
        """Create a Runbook record in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :raises: RunbookDuplicateName if a runbook with the same
            name exists.
        :raises: RunbookAlreadyExists if a runbook with the same
            UUID exists.
        """
        values = self.do_version_changes_for_db()
        db_template = self.dbapi.create_runbook(values)
        self._from_db_object(self._context, self, db_template)

    def save(self, context=None):
        """Save updates to this Runbook.

        Column-wise updates will be made based on the result of
        self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context)
        :raises: RunbookDuplicateName if a runbook with the same
            name exists.
        :raises: RunbookNotFound if the runbook does not exist.
        """
        updates = self.do_version_changes_for_db()
        db_template = self.dbapi.update_runbook(self.uuid, updates)
        self._from_db_object(self._context, self, db_template)

    def destroy(self):
        """Delete the Runbook from the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :raises: RunbookNotFound if the runbook no longer
            appears in the database.
        """
        self.dbapi.destroy_runbook(self.id)
        self.obj_reset_changes()

    @classmethod
    def get_by_id(cls, context, runbook_id):
        """Find a runbook based on its integer ID.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :param runbook_id: The ID of a runbook.
        :raises: RunbookNotFound if the runbook no longer
            appears in the database.
        :returns: a :class:`Runbook` object.
        """
        db_template = cls.dbapi.get_runbook_by_id(runbook_id)
        template = cls._from_db_object(context, cls(), db_template)
        return template

    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a runbook based on its UUID.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :param uuid: The UUID of a runbook.
        :raises: RunbookNotFound if the runbook no longer
            appears in the database.
        :returns: a :class:`Runbook` object.
        """
        db_template = cls.dbapi.get_runbook_by_uuid(uuid)
        template = cls._from_db_object(context, cls(), db_template)
        return template

    @classmethod
    def get_by_name(cls, context, name):
        """Find a runbook based on its name.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :param name: The name of a runbook.
        :raises: RunbookNotFound if the runbook no longer
            appears in the database.
        :returns: a :class:`Runbook` object.
        """
        db_template = cls.dbapi.get_runbook_by_name(name)
        template = cls._from_db_object(context, cls(), db_template)
        return template

    @classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None, filters=None):
        """Return a list of Runbook objects.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param filters: Filters to apply.
        :returns: a list of :class:`Runbook` objects.
        """
        db_templates = cls.dbapi.get_runbook_list(limit=limit, marker=marker,
                                                  sort_key=sort_key,
                                                  sort_dir=sort_dir,
                                                  filters=filters)
        return cls._from_db_object_list(context, db_templates)

    @classmethod
    def list_by_names(cls, context, names):
        """Return a list of Runbook objects matching a set of names.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Runbook(context).
        :param names: a list of names to filter by.
        :returns: a list of :class:`Runbook` objects.
        """
        db_templates = cls.dbapi.get_runbook_list_by_names(names)
        return cls._from_db_object_list(context, db_templates)

    def refresh(self, context=None):
        """Loads updates for this runbook.

        Loads a runbook with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded template column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: RunbookNotFound if the runbook no longer
            appears in the database.
        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()


@base.IronicObjectRegistry.register
class RunbookCRUDNotification(notification.NotificationBase):
    """Notification emitted on runbook API operations."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('RunbookCRUDPayload')
    }


@base.IronicObjectRegistry.register
class RunbookCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'created_at': ('runbook', 'created_at'),
        'disable_ramdisk': ('runbook', 'disable_ramdisk'),
        'extra': ('runbook', 'extra'),
        'name': ('runbook', 'name'),
        'owner': ('runbook', 'owner'),
        'public': ('runbook', 'public'),
        'steps': ('runbook', 'steps'),
        'updated_at': ('runbook', 'updated_at'),
        'uuid': ('runbook', 'uuid')
    }

    fields = {
        'created_at': object_fields.DateTimeField(nullable=True),
        'disable_ramdisk': object_fields.BooleanField(default=False),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'name': object_fields.StringField(nullable=False),
        'owner': object_fields.StringField(nullable=True),
        'public': object_fields.BooleanField(default=False),
        'steps': object_fields.ListOfFlexibleDictsField(nullable=False),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, runbook, **kwargs):
        super(RunbookCRUDPayload, self).__init__(**kwargs)
        self.populate_schema(runbook=runbook)
