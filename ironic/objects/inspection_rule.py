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
class InspectionRule(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Relevant methods changed to be remotable methods.
    VERSION = '1.1'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=False),
        'priority': object_fields.IntegerField(default=0),
        'description': object_fields.StringField(nullable=True),
        'sensitive': object_fields.BooleanField(default=False),
        'phase': object_fields.StringField(nullable=True, default='main'),
        'scope': object_fields.StringField(nullable=True),
        'actions': object_fields.ListOfFlexibleDictsField(nullable=False),
        'conditions': object_fields.ListOfFlexibleDictsField(nullable=True),
    }

    @object_base.remotable
    def create(self, context=None):
        """Create a InspectionRule record in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: InspectionRule(context).
        :raises: InspectionRuleName if a inspection rule with the same
            name exists.
        :raises: InspectionRuleAlreadyExists if a inspection rule with the same
            UUID exists.
        """
        values = self.do_version_changes_for_db()
        db_rule = self.dbapi.create_inspection_rule(values)
        self._from_db_object(self._context, self, db_rule)

    @object_base.remotable
    def save(self, context=None):
        """Save updates to this InspectionRule.

        Column-wise updates will be made based on the result of
        self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: InspectionRule(context)
        :raises: InspectionRuleNotFound if the inspection rule does not exist.
        """
        updates = self.do_version_changes_for_db()
        db_rule = self.dbapi.update_inspection_rule(self.uuid, updates)
        self._from_db_object(self._context, self, db_rule)

    @object_base.remotable
    def destroy(self):
        """Delete the InspectionRule from the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api,
                        but, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: InspectionRule(context).
        :raises: InspectionRuleNotFound if the inspection_rule no longer
            appears in the database.
        """
        self.dbapi.destroy_inspection_rule(self.id)
        self.obj_reset_changes()

    @object_base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a inspection rule based on its UUID.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: InspectionRule(context).
        :param uuid: The UUID of a inspection rule.
        :raises: InspectionRuleNotFound if the inspection rule no longer
            appears in the database.
        :returns: a :class:`InspectionRule` object.
        """
        db_rule = cls.dbapi.get_inspection_rule_by_uuid(uuid)
        rule = cls._from_db_object(context, cls(), db_rule)
        return rule

    @object_base.remotable_classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None, filters=None):
        """Return a list of InspectionRule objects.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: InspectionRule(context).
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`InspectionRule` objects.
        """
        db_rules = cls.dbapi.get_inspection_rule_list(
            limit=limit, marker=marker, sort_key=sort_key, sort_dir=sort_dir,
            filters=filters)
        return cls._from_db_object_list(context, db_rules)

    @object_base.remotable
    def refresh(self, context=None):
        """Loads updates for this inspection rule.

        Loads a inspection rule with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded rule column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: InspectionRuleNotFound if the inspection rule no longer
            appears in the database.
        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()


@base.IronicObjectRegistry.register
class InspectionRuleCRUDNotification(notification.NotificationBase):
    """Notification emitted on inspection rule API operations."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('InspectionRuleCRUDPayload')
    }


@base.IronicObjectRegistry.register
class InspectionRuleCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'created_at': ('inspection_rule', 'created_at'),
        'description': ('inspection_rule', 'description'),
        'phase': ('inspection_rule', 'phase'),
        'priority': ('inspection_rule', 'priority'),
        'scope': ('inspection_rule', 'scope'),
        'sensitive': ('inspection_rule', 'sensitive'),
        'actions': ('inspection_rule', 'actions'),
        'conditions': ('inspection_rule', 'conditions'),
        'updated_at': ('inspection_rule', 'updated_at'),
        'uuid': ('inspection_rule', 'uuid')
    }

    fields = {
        'created_at': object_fields.DateTimeField(nullable=True),
        'description': object_fields.StringField(nullable=True),
        'phase': object_fields.StringField(nullable=True, default='main'),
        'priority': object_fields.IntegerField(default=0),
        'scope': object_fields.StringField(nullable=True),
        'sensitive': object_fields.BooleanField(default=False),
        'actions': object_fields.ListOfFlexibleDictsField(nullable=False),
        'conditions': object_fields.ListOfFlexibleDictsField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, inspection_rule, **kwargs):
        super(InspectionRuleCRUDPayload, self).__init__(**kwargs)
        self.populate_schema(inspection_rule=inspection_rule)
