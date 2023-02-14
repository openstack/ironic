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
class Port(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add get() and get_by_id() and get_by_address() and
    #              make get_by_uuid() only work with a uuid
    # Version 1.2: Add create() and destroy()
    # Version 1.3: Add list()
    # Version 1.4: Add list_by_node_id()
    # Version 1.5: Add list_by_portgroup_id() and new fields
    #              local_link_connection, portgroup_id and pxe_enabled
    # Version 1.6: Add internal_info field
    # Version 1.7: Add physical_network field
    # Version 1.8: Migrate/copy extra['vif_port_id'] to
    #              internal_info['tenant_vif_port_id'] (not an explicit db
    #              change)
    # Version 1.9: Add support for Smart NIC port
    # Version 1.10: Add name field
    # Version 1.11: Add node_uuid field
    VERSION = '1.11'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'node_id': object_fields.IntegerField(nullable=True),
        'node_uuid': object_fields.UUIDField(nullable=True),
        'address': object_fields.MACAddressField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'local_link_connection': object_fields.FlexibleDictField(
            nullable=True),
        'portgroup_id': object_fields.IntegerField(nullable=True),
        'pxe_enabled': object_fields.BooleanField(),
        'internal_info': object_fields.FlexibleDictField(nullable=True),
        'physical_network': object_fields.StringField(nullable=True),
        'is_smartnic': object_fields.BooleanField(nullable=True,
                                                  default=False),
        'name': object_fields.StringField(nullable=True),
    }

    def _convert_name_field(self, target_version,
                            remove_unavailable_fields=True):
        name_is_set = self.obj_attr_is_set('name')
        if target_version >= (1, 10):
            # Target version supports name. Set it to its default
            # value if it is not set.
            if not name_is_set:
                self.name = None
        elif name_is_set:
            # Target version does not support name, and it is set.
            if remove_unavailable_fields:
                # (De)serialising: remove unavailable fields.
                delattr(self, 'name')
            elif self.name is not None:
                # DB: set unavailable fields to their default.
                self.name = None

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        Version 1.7: physical_network field was added. Its default value is
            None. For versions prior to this, it should be set to None (or
            removed).

        Version 1.8: if extra['vif_port_id'] is specified (non-null) and
            internal_info['tenant_vif_port_id'] is not specified, copy the
            .extra value to internal_info. There is nothing to do here when
            downgrading to an older version.

        Version 1.9: remove is_smartnic field for unsupported versions if
            remove_unavailable_fields is True.

        Version 1.10: remove name field for unsupported versions if
            remove_unavailable_fields is True.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version >= (1, 8):
            if self.obj_attr_is_set('extra'):
                vif = self.extra.get('vif_port_id')
                if vif:
                    internal_info = (self.internal_info
                                     if self.obj_attr_is_set('internal_info')
                                     else {})
                    if 'tenant_vif_port_id' not in internal_info:
                        internal_info['tenant_vif_port_id'] = vif
                        self.internal_info = internal_info

        # Convert the physical_network field.
        physnet_is_set = self.obj_attr_is_set('physical_network')
        if target_version >= (1, 7):
            # Target version supports physical_network. Set it to its default
            # value if it is not set.
            if not physnet_is_set:
                self.physical_network = None
        elif physnet_is_set:
            # Target version does not support physical_network, and it is set.
            if remove_unavailable_fields:
                # (De)serialising: remove unavailable fields.
                delattr(self, 'physical_network')
            elif self.physical_network is not None:
                # DB: set unavailable fields to their default.
                self.physical_network = None

        # Convert is_smartnic field.
        is_smartnic_set = self.obj_attr_is_set('is_smartnic')
        if target_version >= (1, 9):
            # Target version supports is_smartnic. Set it to its default
            # value if it is not set.
            if not is_smartnic_set:
                self.is_smartnic = False

        # handle is_smartnic field in older version
        elif is_smartnic_set:
            # Target version does not support is_smartnic, and it is set.
            if remove_unavailable_fields:
                # (De)serialising: remove unavailable fields.
                delattr(self, 'is_smartnic')
            elif self.is_smartnic is not False:
                # DB: set unavailable fields to their default.
                self.is_smartnic = False

        # Convert the name field.
        self._convert_name_field(target_version, remove_unavailable_fields)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, port_id):
        """Find a port.

        Find a port based on its id or uuid or name or MAC address and return
        a Port object.

        :param context: Security context
        :param port_id: the id *or* uuid *or* name *or* MAC address of a port.
        :returns: a :class:`Port` object.
        :raises: InvalidIdentity

        """
        if strutils.is_int_like(port_id):
            return cls.get_by_id(context, port_id)
        elif uuidutils.is_uuid_like(port_id):
            return cls.get_by_uuid(context, port_id)
        elif netutils.is_valid_mac(port_id):
            return cls.get_by_address(context, port_id)
        elif utils.is_valid_logical_name(port_id):
            return cls.get_by_name(context, port_id)
        else:
            raise exception.InvalidIdentity(identity=port_id)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, port_id):
        """Find a port based on its integer ID and return a Port object.

        :param cls: the :class:`Port`
        :param context: Security context
        :param port_id: the ID of a port.
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        db_port = cls.dbapi.get_port_by_id(port_id)
        port = cls._from_db_object(context, cls(), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a port based on UUID and return a :class:`Port` object.

        :param cls: the :class:`Port`
        :param context: Security context
        :param uuid: the UUID of a port.
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        db_port = cls.dbapi.get_port_by_uuid(uuid)
        port = cls._from_db_object(context, cls(), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_address(cls, context, address, owner=None, project=None):
        """Find a port based on address and return a :class:`Port` object.

        :param cls: the :class:`Port`
        :param context: Security context
        :param address: the address of a port.
        :param owner: DEPRECATED a node owner to match against
        :param project: a node owner or lessee to match against
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        if owner and not project:
            project = owner
        db_port = cls.dbapi.get_port_by_address(address, project=project)
        port = cls._from_db_object(context, cls(), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_name(cls, context, name):
        """Find a port based on name and return a :class:`Port` object.

        :param cls: the :class:`Port`
        :param context: Security context
        :param name: the name of a port.
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        db_port = cls.dbapi.get_port_by_name(name)
        port = cls._from_db_object(context, cls(), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None,
             sort_key=None, sort_dir=None, owner=None, project=None):
        """Return a list of Port objects.

        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param owner: DEPRECATED a node owner to match against
        :param project: a node owner or lessee to match against
        :returns: a list of :class:`Port` object.
        :raises: InvalidParameterValue

        """
        if owner and not project:
            project = owner
        db_ports = cls.dbapi.get_port_list(limit=limit,
                                           marker=marker,
                                           sort_key=sort_key,
                                           sort_dir=sort_dir,
                                           project=project)
        return cls._from_db_object_list(context, db_ports)

    @classmethod
    def list_by_node_shards(cls, context, shards, limit=None, marker=None,
                            sort_key=None, sort_dir=None, project=None):
        """Return a list of Port objects associated with nodes in shards

        :param context: Security context.
        :param shards: a list of shards
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param project: a node owner or lessee to match against
        :returns: a list of :class:`Port` object.

        """
        db_ports = cls.dbapi.get_ports_by_shards(shards, limit=limit,
                                                 marker=marker,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)
        return cls._from_db_object_list(context, db_ports)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_node_id(cls, context, node_id, limit=None, marker=None,
                        sort_key=None, sort_dir=None, owner=None,
                        project=None):
        """Return a list of Port objects associated with a given node ID.

        :param context: Security context.
        :param node_id: the ID of the node.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param owner: DEPRECATED a node owner to match against
        :param project: a node owner or lessee to match against
        :returns: a list of :class:`Port` object.

        """
        if owner and not project:
            project = owner
        db_ports = cls.dbapi.get_ports_by_node_id(node_id, limit=limit,
                                                  marker=marker,
                                                  sort_key=sort_key,
                                                  sort_dir=sort_dir,
                                                  project=project)
        return cls._from_db_object_list(context, db_ports)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_portgroup_id(cls, context, portgroup_id, limit=None,
                             marker=None, sort_key=None, sort_dir=None,
                             owner=None, project=None):
        """Return a list of Port objects associated with a given portgroup ID.

        :param context: Security context.
        :param portgroup_id: the ID of the portgroup.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param owner: DEPRECATED a node owner to match against
        :param project: a node owner or lessee to match against
        :returns: a list of :class:`Port` object.

        """
        if owner and not project:
            project = owner
        db_ports = cls.dbapi.get_ports_by_portgroup_id(portgroup_id,
                                                       limit=limit,
                                                       marker=marker,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir,
                                                       project=project)
        return cls._from_db_object_list(context, db_ports)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a Port record in the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: MACAlreadyExists if 'address' column is not unique
        :raises: PortAlreadyExists if 'uuid' column is not unique

        """
        values = self.do_version_changes_for_db()
        db_port = self.dbapi.create_port(values)
        # NOTE(hjensas): To avoid lazy load issue (DetachedInstanceError) in
        # sqlalchemy, get new port the port from the DB to ensure the node_uuid
        # via association_proxy relationship is loaded.
        db_port = self.dbapi.get_port_by_id(db_port['id'])
        self._from_db_object(self._context, self, db_port)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the Port from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: PortNotFound

        """
        self.dbapi.destroy_port(self.uuid)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this Port.

        Updates will be made column by column based on the result
        of self.what_changed().

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: PortNotFound
        :raises: MACAlreadyExists if 'address' column is not unique

        """
        updates = self.do_version_changes_for_db()
        updated_port = self.dbapi.update_port(self.uuid, updates)
        self._from_db_object(self._context, self, updated_port)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Loads updates for this Port.

        Loads a port with the same uuid from the database and
        checks for updated attributes. Updates are applied from
        the loaded port column by column, if there are any updates.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Port(context)
        :raises: PortNotFound

        """
        current = self.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()

    @classmethod
    def supports_physical_network(cls):
        """Return whether the physical_network field is supported.

        :returns: Whether the physical_network field is supported
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        return cls.supports_version((1, 7))

    @classmethod
    def supports_is_smartnic(cls):
        """Return whether is_smartnic field is supported.

        :returns: Whether is_smartnic field is supported
        :raises: ovo_exception.IncompatibleObjectVersion
        """
        return cls.supports_version((1, 9))


@base.IronicObjectRegistry.register
class PortCRUDNotification(notification.NotificationBase):
    """Notification emitted when ironic creates, updates or deletes a port."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('PortCRUDPayload')
    }


@base.IronicObjectRegistry.register
class PortCRUDPayload(notification.NotificationPayloadBase):
    # Version 1.0: Initial version
    # Version 1.1: Add "portgroup_uuid" field
    # Version 1.2: Add "physical_network" field
    # Version 1.3: Add "is_smartnic" field
    # Version 1.4: Add "name" field
    VERSION = '1.4'

    SCHEMA = {
        'address': ('port', 'address'),
        'extra': ('port', 'extra'),
        'local_link_connection': ('port', 'local_link_connection'),
        'pxe_enabled': ('port', 'pxe_enabled'),
        'physical_network': ('port', 'physical_network'),
        'created_at': ('port', 'created_at'),
        'updated_at': ('port', 'updated_at'),
        'uuid': ('port', 'uuid'),
        'is_smartnic': ('port', 'is_smartnic'),
        'name': ('port', 'name'),
    }

    fields = {
        'address': object_fields.MACAddressField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'local_link_connection': object_fields.FlexibleDictField(
            nullable=True),
        'pxe_enabled': object_fields.BooleanField(nullable=True),
        'node_uuid': object_fields.UUIDField(),
        'portgroup_uuid': object_fields.UUIDField(nullable=True),
        'physical_network': object_fields.StringField(nullable=True),
        'created_at': object_fields.DateTimeField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField(),
        'is_smartnic': object_fields.BooleanField(nullable=True,
                                                  default=False),
        'name': object_fields.StringField(nullable=True),
    }

    def __init__(self, port, node_uuid, portgroup_uuid):
        super(PortCRUDPayload, self).__init__(node_uuid=node_uuid,
                                              portgroup_uuid=portgroup_uuid)
        self.populate_schema(port=port)
