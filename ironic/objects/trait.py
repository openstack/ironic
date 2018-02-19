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

from ironic.db import api as db_api
from ironic.objects import base
from ironic.objects import fields as object_fields


@base.IronicObjectRegistry.register
class Trait(base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'node_id': object_fields.StringField(),
        'trait': object_fields.StringField(),
    }

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a Trait record in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Trait(context).
        :raises: InvalidParameterValue if adding the trait would exceed the
            per-node traits limit.
        :raises: NodeNotFound if the node no longer appears in the database.
        """
        values = self.do_version_changes_for_db()
        db_trait = self.dbapi.add_node_trait(
            values['node_id'], values['trait'], values['version'])
        self._from_db_object(self._context, self, db_trait)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def destroy(cls, context, node_id, trait):
        """Delete the Trait from the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Trait(context).
        :param node_id: The id of a node.
        :param trait: A trait string.
        :raises: NodeNotFound if the node no longer appears in the database.
        :raises: NodeTraitNotFound if the trait is not found.
        """
        cls.dbapi.delete_node_trait(node_id, trait)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def exists(cls, context, node_id, trait):
        """Check whether a Trait exists in the DB.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Trait(context).
        :param node_id: The id of a node.
        :param trait: A trait string.
        :returns: True if the trait exists otherwise False.
        :raises: NodeNotFound if the node no longer appears in the database.
        """
        return cls.dbapi.node_trait_exists(node_id, trait)


@base.IronicObjectRegistry.register
class TraitList(base.IronicObjectListBase, base.IronicObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    dbapi = db_api.get_instance()

    fields = {
        'objects': object_fields.ListOfObjectsField('Trait'),
    }

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_node_id(cls, context, node_id):
        """Return all traits for the specified node.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Trait(context).
        :param node_id: The id of a node.
        :raises: NodeNotFound if the node no longer appears in the database.
        """
        db_traits = cls.dbapi.get_node_traits_by_node_id(node_id)
        return object_base.obj_make_list(context, cls(), Trait, db_traits)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def create(cls, context, node_id, traits):
        """Replace all existing traits with the specified list.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Trait(context).
        :param node_id: The id of a node.
        :param traits: List of Strings; traits to set.
        :raises: InvalidParameterValue if adding the trait would exceed the
            per-node traits limit.
        :raises: NodeNotFound if the node no longer appears in the database.
        """
        version = Trait.get_target_version()
        db_traits = cls.dbapi.set_node_traits(node_id, traits, version)
        return object_base.obj_make_list(context, cls(), Trait, db_traits)

    # NOTE(mgoddard): We don't want to enable RPC on this call just yet.
    # Remotable methods can be used in the future to replace current explicit
    # RPC calls.  Implications of calling new remote procedures should be
    # thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def destroy(cls, context, node_id):
        """Delete all traits for the specified node.

        :param context: security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Trait(context).
        :param node_id: The id of a node.
        :raises: NodeNotFound if the node no longer appears in the database.
        """
        cls.dbapi.unset_node_traits(node_id)

    def get_trait_names(self):
        """Return a list of names of the traits in this list."""
        return [t.trait for t in self.objects]
