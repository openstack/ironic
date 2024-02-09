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
from ironic.common import utils
from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import fields as object_fields


@base.IronicObjectRegistry.register
class Conductor(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add register() and unregister(), make the context parameter
    #              to touch() optional.
    # Version 1.2: Add register_hardware_interfaces() and
    #              unregister_all_hardware_interfaces()
    # Version 1.3: Add conductor_group field.
    VERSION = '1.3'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'drivers': object_fields.ListOfStringsField(nullable=True),
        'hostname': object_fields.StringField(),
        'conductor_group': object_fields.StringField(),
    }

    @classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None):
        """Return a list of Conductor objects.

        :param cls: the :class:`Conductor`
        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`Conductor` object.
        """
        db_conductors = cls.dbapi.get_conductor_list(limit=limit,
                                                     marker=marker,
                                                     sort_key=sort_key,
                                                     sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_conductors)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_hostname(cls, context, hostname, online=True):
        """Get a Conductor record by its hostname.

        :param cls: the :class:`Conductor`
        :param context: Security context
        :param hostname: the hostname on which a Conductor is running
        :param online: Specify the expected ``online`` field value for the
                       conductor to be retrieved. The ``online`` field is
                       ignored if this value is set to None.
        :returns: a :class:`Conductor` object.
        """
        db_obj = cls.dbapi.get_conductor(hostname, online=online)
        conductor = cls._from_db_object(context, cls(), db_obj)
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
        current = self.get_by_hostname(self._context, hostname=self.hostname)
        self.obj_refresh(current)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def touch(self, context=None, online=True):
        """Touch this conductor's DB record, marking it as up-to-date."""
        self.dbapi.touch_conductor(self.hostname, online=online)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    @classmethod
    def register(cls, context, hostname, drivers, conductor_group,
                 update_existing=False):
        """Register an active conductor with the cluster.

        :param cls: the :class:`Conductor`
        :param context: Security context
        :param hostname: the hostname on which the conductor will run
        :param drivers: the list of drivers enabled in the conductor
        :param conductor_group: conductor group to join, used for
                                node:conductor affinity.
        :param update_existing: When false, registration will raise an
                                exception when a conflicting online record
                                is found. When true, will overwrite the
                                existing record. Default: False.
        :raises: ConductorAlreadyRegistered
        :returns: a :class:`Conductor` object.

        """
        utils.validate_conductor_group(conductor_group)
        db_cond = cls.dbapi.register_conductor(
            {'hostname': hostname,
             'drivers': drivers,
             'conductor_group': conductor_group.lower(),
             'version': cls.get_target_version()},
            update_existing=update_existing)
        return cls._from_db_object(context, cls(), db_cond)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def unregister(self, context=None):
        """Remove this conductor from the service registry."""
        self.unregister_all_hardware_interfaces()
        self.dbapi.unregister_conductor(self.hostname)

    def register_hardware_interfaces(self, interfaces):
        """Register hardware interfaces with the conductor.

        :param interfaces: List of interface to register, each entry should
            be a dictionary containing "hardware_type", "interface_type",
            "interface_name" and "default", e.g.
            {'hardware_type': 'hardware-type', 'interface_type': 'deploy',
            'interface_name': 'direct', 'default': True}
        """
        self.dbapi.register_conductor_hardware_interfaces(self.id, interfaces)

    def unregister_all_hardware_interfaces(self):
        """Unregister all hardware interfaces for this conductor."""
        self.dbapi.unregister_conductor_hardware_interfaces(self.id)
