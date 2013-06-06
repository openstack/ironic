# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import utils


def objectify(fn):
    """Decorator to convert database results into Node objects."""
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        try:
            return Node._from_db_object(Node(), result)
        except TypeError:
            # TODO(deva): handle lists of objects better
            #             once support for those lands and is imported.
            return [Node._from_db_object(Node(), obj) for obj in result]
    return wrapper


class Node(base.IronicObject):

    dbapi = db_api.get_instance()

    fields = {
            'id': int,

            'uuid': utils.str_or_none,
            'chassis_id': utils.int_or_none,
            'instance_uuid': utils.str_or_none,

            # NOTE(deva): should driver_info be a nested_object_or_none,
            #             or does this bind the driver API too tightly?
            'driver': utils.str_or_none,
            'driver_info': utils.str_or_none,

            'properties': utils.str_or_none,
            'reservation': utils.str_or_none,
            'task_state': utils.str_or_none,
            'task_start': utils.datetime_or_none,
            'extra': utils.str_or_none,
            }

    @staticmethod
    def _from_db_object(node, db_node):
        """Converts a database entity to a formal object."""
        for field in node.fields:
            node[field] = db_node[field]

        node.obj_reset_changes()
        return node

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a node based on uuid and return a Node object.

        :param uuid: the uuid of a node.
        :returns: a :class:`Node` object.
        """
        # TODO(deva): enable getting ports for this node
        db_node = cls.dbapi.get_node(uuid)
        return Node._from_db_object(cls(), db_node)

    @base.remotable
    def save(self, context):
        """Save updates to this Node.

        Column-wise updates will be made based on the result of
        self.what_changed(). If expected_task_state is provided,
        it will be checked against the in-database copy of the
        node before updates are made.

        :param context: Security context
        """
        updates = {}
        changes = self.obj_what_changed()
        for field in changes:
            updates[field] = self[field]
        self.dbapi.update_node(self.uuid, updates)

        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        current = self.__class__.get_by_uuid(context, uuid=self.uuid)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
