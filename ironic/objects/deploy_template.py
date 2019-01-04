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
class DeployTemplate(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added 'extra' field
    VERSION = '1.1'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=False),
        'name': object_fields.StringField(nullable=False),
        'steps': object_fields.ListOfFlexibleDictsField(nullable=False),
        'extra': object_fields.FlexibleDictField(nullable=True),
    }

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a DeployTemplate record in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :raises: DeployTemplateDuplicateName if a deploy template with the same
            name exists.
        :raises: DeployTemplateAlreadyExists if a deploy template with the same
            UUID exists.
        """
        values = self.do_version_changes_for_db()
        db_template = self.dbapi.create_deploy_template(values)
        self._from_db_object(self._context, self, db_template)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this DeployTemplate.

        Column-wise updates will be made based on the result of
        self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context)
        :raises: DeployTemplateDuplicateName if a deploy template with the same
            name exists.
        :raises: DeployTemplateNotFound if the deploy template does not exist.
        """
        updates = self.do_version_changes_for_db()
        db_template = self.dbapi.update_deploy_template(self.uuid, updates)
        self._from_db_object(self._context, self, db_template)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    def destroy(self):
        """Delete the DeployTemplate from the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :raises: DeployTemplateNotFound if the deploy template no longer
            appears in the database.
        """
        self.dbapi.destroy_deploy_template(self.id)
        self.obj_reset_changes()

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, template_id):
        """Find a deploy template based on its integer ID.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :param template_id: The ID of a deploy template.
        :raises: DeployTemplateNotFound if the deploy template no longer
            appears in the database.
        :returns: a :class:`DeployTemplate` object.
        """
        db_template = cls.dbapi.get_deploy_template_by_id(template_id)
        template = cls._from_db_object(context, cls(), db_template)
        return template

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a deploy template based on its UUID.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :param uuid: The UUID of a deploy template.
        :raises: DeployTemplateNotFound if the deploy template no longer
            appears in the database.
        :returns: a :class:`DeployTemplate` object.
        """
        db_template = cls.dbapi.get_deploy_template_by_uuid(uuid)
        template = cls._from_db_object(context, cls(), db_template)
        return template

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_name(cls, context, name):
        """Find a deploy template based on its name.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :param name: The name of a deploy template.
        :raises: DeployTemplateNotFound if the deploy template no longer
            appears in the database.
        :returns: a :class:`DeployTemplate` object.
        """
        db_template = cls.dbapi.get_deploy_template_by_name(name)
        template = cls._from_db_object(context, cls(), db_template)
        return template

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None):
        """Return a list of DeployTemplate objects.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`DeployTemplate` objects.
        """
        db_templates = cls.dbapi.get_deploy_template_list(
            limit=limit, marker=marker, sort_key=sort_key, sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_templates)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_names(cls, context, names):
        """Return a list of DeployTemplate objects matching a set of names.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: DeployTemplate(context).
        :param names: a list of names to filter by.
        :returns: a list of :class:`DeployTemplate` objects.
        """
        db_templates = cls.dbapi.get_deploy_template_list_by_names(names)
        return cls._from_db_object_list(context, db_templates)

    def refresh(self, context=None):
        """Loads updates for this deploy template.

        Loads a deploy template with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded template column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: DeployTemplateNotFound if the deploy template no longer
            appears in the database.
        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()


@base.IronicObjectRegistry.register
class DeployTemplateCRUDNotification(notification.NotificationBase):
    """Notification emitted on deploy template API operations."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('DeployTemplateCRUDPayload')
    }


@base.IronicObjectRegistry.register
class DeployTemplateCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'created_at': ('deploy_template', 'created_at'),
        'extra': ('deploy_template', 'extra'),
        'name': ('deploy_template', 'name'),
        'steps': ('deploy_template', 'steps'),
        'updated_at': ('deploy_template', 'updated_at'),
        'uuid': ('deploy_template', 'uuid')
    }

    fields = {
        'created_at': object_fields.DateTimeField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'name': object_fields.StringField(nullable=False),
        'steps': object_fields.ListOfFlexibleDictsField(nullable=False),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, deploy_template, **kwargs):
        super(DeployTemplateCRUDPayload, self).__init__(**kwargs)
        self.populate_schema(deploy_template=deploy_template)
