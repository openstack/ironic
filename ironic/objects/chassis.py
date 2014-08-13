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
from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import utils as obj_utils


class Chassis(base.IronicObject):
    # Version 1.0: Initial version
    # Version 1.1: Add get() and get_by_id() and make get_by_uuid()
    #              only work with a uuid
    # Version 1.2: Add create() and destroy()
    # Version 1.3: Add list()
    VERSION = '1.3'

    dbapi = dbapi.get_instance()

    fields = {
        'id': int,
        'uuid': obj_utils.str_or_none,
        'extra': obj_utils.dict_or_none,
        'description': obj_utils.str_or_none,
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
    def get(cls, context, chassis_id):
        """Find a chassis based on its id or uuid and return a Chassis object.

        :param chassis_id: the id *or* uuid of a chassis.
        :returns: a :class:`Chassis` object.
        """
        if utils.is_int_like(chassis_id):
            return cls.get_by_id(context, chassis_id)
        elif utils.is_uuid_like(chassis_id):
            return cls.get_by_uuid(context, chassis_id)
        else:
            raise exception.InvalidIdentity(identity=chassis_id)

    @base.remotable_classmethod
    def get_by_id(cls, context, chassis_id):
        """Find a chassis based on its integer id and return a Chassis object.

        :param chassis_id: the id of a chassis.
        :returns: a :class:`Chassis` object.
        """
        db_chassis = cls.dbapi.get_chassis_by_id(chassis_id)
        chassis = Chassis._from_db_object(cls(), db_chassis)
        # FIXME(comstud): Setting of the context should be moved to
        # _from_db_object().
        chassis._context = context
        return chassis

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a chassis based on uuid and return a :class:`Chassis` object.

        :param uuid: the uuid of a chassis.
        :param context: Security context
        :returns: a :class:`Chassis` object.
        """
        db_chassis = cls.dbapi.get_chassis_by_uuid(uuid)
        chassis = Chassis._from_db_object(cls(), db_chassis)
        # FIXME(comstud): Setting of the context should be moved to
        # _from_db_object().
        chassis._context = context
        return chassis

    @base.remotable_classmethod
    def list(cls, context, limit=None, marker=None,
             sort_key=None, sort_dir=None):
        """Return a list of Chassis objects.

        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`Chassis` object.

        """
        chassis_list = []
        db_chassis = cls.dbapi.get_chassis_list(limit=limit,
                                                marker=marker,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir)
        for obj in db_chassis:
            chassis = Chassis._from_db_object(cls(), obj)
            # FIXME(comstud): Setting of the context should be moved to
            # _from_db_object().
            chassis._context = context
            chassis_list.append(chassis)
        return chassis_list

    @base.remotable
    def create(self, context=None):
        """Create a Chassis record in the DB.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        chassis before updates are made.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Chassis(context=context)

        """
        values = self.obj_get_changes()
        db_chassis = self.dbapi.create_chassis(values)
        self._from_db_object(self, db_chassis)

    @base.remotable
    def destroy(self, context=None):
        """Delete the Chassis from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Chassis(context=context)
        """
        self.dbapi.destroy_chassis(self.id)
        self.obj_reset_changes()

    @base.remotable
    def save(self, context=None):
        """Save updates to this Chassis.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context. NOTE: This is only used
                        internally by the indirection_api.
        """
        updates = self.obj_get_changes()
        self.dbapi.update_chassis(self.uuid, updates)

        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context=None):
        """Loads and applies updates for this Chassis.

        Loads a :class:`Chassis` with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded chassis column by column, if there are any updates.

        :param context: Security context. NOTE: This is only used
                        internally by the indirection_api.
        """
        current = self.__class__.get_by_uuid(self._context, uuid=self.uuid)
        for field in self.fields:
            if (hasattr(self, base.get_attrname(field)) and
                    self[field] != current[field]):
                self[field] = current[field]
