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


class Chassis(base.IronicObject):
    dbapi = dbapi.get_instance()

    fields = {
        'id': int,
        'uuid': utils.str_or_none,
        'extra': utils.dict_or_none,
        'description': utils.str_or_none,
    }

    @staticmethod
    def _from_db_object(chassis, db_chassis):
        """Converts a database entity to a formal :class:`Chassis` object.

        :param chassis: An object of :class:`Chassis`.
        :param db_chassis: A DB model of a chassis.
        :return: a :class:`Chassis` object.
        """
        for field in chassis.fields:
            chassis[field] = db_chassis[field]

        chassis.obj_reset_changes()
        return chassis

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid=None):
        """Find a chassis based on uuid and return a :class:`Chassis` object.

        :param uuid: the uuid of a chassis.
        :param context: Security context
        :returns: a :class:`Chassis` object.
        """
        db_chassis = cls.dbapi.get_chassis(uuid)
        return Chassis._from_db_object(cls(), db_chassis)

    @base.remotable
    def save(self, context):
        """Save updates to this Chassis.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context
        """
        updates = self.obj_get_changes()
        self.dbapi.update_chassis(self.uuid, updates)

        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        """Loads and applies updates for this Chassis.

        Loads a :class:`Chassis` with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded chassis column by column, if there are any updates.

        :param context: Security context
        """
        current = self.__class__.get_by_uuid(context, uuid=self.uuid)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
