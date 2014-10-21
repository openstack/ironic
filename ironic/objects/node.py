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

from ironic.common import exception
from ironic.common import utils
from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import utils as obj_utils


class Node(base.IronicObject):
    # Version 1.0: Initial version
    # Version 1.1: Added instance_info
    # Version 1.2: Add get() and get_by_id() and make get_by_uuid()
    #              only work with a uuid
    # Version 1.3: Add create() and destroy()
    # Version 1.4: Add get_by_instance_uuid()
    # Version 1.5: Add list()
    # Version 1.6: Add reserve() and release()
    # Version 1.7: Add conductor_affinity
    # Version 1.8: Add maintenance_reason
    VERSION = '1.8'

    dbapi = db_api.get_instance()

    fields = {
            'id': int,

            'uuid': obj_utils.str_or_none,
            'chassis_id': obj_utils.int_or_none,
            'instance_uuid': obj_utils.str_or_none,

            'driver': obj_utils.str_or_none,
            'driver_info': obj_utils.dict_or_none,

            'instance_info': obj_utils.dict_or_none,
            'properties': obj_utils.dict_or_none,
            'reservation': obj_utils.str_or_none,
            # a reference to the id of the conductor service, not its hostname,
            # that has most recently performed some action which could require
            # local state to be maintained (eg, built a PXE config)
            'conductor_affinity': obj_utils.int_or_none,

            # One of states.POWER_ON|POWER_OFF|NOSTATE|ERROR
            'power_state': obj_utils.str_or_none,

            # Set to one of states.POWER_ON|POWER_OFF when a power operation
            # starts, and set to NOSTATE when the operation finishes
            # (successfully or unsuccessfully).
            'target_power_state': obj_utils.str_or_none,

            'provision_state': obj_utils.str_or_none,
            'provision_updated_at': obj_utils.datetime_or_str_or_none,
            'target_provision_state': obj_utils.str_or_none,

            'maintenance': bool,
            'maintenance_reason': obj_utils.str_or_none,
            'console_enabled': bool,

            # Any error from the most recent (last) asynchronous transaction
            # that started but failed to finish.
            'last_error': obj_utils.str_or_none,

            'extra': obj_utils.dict_or_none,
            }

    @staticmethod
    def _from_db_object(node, db_node):
        """Converts a database entity to a formal object."""
        for field in node.fields:
            node[field] = db_node[field]
        node.obj_reset_changes()
        return node

    @base.remotable_classmethod
    def get(cls, context, node_id):
        """Find a node based on its id or uuid and return a Node object.

        :param node_id: the id *or* uuid of a node.
        :returns: a :class:`Node` object.
        """
        if utils.is_int_like(node_id):
            return cls.get_by_id(context, node_id)
        elif utils.is_uuid_like(node_id):
            return cls.get_by_uuid(context, node_id)
        else:
            raise exception.InvalidIdentity(identity=node_id)

    @base.remotable_classmethod
    def get_by_id(cls, context, node_id):
        """Find a node based on its integer id and return a Node object.

        :param node_id: the id of a node.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_id(node_id)
        node = Node._from_db_object(cls(context), db_node)
        return node

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a node based on uuid and return a Node object.

        :param uuid: the uuid of a node.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_uuid(uuid)
        node = Node._from_db_object(cls(context), db_node)
        return node

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        """Find a node based on the instance uuid and return a Node object.

        :param uuid: the uuid of the instance.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_instance(instance_uuid)
        node = Node._from_db_object(cls(context), db_node)
        return node

    @base.remotable_classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None, filters=None):
        """Return a list of Node objects.

        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param filters: Filters to apply.
        :returns: a list of :class:`Node` object.

        """
        db_nodes = cls.dbapi.get_node_list(filters=filters, limit=limit,
                                           marker=marker, sort_key=sort_key,
                                           sort_dir=sort_dir)
        return [Node._from_db_object(cls(context), obj) for obj in db_nodes]

    @base.remotable_classmethod
    def reserve(cls, context, tag, node_id):
        """Get and reserve a node.

        To prevent other ManagerServices from manipulating the given
        Node while a Task is performed, mark it reserved by this host.

        :param context: Security context.
        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id or uuid.
        :raises: NodeNotFound if the node is not found.
        :returns: a :class:`Node` object.

        """
        db_node = cls.dbapi.reserve_node(tag, node_id)
        node = Node._from_db_object(cls(context), db_node)
        return node

    @base.remotable_classmethod
    def release(cls, context, tag, node_id):
        """Release the reservation on a node.

        :param context: Security context.
        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id or uuid.
        :raises: NodeNotFound if the node is not found.

        """
        cls.dbapi.release_node(tag, node_id)

    @base.remotable
    def create(self, context=None):
        """Create a Node record in the DB.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        node before updates are made.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)

        """
        values = self.obj_get_changes()
        db_node = self.dbapi.create_node(values)
        self._from_db_object(self, db_node)

    @base.remotable
    def destroy(self, context=None):
        """Delete the Node from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        """
        self.dbapi.destroy_node(self.uuid)
        self.obj_reset_changes()

    @base.remotable
    def save(self, context=None):
        """Save updates to this Node.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        node before updates are made.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        """
        updates = self.obj_get_changes()
        self.dbapi.update_node(self.uuid, updates)
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context=None):
        """Refresh the object by re-fetching from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        """
        current = self.__class__.get_by_uuid(self._context, self.uuid)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
