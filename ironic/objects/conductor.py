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

import datetime

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
    # Version 1.4: Add online field.
    # Version 1.5: Add new remotable methods
    #              get_shard_list, list_hardware_type_interfaces,
    #              and get_active_hardware_type_dict
    # Version 1.6: Updates methods numerous conductor methods to
    #              to be remotable calls.
    VERSION = '1.6'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'drivers': object_fields.ListOfStringsField(nullable=True),
        'hostname': object_fields.StringField(),
        'conductor_group': object_fields.StringField(),
        'online': object_fields.BooleanField(),
    }

    @object_base.remotable_classmethod
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

    @object_base.remotable_classmethod
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

    @object_base.remotable
    def save(self, context):
        """Save is not supported by Conductor objects."""
        raise NotImplementedError(
            _('Cannot update a conductor record directly.'))

    @object_base.remotable
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

    def touch(self, context=None, online=True):
        """Touch this conductor's DB record, marking it as up-to-date."""
        self.dbapi.touch_conductor(self.hostname, online=online)

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

    def unregister(self, context=None):
        """Remove this conductor from the service registry."""
        self.unregister_all_hardware_interfaces()
        self.dbapi.unregister_conductor(self.hostname)

    @classmethod
    def delete(cls, context, hostname):
        """Delete a conductor from the database.

        :param cls: the :class:`Conductor`
        :param context: Security context
        :param hostname: the hostname of the conductor to delete
        :raises: ConductorNotFound if the conductor doesn't exist
        """
        cls.dbapi.delete_conductor(hostname)

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

    @base.remotable_classmethod
    def get_active_hardware_type_dict(cls, context, use_groups=False):
        """Provides a hardware type list as it relates to the conductors.

        This method provides a pass-through call mechanism on an attached
        object for insight into the state of hardware managers by conductors
        and does so as a direct call for compatibility with lightweight
        API method.
        """
        # NOTE(TheJulia): Return a dict object instead of a collection object
        # because the indirection layer cannot handle a collection class.
        return dict(
            cls.dbapi.get_active_hardware_type_dict(use_groups=use_groups))

    @base.remotable_classmethod
    def list_hardware_type_interfaces_dict(cls, context, names):
        """Provides a list of hardware type interface names from conductors.

        This method provides a pass-through call mechanism on an object as
        opposed to direct API call functionality.
        """
        # NOTE(TheJulia): SQLAlchemy hands us a hybrid object which also
        # works like a dictionary, and the consumer of this call treats
        # it as such but we can't hand it across the message bus as a
        # DB object.
        db_resp = cls.dbapi.list_hardware_type_interfaces(names)
        resp = []
        for row in db_resp:
            entry = {}
            for col_key in row.keys():
                if isinstance(row[col_key], datetime.datetime):
                    # SQLAclchemy hands response objects with nested
                    # datetime objects, so they need to be converted
                    # before trying to serialize as opposed before
                    # sending the API response out.
                    entry[col_key] = row[col_key].isoformat()
                else:
                    entry[col_key] = row[col_key]
            resp.append(entry)
        return resp

    @base.remotable_classmethod
    def get_shard_list(cls, context):
        """Provides a shard list as it relates to conductors.

        This method provides a pass-through all mechanism on an attached
        object for insight into the list of represented shards in a deployment
        which is sourced in the database combined with runtime configurations.
        The primary prupose of this being be lightweight and enable
        indirection_api call usage instead of trying to directly invoke the
        database.
        """
        # FIXME(TheJulia): Ideally this should be a formal object, but the
        # calling method expects json, so it works.
        return cls.dbapi.get_shard_list()
