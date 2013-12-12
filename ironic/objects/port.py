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

from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import utils


class Port(base.IronicObject):
    dbapi = dbapi.get_instance()

    fields = {
        'id': int,
        'uuid': utils.str_or_none,
        'node_id': utils.int_or_none,
        'address': utils.str_or_none,
        'extra': utils.dict_or_none,
    }

    @staticmethod
    def _from_db_object(port, db_port):
        """Converts a database entity to a formal object."""
        for field in port.fields:
            port[field] = db_port[field]

        port.obj_reset_changes()
        return port

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid=None):
        """Find a port based on uuid and return a Port object.

        :param uuid: the uuid of a port.
        :returns: a :class:`Port` object.
        """
        db_port = cls.dbapi.get_port(uuid)
        return Port._from_db_object(cls(), db_port)

    @base.remotable
    def save(self, context):
        """Save updates to this Port.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context
        """
        updates = self.obj_get_changes()
        self.dbapi.update_port(self.uuid, updates)

        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        """Loads updates for this Port.

        Loads a port with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded port column by column, if there are any updates.

        :param context: Security context
        """
        current = self.__class__.get_by_uuid(context, uuid=self.uuid)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
