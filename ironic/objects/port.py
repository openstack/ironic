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

from oslo_utils import strutils
from oslo_utils import uuidutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.common import utils
from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields


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
    VERSION = '1.6'

    dbapi = dbapi.get_instance()

    fields = {
        'id': object_fields.IntegerField(),
        'uuid': object_fields.UUIDField(nullable=True),
        'node_id': object_fields.IntegerField(nullable=True),
        'address': object_fields.MACAddressField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'local_link_connection': object_fields.FlexibleDictField(
            nullable=True),
        'portgroup_id': object_fields.IntegerField(nullable=True),
        'pxe_enabled': object_fields.BooleanField(),
        'internal_info': object_fields.FlexibleDictField(nullable=True),
    }

    @staticmethod
    def _from_db_object_list(db_objects, cls, context):
        """Converts a list of database entities to a list of formal objects."""
        return [Port._from_db_object(cls(context), obj) for obj in db_objects]

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, port_id):
        """Find a port.

        Find a port based on its id or uuid or MAC address and return a Port
        object.

        :param port_id: the id *or* uuid *or* MAC address of a port.
        :returns: a :class:`Port` object.
        :raises: InvalidIdentity

        """
        if strutils.is_int_like(port_id):
            return cls.get_by_id(context, port_id)
        elif uuidutils.is_uuid_like(port_id):
            return cls.get_by_uuid(context, port_id)
        elif utils.is_valid_mac(port_id):
            return cls.get_by_address(context, port_id)
        else:
            raise exception.InvalidIdentity(identity=port_id)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, port_id):
        """Find a port based on its integer id and return a Port object.

        :param port_id: the id of a port.
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        db_port = cls.dbapi.get_port_by_id(port_id)
        port = Port._from_db_object(cls(context), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a port based on uuid and return a :class:`Port` object.

        :param uuid: the uuid of a port.
        :param context: Security context
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        db_port = cls.dbapi.get_port_by_uuid(uuid)
        port = Port._from_db_object(cls(context), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_address(cls, context, address):
        """Find a port based on address and return a :class:`Port` object.

        :param address: the address of a port.
        :param context: Security context
        :returns: a :class:`Port` object.
        :raises: PortNotFound

        """
        db_port = cls.dbapi.get_port_by_address(address)
        port = Port._from_db_object(cls(context), db_port)
        return port

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None,
             sort_key=None, sort_dir=None):
        """Return a list of Port objects.

        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`Port` object.
        :raises: InvalidParameterValue

        """
        db_ports = cls.dbapi.get_port_list(limit=limit,
                                           marker=marker,
                                           sort_key=sort_key,
                                           sort_dir=sort_dir)
        return Port._from_db_object_list(db_ports, cls, context)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_node_id(cls, context, node_id, limit=None, marker=None,
                        sort_key=None, sort_dir=None):
        """Return a list of Port objects associated with a given node ID.

        :param context: Security context.
        :param node_id: the ID of the node.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`Port` object.

        """
        db_ports = cls.dbapi.get_ports_by_node_id(node_id, limit=limit,
                                                  marker=marker,
                                                  sort_key=sort_key,
                                                  sort_dir=sort_dir)
        return Port._from_db_object_list(db_ports, cls, context)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list_by_portgroup_id(cls, context, portgroup_id, limit=None,
                             marker=None, sort_key=None, sort_dir=None):
        """Return a list of Port objects associated with a given portgroup ID.

        :param context: Security context.
        :param portgroup_id: the ID of the portgroup.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :returns: a list of :class:`Port` object.

        """
        db_ports = cls.dbapi.get_ports_by_portgroup_id(portgroup_id,
                                                       limit=limit,
                                                       marker=marker,
                                                       sort_key=sort_key,
                                                       sort_dir=sort_dir)
        return Port._from_db_object_list(db_ports, cls, context)

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
        values = self.obj_get_changes()
        db_port = self.dbapi.create_port(values)
        self._from_db_object(self, db_port)

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
        updates = self.obj_get_changes()
        updated_port = self.dbapi.update_port(self.uuid, updates)
        self._from_db_object(self, updated_port)

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
        current = self.__class__.get_by_uuid(self._context, uuid=self.uuid)
        self.obj_refresh(current)
