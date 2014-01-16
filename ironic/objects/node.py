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


class Node(base.IronicObject):

    dbapi = db_api.get_instance()

    fields = {
            'id': int,

            'uuid': utils.str_or_none,
            'chassis_id': utils.int_or_none,
            'instance_uuid': utils.str_or_none,

            'driver': utils.str_or_none,
            'driver_info': utils.dict_or_none,

            'properties': utils.dict_or_none,
            'reservation': utils.str_or_none,

            # One of states.POWER_ON|POWER_OFF|NOSTATE|ERROR
            'power_state': utils.str_or_none,

            # Set to one of states.POWER_ON|POWER_OFF when a power operation
            # starts, and set to NOSTATE when the operation finishes
            # (successfully or unsuccessfully).
            'target_power_state': utils.str_or_none,

            'provision_state': utils.str_or_none,
            'target_provision_state': utils.str_or_none,

            'maintenance': bool,

            # Any error from the most recent (last) asynchronous transaction
            # that started but failed to finish.
            'last_error': utils.str_or_none,

            'extra': utils.dict_or_none,
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
        db_node = cls.dbapi.get_node(uuid)
        return Node._from_db_object(cls(), db_node)

    @base.remotable
    def save(self, context):
        """Save updates to this Node.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        node before updates are made.

        :param context: Security context
        """
        updates = self.obj_get_changes()
        self.dbapi.update_node(self.uuid, updates)

        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        current = self.__class__.get_by_uuid(context, uuid=self.uuid)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
