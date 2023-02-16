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
class NodeInventory(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'node_id': object_fields.IntegerField(nullable=True),
        'inventory_data': object_fields.FlexibleDictField(nullable=True),
        'plugin_data': object_fields.FlexibleDictField(nullable=True),
    }

    @classmethod
    def _from_node_object(cls, context, node):
        """Convert a node into a virtual `NodeInventory` object."""
        result = cls(context)
        result._update_from_node_object(node)
        return result

    def _update_from_node_object(self, node):
        """Update the NodeInventory object from the node."""
        for src, dest in self.node_mapping.items():
            setattr(self, dest, getattr(node, src, None))
        for src, dest in self.instance_info_mapping.items():
            setattr(self, dest, node.instance_info.get(src))

    @classmethod
    def get_by_node_id(cls, context, node_id):
        """Get a NodeInventory object by its node ID.

        :param cls: the :class:`NodeInventory`
        :param context: Security context
        :param uuid: The UUID of a NodeInventory.
        :returns: A :class:`NodeInventory` object.
        :raises: NodeInventoryNotFound

        """
        db_inventory = cls.dbapi.get_node_inventory_by_node_id(node_id)
        inventory = cls._from_db_object(context, cls(), db_inventory)
        return inventory

    def create(self, context=None):
        """Create a NodeInventory record in the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: NodeHistory(context)
        """
        values = self.do_version_changes_for_db()
        db_inventory = self.dbapi.create_node_inventory(values)
        self._from_db_object(self._context, self, db_inventory)

    def destroy(self, context=None):
        """Delete the NodeInventory from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: NodeInventory(context)
        :raises: NodeInventoryNotFound
        """
        self.dbapi.destroy_node_inventory_by_node_id(self.node_id)
        self.obj_reset_changes()
