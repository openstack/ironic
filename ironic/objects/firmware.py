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
class FirmwareComponent(base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'node_id': object_fields.IntegerField(nullable=False),
        'component': object_fields.StringField(nullable=False),
        'initial_version': object_fields.StringField(nullable=False),
        'current_version': object_fields.StringField(nullable=True),
        'last_version_flashed': object_fields.StringField(nullable=True),
    }

    def create(self, context=None):
        """Create a Firmware record in the DB.

        :param context: Security context.
        :raises: NodeNotFound if the node is not found.
        :raises: FirmwareComponentAlreadyExists if the record already exists.
        """
        values = self.do_version_changes_for_db()
        # Note(iurygregory): We ensure that when creating we will be setting
        # initial_version to the current_version we got from the BMC.
        values['initial_version'] = values['current_version']
        db_fwcmp = self.dbapi.create_firmware_component(values)
        self._from_db_object(self._context, self, db_fwcmp)

    def save(self, context=None):
        """Save updates  to this Firmware Component.

        Updates will be made column by column based on the result of
        self.what_changed()

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: FirmwareComponent(context)
        :raises: NodeNotFound if the node id is not found.
        :raises: FirmwareComponentNotFound if the component is not found.
        """

        # NOTE(iurygregory): some fields shouldn't be updated, like
        # 'initial_version', 'id', 'node_id', 'component'
        # filter them out or raise an Error?
        updates = self.do_version_changes_for_db()
        up_fwcmp = self.dbapi.update_firmware_component(
            self.node_id, self.component, updates)
        self._from_db_object(self._context, self, up_fwcmp)

    @classmethod
    def get(cls, context, node_id, name):
        """Get a FirmwareComponent based on its node_id and name.

        :param context: Security context.
        :param node_id: The node id.
        :param name: The Firmware Component name.
        :raises: NodeNotFound if the node id is not found.
        :raises: FirmwareComponentNotFound if the Firmware Component
            name is not found.
        :returns: A :class:'FirmwareComponent' object.
        """
        db_fw_cmp = cls.dbapi.get_firmware_component(node_id, name)
        fw_cmp = cls._from_db_object(context, cls(), db_fw_cmp)
        return fw_cmp


@base.IronicObjectRegistry.register
class FirmwareComponentList(base.IronicObjectListBase, base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'objects': object_fields.ListOfObjectsField('FirmwareComponent'),
    }

    @classmethod
    def get_by_node_id(cls, context, node_id):
        """Get FirmwareComponent based on node_id.

        :param context: Security context.
        :param node_id: The node id.
        :raises: NodeNotFound if the node is not found.
        :return: A list of FirmwareComponent objects.
        """
        node_fw_components = cls.dbapi.get_firmware_component_list(node_id)
        return object_base.obj_make_list(
            context, cls(), FirmwareComponent, node_fw_components)

    @classmethod
    def sync_firmware_components(cls, context, node_id, components):
        """Returns a list of create/update components.

        This method sync with the 'firmware_information' database table
        and sorts three lists - create / update / unchanged components.

        :param context: Security context.
        :param node_id: The node id.
        :param components: List of FirmwareComponents.
        :returns: A 3-tuple of lists of Firmware Components to be created,
            updated and unchanged.
        """
        create_list = []
        update_list = []
        unchanged_list = []
        current_components_dict = {}

        current_components = cls.get_by_node_id(context, node_id)

        for cmp in current_components:
            current_components_dict[cmp.component] = {
                'initial_version': cmp.initial_version,
                'current_version': cmp.current_version,
                'last_version_flashed': cmp.last_version_flashed,
            }

        for cmp in components:
            if cmp['component'] in current_components_dict:
                values = current_components_dict[cmp['component']]
                if values.get('last_version_flashed') is None:
                    lvf_changed = False
                    cv_changed = cmp['current_version'] \
                        != values.get('current_version')
                else:
                    lvf_changed = cmp['current_version'] \
                        != values.get('last_version_flashed')
                    cv_changed = cmp['current_version'] \
                        != values.get('current_version')

                if cv_changed or lvf_changed:
                    update_list.append(cmp)
                else:
                    unchanged_list.append(cmp)
            else:
                create_list.append(cmp)

        return (create_list, update_list, unchanged_list)
