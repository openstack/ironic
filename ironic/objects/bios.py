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

from oslo_versionedobjects import base as object_base

from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields


@base.IronicObjectRegistry.register
class BIOSSetting(base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'node_id': object_fields.StringField(nullable=False),
        'name': object_fields.StringField(nullable=False),
        'value': object_fields.StringField(nullable=True),
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
        setting = [{'name': values['name'], 'value': values['value']}]
        db_bios_setting = self.dbapi.create_bios_setting_list(
            values['node_id'], setting, values['version'])
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
        setting = [{'name': values['name'], 'value': values['value']}]
        updated_bios_setting = self.dbapi.update_bios_setting_list(
            values['node_id'], setting, values['version'])
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
