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

from oslo_utils import uuidutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import node as node_obj


@base.IronicObjectRegistry.register
class Deployment(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = dbapi.get_instance()

    fields = {
        'uuid': object_fields.UUIDField(nullable=True),
        'node_uuid': object_fields.UUIDField(nullable=True),
        'image_checksum': object_fields.StringField(nullable=True),
        'image_ref': object_fields.StringField(nullable=True),
        'kernel_ref': object_fields.StringField(nullable=True),
        'ramdisk_ref': object_fields.StringField(nullable=True),
        'root_device': object_fields.FlexibleDictField(nullable=True),
        'root_gib': object_fields.IntegerField(nullable=True),
        'state': object_fields.StringField(nullable=True),
        'swap_mib': object_fields.IntegerField(nullable=True),
    }

    node_mapping = {
        'instance_uuid': 'uuid',
        'provision_state': 'state',
        'uuid': 'node_uuid',
    }

    instance_info_mapping = {
        'image_checksum': 'image_checksum',
        'image_source': 'image_ref',
        'kernel': 'kernel_ref',
        'ramdisk': 'ramdisk_ref',
        'root_device': 'root_device',
        'root_gb': 'root_gib',
        'swap_mb': 'swap_mib',
    }

    instance_info_mapping_rev = {v: k
                                 for k, v in instance_info_mapping.items()}

    assert (set(node_mapping.values()) | set(instance_info_mapping.values())
            == set(fields))

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """

    @classmethod
    def _from_node_object(cls, context, node):
        """Convert a node into a virtual `Deployment` object."""
        result = cls(context)
        result._update_from_node_object(node)
        return result

    def _update_from_node_object(self, node):
        """Update the Deployment object from the node."""
        for src, dest in self.node_mapping.items():
            setattr(self, dest, getattr(node, src, None))
        for src, dest in self.instance_info_mapping.items():
            setattr(self, dest, node.instance_info.get(src))

    def _update_node_object(self, node):
        """Update the given node object with the changes here."""
        changes = self.obj_get_changes()
        try:
            new_instance_uuid = changes.pop('uuid')
        except KeyError:
            pass
        else:
            node.instance_uuid = new_instance_uuid

        changes.pop('node_uuid', None)
        instance_info = node.instance_info

        for field, value in changes.items():
            # NOTE(dtantsur): only instance_info fields can be updated here.
            try:
                dest = self.instance_info_mapping_rev[field]
            except KeyError:
                # NOTE(dtantsur): this should not happen because of API-level
                # validations, but checking just in case.
                raise exception.BadRequest('Field %s cannot be set or updated'
                                           % changes)
            instance_info[dest] = value

        node.instance_info = instance_info
        return node

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a deployment by its UUID.

        :param cls: the :class:`Deployment`
        :param context: Security context
        :param uuid: The UUID of a deployment.
        :returns: An :class:`Deployment` object.
        :raises: InstanceNotFound

        """
        node = node_obj.Node.get_by_instance_uuid(context, uuid)
        return cls._from_node_object(context, node)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_node_uuid(cls, context, node_uuid):
        """Find a deployment based by its node's UUID.

        :param cls: the :class:`Deployment`
        :param context: Security context
        :param node_uuid: The UUID of a corresponding node.
        :returns: An :class:`Deployment` object.
        :raises: NodeNotFound

        """
        node = node_obj.Node.get_by_uuid(context, node_uuid)
        return cls._from_node_object(context, node)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, filters=None, limit=None, marker=None,
             sort_key=None, sort_dir=None):
        """Return a list of Deployment objects.

        :param cls: the :class:`Deployment`
        :param context: Security context.
        :param filters: Filters to apply.
        :param limit: Maximum number of resources to return in a single result.
        :param marker: Pagination marker for large data sets.
        :param sort_key: Column to sort results by.
        :param sort_dir: Direction to sort. "asc" or "desc".
        :returns: A list of :class:`Deployment` object.
        :raises: InvalidParameterValue

        """
        nodes = node_obj.Node.list(context, filters=filters, limit=limit,
                                   marker=marker, sort_key=sort_key,
                                   sort_dir=sort_dir)
        return [cls._from_node_object(context, node) for node in nodes]

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None, node=None):
        """Create a Deployment.

        Updates the corresponding node under the hood.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Deployment(context)
        :param node: Node object for deployment.
        :raises: InstanceAssociated, NodeAssociated, NodeNotFound

        """
        if node is None:
            node = node_obj.Node.get_by_uuid(self._context, self.node_uuid)
        elif 'node_uuid' in self and self.node_uuid:
            # NOTE(dtantsur): this is only possible if a bug happens on
            # a higher level.
            assert self.node_uuid == node.uuid

        if 'uuid' not in self or not self.uuid:
            self.uuid = uuidutils.generate_uuid()
        node.instance_uuid = self.uuid
        self._update_node_object(node)
        node.save()
        self._update_from_node_object(node)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None, node=None):
        """Delete the Deployment.

        Updates the corresponding node under the hood.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        :param node: Node object for deployment.
        """
        if node is None:
            node = node_obj.Node.get_by_uuid(self._context, self.node_uuid)
        else:
            assert node.uuid == self.node_uuid
        node.instance_uuid = None
        node.instance_info = {}
        node.save()
        self._update_from_node_object(node)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def refresh(self, context=None):
        """Refresh the object by re-fetching from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        """
        current = self.get_by_uuid(self._context, self.uuid)
        self.obj_refresh(current)
        self.obj_reset_changes()
