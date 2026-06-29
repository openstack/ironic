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
    # Version 1.1: Relevant methods changed to be remotable methods.
    # Version 1.2: Added description and traits fields.
    VERSION = '1.2'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=False),
        'name': object_fields.StringField(nullable=False),
        'description': object_fields.StringField(nullable=True),
        'steps': object_fields.ListOfFlexibleDictsField(nullable=False),
        'disable_ramdisk': object_fields.BooleanField(default=False),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'public': object_fields.BooleanField(default=False),
        'owner': object_fields.StringField(nullable=True),
        'traits': object_fields.ListOfStringsField(nullable=False,
                                                   default=[]),
    }

    def obj_make_compatible(self, primitive, target_version):
        """Make an object representation compatible with a target version.

        :param primitive: The result of self.obj_to_primitive().
        :param target_version: The version string of the target version.
        """
        target_version = object_base.SemanticVersion.parse(target_version)
        if target_version < object_base.SemanticVersion.parse('1.2'):
            # description and traits were added in 1.2
            primitive['versioned_object.data'].pop('description', None)
            primitive['versioned_object.data'].pop('traits', None)

    def _set_from_db_object(self, context, db_object, fields=None):
        """Set fields from a database object.

        Handles the traits field specially: the DB layer stores traits as
        RunbookTrait ORM objects in a relationship, but the versioned object
        represents them as a plain list of strings.
        """
        use_fields = set(fields or self.fields) - {'traits'}
        super(Runbook, self)._set_from_db_object(
            context, db_object, use_fields)
        if not fields or 'traits' in fields:
            self.traits = [t.trait for t in db_object['traits']]

    @object_base.remotable
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

    @object_base.remotable
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
        # Traits are managed separately via the traits API endpoints.
        updates.pop('traits', None)
        db_template = self.dbapi.update_runbook(self.uuid, updates)
        self._from_db_object(self._context, self, db_template)

    @object_base.remotable
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
    @object_base.remotable
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
    @object_base.remotable
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
    @object_base.remotable
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
    @object_base.remotable
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
    @object_base.remotable
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

    @object_base.remotable
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
class RunbookTrait(base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'runbook_id': object_fields.IntegerField(),
        'trait': object_fields.StringField(),
    }

    @object_base.remotable
    def create(self, context=None):
        """Create a RunbookTrait record in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        A context should be set when instantiating the
                        object, e.g.: RunbookTrait(context).
        :raises: RunbookNotFound if the runbook no longer appears in
            the database.
        """
        values = self.do_version_changes_for_db()
        db_trait = self.dbapi.add_runbook_trait(
            values['runbook_id'], values['trait'], values['version'])
        self._from_db_object(self._context, self, db_trait)

    @classmethod
    @object_base.remotable
    def destroy(cls, context, runbook_id, trait):
        """Delete the RunbookTrait from the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        A context should be set when instantiating the
                        object, e.g.: RunbookTrait(context).
        :param runbook_id: The id of a runbook.
        :param trait: A trait string.
        :raises: RunbookNotFound if the runbook no longer appears in
            the database.
        :raises: RunbookTraitNotFound if the trait is not found.
        """
        cls.dbapi.delete_runbook_trait(runbook_id, trait)

    @classmethod
    @object_base.remotable
    def exists(cls, context, runbook_id, trait):
        """Check whether a RunbookTrait exists in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        A context should be set when instantiating the
                        object, e.g.: RunbookTrait(context).
        :param runbook_id: The id of a runbook.
        :param trait: A trait string.
        :returns: True if the trait exists otherwise False.
        :raises: RunbookNotFound if the runbook no longer appears in
            the database.
        """
        return cls.dbapi.runbook_trait_exists(runbook_id, trait)


@base.IronicObjectRegistry.register
class RunbookTraitList(base.IronicObjectListBase, base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'objects': object_fields.ListOfObjectsField('RunbookTrait'),
    }

    @classmethod
    @object_base.remotable
    def get_by_runbook_id(cls, context, runbook_id):
        """Return all traits for the specified runbook.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        A context should be set when instantiating the
                        object, e.g.: RunbookTrait(context).
        :param runbook_id: The id of a runbook.
        :raises: RunbookNotFound if the runbook no longer appears in
            the database.
        """
        db_traits = cls.dbapi.get_runbook_traits_by_runbook_id(runbook_id)
        return object_base.obj_make_list(
            context, cls(), RunbookTrait, db_traits)

    @classmethod
    @object_base.remotable
    def create(cls, context, runbook_id, traits):
        """Replace all existing traits with the specified list.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        A context should be set when instantiating the
                        object, e.g.: RunbookTrait(context).
        :param runbook_id: The id of a runbook.
        :param traits: List of Strings; traits to set.
        :raises: RunbookNotFound if the runbook no longer appears in
            the database.
        """
        version = RunbookTrait.get_target_version()
        db_traits = cls.dbapi.set_runbook_traits(runbook_id, traits, version)
        return object_base.obj_make_list(
            context, cls(), RunbookTrait, db_traits)

    @classmethod
    @object_base.remotable
    def destroy(cls, context, runbook_id):
        """Delete all traits for the specified runbook.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        A context should be set when instantiating the
                        object, e.g.: RunbookTrait(context).
        :param runbook_id: The id of a runbook.
        :raises: RunbookNotFound if the runbook no longer appears in
            the database.
        """
        cls.dbapi.unset_runbook_traits(runbook_id)

    def get_trait_names(self):
        """Return a list of names of the traits in this list."""
        return [t.trait for t in self.objects]


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
    # Version 1.1: Added description and traits fields.
    VERSION = '1.1'

    SCHEMA = {
        'created_at': ('runbook', 'created_at'),
        'description': ('runbook', 'description'),
        'disable_ramdisk': ('runbook', 'disable_ramdisk'),
        'extra': ('runbook', 'extra'),
        'name': ('runbook', 'name'),
        'owner': ('runbook', 'owner'),
        'public': ('runbook', 'public'),
        'steps': ('runbook', 'steps'),
        'traits': ('runbook', 'traits'),
        'updated_at': ('runbook', 'updated_at'),
        'uuid': ('runbook', 'uuid')
    }

    fields = {
        'created_at': object_fields.DateTimeField(nullable=True),
        'description': object_fields.StringField(nullable=True),
        'disable_ramdisk': object_fields.BooleanField(default=False),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'name': object_fields.StringField(nullable=False),
        'owner': object_fields.StringField(nullable=True),
        'public': object_fields.BooleanField(default=False),
        'steps': object_fields.ListOfFlexibleDictsField(nullable=False),
        'traits': object_fields.ListOfStringsField(nullable=False,
                                                   default=[]),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, runbook, **kwargs):
        super(RunbookCRUDPayload, self).__init__(**kwargs)
        self.populate_schema(runbook=runbook)
