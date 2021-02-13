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

from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import uuidutils
from oslo_utils import versionutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.common import utils
from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import notification


@base.IronicObjectRegistry.register
class Portgroup(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add internal_info field
    # Version 1.2: Add standalone_ports_supported field
    # Version 1.3: Add mode and properties fields
    # Version 1.4: Migrate/copy extra['vif_port_id'] to
    #              internal_info['tenant_vif_port_id'] (not an explicit db
    #              change)
    VERSION = '1.4'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'name': object_fields.StringField(nullable=True),
        'node_id': object_fields.IntegerField(nullable=True),
        'address': object_fields.MACAddressField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'internal_info': object_fields.FlexibleDictField(nullable=True),
        'standalone_ports_supported': object_fields.BooleanField(),
        'mode': object_fields.StringField(nullable=True),
        'properties': object_fields.FlexibleDictField(nullable=True),
    }

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        Version 1.4: if extra['vif_port_id'] is specified (non-null) and
            internal_info['tenant_vif_port_id'] is not specified, copy the
            .extra value to internal_info. There is nothing to do here when
            downgrading to an older version.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version >= (1, 4):
            if self.obj_attr_is_set('extra'):
                vif = self.extra.get('vif_port_id')
                if vif:
                    internal_info = (self.internal_info
                                     if self.obj_attr_is_set('internal_info')
                                     else {})
                    if 'tenant_vif_port_id' not in internal_info:
                        internal_info['tenant_vif_port_id'] = vif
                        self.internal_info = internal_info

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, portgroup_ident):
        """Find a portgroup based on its id, uuid, name or address.

        :param portgroup_ident: The id, uuid, name or address of a portgroup.
        :param context: Security context
        :returns: A :class:`Portgroup` object.
        :raises: InvalidIdentity

        """
        if strutils.is_int_like(portgroup_ident):
            return cls.get_by_id(context, portgroup_ident)
        elif uuidutils.is_uuid_like(portgroup_ident):
            return cls.get_by_uuid(context, portgroup_ident)
        elif netutils.is_valid_mac(portgroup_ident):
            return cls.get_by_address(context, portgroup_ident)
        elif utils.is_valid_logical_name(portgroup_ident):
            return cls.get_by_name(context, portgroup_ident)
        else:
            raise exception.InvalidIdentity(identity=portgroup_ident)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, portgroup_id):
        """Find a portgroup by its integer ID and return a Portgroup object.

        :param cls: the :class:`Portgroup`
        :param context: Security context
        :param portgroup_id: The ID of a portgroup.
        :returns: A :class:`Portgroup` object.
        :raises: PortgroupNotFound

        """
        db_portgroup = cls.dbapi.get_portgroup_by_id(portgroup_id)
        portgroup = cls._from_db_object(context, cls(), db_portgroup)
        return portgroup

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a portgroup by UUID and return a :class:`Portgroup` object.

        :param cls: the :class:`Portgroup`
        :param context: Security context
        :param uuid: The UUID of a portgroup.
        :returns: A :class:`Portgroup` object.
        :raises: PortgroupNotFound

        """
        db_portgroup = cls.dbapi.get_portgroup_by_uuid(uuid)
        portgroup = cls._from_db_object(context, cls(), db_portgroup)
        return portgroup

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_address(cls, context, address, project=None):
        """Find portgroup by address and return a :class:`Portgroup` object.

        :param cls: the :class:`Portgroup`
        :param context: Security context
        :param address: The MAC address of a portgroup.
        :param project: a node owner or lessee to match against.
        :returns: A :class:`Portgroup` object.
        :raises: PortgroupNotFound

        """
        db_portgroup = cls.dbapi.get_portgroup_by_address(address,
                                                          project=project)
        portgroup = cls._from_db_object(context, cls(), db_portgroup)
        return portgroup

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_name(cls, context, name):
        """Find portgroup based on name and return a :class:`Portgroup` object.

        :param cls: the :class:`Portgroup`
        :param context: Security context
        :param name: The name of a portgroup.
        :returns: A :class:`Portgroup` object.
        :raises: PortgroupNotFound

        """
        db_portgroup = cls.dbapi.get_portgroup_by_name(name)
        portgroup = cls._from_db_object(context, cls(), db_portgroup)
        return portgroup

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None,
             sort_key=None, sort_dir=None, project=None):
        """Return a list of Portgroup objects.

        :param cls: the :class:`Portgroup`
        :param context: Security context.
        :param limit: Maximum number of resources to return in a single result.
        :param marker: Pagination marker for large data sets.
        :param sort_key: Column to sort results by.
        :param sort_dir: Direction to sort. "asc" or "desc".
        :param project: a node owner or lessee to match against.
        :returns: A list of :class:`Portgroup` object.
        :raises: InvalidParameterValue

        """
        db_portgroups = cls.dbapi.get_portgroup_list(limit=limit,
                                                     marker=marker,
                                                     sort_key=sort_key,
                                                     sort_dir=sort_dir,
                                                     project=project)
        return cls._from_db_object_list(context, db_portgroups)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_node_id(cls, context, node_id, limit=None, marker=None,
                        sort_key=None, sort_dir=None, project=None):
        """Return a list of Portgroup objects associated with a given node ID.

        :param cls: the :class:`Portgroup`
        :param context: Security context.
        :param node_id: The ID of the node.
        :param limit: Maximum number of resources to return in a single result.
        :param marker: Pagination marker for large data sets.
        :param sort_key: Column to sort results by.
        :param sort_dir: Direction to sort. "asc" or "desc".
        :param project: a node owner or lessee to match against.
        :returns: A list of :class:`Portgroup` object.
        :raises: InvalidParameterValue

        """
        db_portgroups = cls.dbapi.get_portgroups_by_node_id(node_id,
                                                            limit=limit,
                                                            marker=marker,
                                                            sort_key=sort_key,
                                                            sort_dir=sort_dir,
                                                            project=project)
        return cls._from_db_object_list(context, db_portgroups)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a Portgroup record in the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Portgroup(context)
        :raises: DuplicateName, MACAlreadyExists, PortgroupAlreadyExists

        """
        values = self.do_version_changes_for_db()
        db_portgroup = self.dbapi.create_portgroup(values)
        self._from_db_object(self._context, self, db_portgroup)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the Portgroup from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Portgroup(context)
        :raises: PortgroupNotEmpty, PortgroupNotFound

        """
        self.dbapi.destroy_portgroup(self.uuid)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this Portgroup.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Portgroup(context)
        :raises: PortgroupNotFound, DuplicateName, MACAlreadyExists

        """
        updates = self.do_version_changes_for_db()
        updated_portgroup = self.dbapi.update_portgroup(self.uuid, updates)
        self._from_db_object(self._context, self, updated_portgroup)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Loads updates for this Portgroup.

        Loads a portgroup with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded portgroup column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Portgroup(context)
        :raises: PortgroupNotFound

        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()


@base.IronicObjectRegistry.register
class PortgroupCRUDNotification(notification.NotificationBase):
    """Notification when ironic creates, updates or deletes a portgroup."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('PortgroupCRUDPayload')
    }


@base.IronicObjectRegistry.register
class PortgroupCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'address': ('portgroup', 'address'),
        'extra': ('portgroup', 'extra'),
        'mode': ('portgroup', 'mode'),
        'name': ('portgroup', 'name'),
        'properties': ('portgroup', 'properties'),
        'standalone_ports_supported': ('portgroup',
                                       'standalone_ports_supported'),
        'created_at': ('portgroup', 'created_at'),
        'updated_at': ('portgroup', 'updated_at'),
        'uuid': ('portgroup', 'uuid')
    }

    fields = {
        'address': object_fields.MACAddressField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'mode': object_fields.StringField(nullable=True),
        'name': object_fields.StringField(nullable=True),
        'node_uuid': object_fields.UUIDField(),
        'properties': object_fields.FlexibleDictField(nullable=True),
        'standalone_ports_supported': object_fields.BooleanField(
            nullable=True),
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, portgroup, node_uuid):
        super(PortgroupCRUDPayload, self).__init__(node_uuid=node_uuid)
        self.populate_schema(portgroup=portgroup)
