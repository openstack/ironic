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

from oslo_utils import versionutils
from oslo_versionedobjects import base as object_base

from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields


@base.IronicObjectRegistry.register
class BIOSSetting(base.IronicObject):
    # Version 1.0: Initial version
    # Version 1.1: Added registry
    VERSION = '1.1'

    dbapi = dbapi.get_instance()

    registry_fields = ('attribute_type', 'allowable_values', 'lower_bound',
                       'max_length', 'min_length', 'read_only',
                       'reset_required', 'unique', 'upper_bound')

    fields = {
        'node_id': object_fields.StringField(nullable=False),
        'name': object_fields.StringField(nullable=False),
        'value': object_fields.StringField(nullable=True),
        'attribute_type': object_fields.StringField(nullable=True),
        'allowable_values': object_fields.ListOfStringsField(
            nullable=True),
        'lower_bound': object_fields.IntegerField(nullable=True),
        'max_length': object_fields.IntegerField(nullable=True),
        'min_length': object_fields.IntegerField(nullable=True),
        'read_only': object_fields.BooleanField(nullable=True),
        'reset_required': object_fields.BooleanField(nullable=True),
        'unique': object_fields.BooleanField(nullable=True),
        'upper_bound': object_fields.IntegerField(nullable=True)
    }

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a BIOS Setting record in DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: BIOSSetting(context)
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingAlreadyExists if the setting record already exists.
        """
        values = self.do_version_changes_for_db()
        settings = {'name': values['name'], 'value': values['value']}
        for r in self.registry_fields:
            settings[r] = values.get(r)

        db_bios_setting = self.dbapi.create_bios_setting_list(
            values['node_id'], [settings], values['version'])
        self._from_db_object(self._context, self, db_bios_setting[0])

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save BIOS Setting update in DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: BIOSSetting(context)
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingNotFound if the bios setting name is not found.
        """
        values = self.do_version_changes_for_db()

        settings = {'name': values['name'], 'value': values['value']}
        for r in self.registry_fields:
            settings[r] = values.get(r)

        updated_bios_setting = self.dbapi.update_bios_setting_list(
            values['node_id'], [settings], values['version'])
        self._from_db_object(self._context, self, updated_bios_setting[0])

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, node_id, name):
        """Get a BIOS Setting based on its node_id and name.

        :param context: Security context.
        :param node_id: The node id.
        :param name: BIOS setting name to be retrieved.
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingNotFound if the bios setting name is not found.
        :returns: A :class:'BIOSSetting' object.
        """
        db_bios_setting = cls.dbapi.get_bios_setting(node_id, name)
        return cls._from_db_object(context, cls(), db_bios_setting)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def delete(cls, context, node_id, name):
        """Delete a BIOS Setting based on its node_id and name.

        :param context: Security context.
        :param node_id: The node id.
        :param name: BIOS setting name to be deleted.
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingNotFound if the bios setting name is not found.
        """
        cls.dbapi.delete_bios_setting_list(node_id, [name])

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        Version 1.74: remove registry field for unsupported versions if
            remove_unavailable_fields is True.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """
        target_version = versionutils.convert_version_to_tuple(target_version)

        for field in self.get_registry_fields():
            field_is_set = self.obj_attr_is_set(field)
            if target_version >= (1, 1):
                # target version supports the major/minor specified
                if not field_is_set:
                    # set it to its default value if it is not set
                    setattr(self, field, None)
            elif field_is_set:
                # target version does not support the field, and it is set
                if remove_unavailable_fields:
                    # (De)serialising: remove unavailable fields
                    delattr(self, field)
                elif self.registry:
                    setattr(self, field, None)


@base.IronicObjectRegistry.register
class BIOSSettingList(base.IronicObjectListBase, base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'objects': object_fields.ListOfObjectsField('BIOSSetting'),
    }

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def create(cls, context, node_id, settings):
        """Create a list of BIOS Setting records in DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: BIOSSetting(context)
        :param node_id: The node id.
        :param settings: A list of bios settings.
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingAlreadyExists if any of the setting records
            already exists.
        :return: A list of BIOSSetting objects.
        """
        version = BIOSSetting.get_target_version()
        db_setting_list = cls.dbapi.create_bios_setting_list(
            node_id, settings, version)
        return object_base.obj_make_list(
            context, cls(), BIOSSetting, db_setting_list)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def save(cls, context, node_id, settings):
        """Save a list of BIOS Setting updates in DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: BIOSSetting(context)
        :param node_id: The node id.
        :param settings: A list of bios settings.
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingNotFound if any of the bios setting names
            is not found.
        :return: A list of BIOSSetting objects.
        """
        version = BIOSSetting.get_target_version()
        updated_setting_list = cls.dbapi.update_bios_setting_list(
            node_id, settings, version)
        return object_base.obj_make_list(
            context, cls(), BIOSSetting, updated_setting_list)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def delete(cls, context, node_id, names):
        """Delete BIOS Settings based on node_id and names.

        :param context: Security context.
        :param node_id: The node id.
        :param names: List of BIOS setting names to be deleted.
        :raises: NodeNotFound if the node id is not found.
        :raises: BIOSSettingNotFound if any of BIOS setting fails to delete.
        """
        cls.dbapi.delete_bios_setting_list(node_id, names)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_node_id(cls, context, node_id):
        """Get BIOS Setting based on node_id.

        :param context: Security context.
        :param node_id: The node id.
        :raises: NodeNotFound if the node id is not found.
        :return: A list of BIOSSetting objects.
        """
        node_bios_setting = cls.dbapi.get_bios_setting_list(node_id)
        return object_base.obj_make_list(
            context, cls(), BIOSSetting, node_bios_setting)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def sync_node_setting(cls, context, node_id, settings):
        """Returns lists of create/update/delete/unchanged settings.

        This method sync with 'bios_settings' database table and sorts
        out four lists of create/update/delete/unchanged settings.

        :param context: Security context.
        :param node_id: The node id.
        :param settings: BIOS settings to be synced.
        :returns: A 4-tuple of lists of BIOS settings to be created,
            updated, deleted and unchanged.
        """
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = []
        current_settings_dict = {}

        given_setting_names = [setting['name'] for setting in settings]
        current_settings = cls.get_by_node_id(context, node_id)

        for setting in current_settings:
            current_settings_dict[setting.name] = setting.value

        for setting in settings:
            if setting['name'] in current_settings_dict:
                if setting['value'] != current_settings_dict[setting['name']]:
                    update_list.append(setting)
                else:
                    nochange_list.append(setting)
            else:
                create_list.append(setting)

        for setting in current_settings:
            if setting.name not in given_setting_names:
                delete_list.append({'name': setting.name,
                                    'value': setting.value})

        return (create_list, update_list, delete_list, nochange_list)
