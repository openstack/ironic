# coding=utf-8
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

from ironic.common.i18n import _
from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import fields as object_fields


@base.IronicObjectRegistry.register
class Conductor(base.IronicObject, object_base.VersionedObjectDictCompat):

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'drivers': object_fields.ListOfStringsField(nullable=True),
        'hostname': object_fields.StringField(),
    }

    @staticmethod
    def _from_db_object(conductor, db_obj):
        """Converts a database entity to a formal object."""
        for field in conductor.fields:
            conductor[field] = db_obj[field]

        conductor.obj_reset_changes()
        return conductor

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_hostname(cls, context, hostname):
        """Get a Conductor record by its hostname.

        :param hostname: the hostname on which a Conductor is running
        :returns: a :class:`Conductor` object.
        """
        db_obj = cls.dbapi.get_conductor(hostname)
        conductor = Conductor._from_db_object(cls(context), db_obj)
        return conductor

    def save(self, context):
        """Save is not supported by Conductor objects."""
        raise NotImplementedError(
            _('Cannot update a conductor record directly.'))

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Loads and applies updates for this Conductor.

        Loads a :class:`Conductor` with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded chassis column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Conductor(context)
        """
        current = self.__class__.get_by_hostname(self._context,
                                                 hostname=self.hostname)
        self.obj_refresh(current)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def touch(self, context):
        """Touch this conductor's DB record, marking it as up-to-date."""
        self.dbapi.touch_conductor(self.hostname)
