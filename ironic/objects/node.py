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
from oslo_config import cfg
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
from oslo_utils import versionutils
from oslo_versionedobjects import base as object_base

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.db import api as db_api
from ironic import objects
from ironic.objects import base
from ironic.objects import fields as object_fields
from ironic.objects import notification

REQUIRED_INT_PROPERTIES = ['local_gb', 'cpus', 'memory_mb']

CONF = cfg.CONF
LOG = log.getLogger(__name__)


@base.IronicObjectRegistry.register
class Node(base.IronicObject, object_base.VersionedObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added instance_info
    # Version 1.2: Add get() and get_by_id() and make get_by_uuid()
    #              only work with a uuid
    # Version 1.3: Add create() and destroy()
    # Version 1.4: Add get_by_instance_uuid()
    # Version 1.5: Add list()
    # Version 1.6: Add reserve() and release()
    # Version 1.7: Add conductor_affinity
    # Version 1.8: Add maintenance_reason
    # Version 1.9: Add driver_internal_info
    # Version 1.10: Add name and get_by_name()
    # Version 1.11: Add clean_step
    # Version 1.12: Add raid_config and target_raid_config
    # Version 1.13: Add touch_provisioning()
    # Version 1.14: Add _validate_property_values() and make create()
    #               and save() validate the input of property values.
    # Version 1.15: Add get_by_port_addresses
    # Version 1.16: Add network_interface field
    # Version 1.17: Add resource_class field
    # Version 1.18: Add default setting for network_interface
    # Version 1.19: Add fields: boot_interface, console_interface,
    #               deploy_interface, inspect_interface, management_interface,
    #               power_interface, raid_interface, vendor_interface
    # Version 1.20: Type of network_interface changed to just nullable string
    # Version 1.21: Add storage_interface field
    # Version 1.22: Add rescue_interface field
    # Version 1.23: Add traits field
    # Version 1.24: Add bios_interface field
    # Version 1.25: Add fault field
    # Version 1.26: Add deploy_step field
    # Version 1.27: Add conductor_group field
    # Version 1.28: Add automated_clean field
    # Version 1.29: Add protected and protected_reason fields
    # Version 1.30: Add owner field
    # Version 1.31: Add allocation_id field
    # Version 1.32: Add description field
    # Version 1.33: Add retired and retired_reason fields
    # Version 1.34: Add lessee field
    # Version 1.35: Add network_data field
    # Version 1.36: Add boot_mode and secure_boot fields
    VERSION = '1.36'

    dbapi = db_api.get_instance()

    fields = {
        'id': object_fields.IntegerField(),

        'uuid': object_fields.UUIDField(nullable=True),
        'name': object_fields.StringField(nullable=True),
        'chassis_id': object_fields.IntegerField(nullable=True),
        'instance_uuid': object_fields.UUIDField(nullable=True),

        'driver': object_fields.StringField(nullable=True),
        'driver_info': object_fields.FlexibleDictField(nullable=True),
        'driver_internal_info': object_fields.FlexibleDictField(nullable=True),

        # A clean step dictionary, indicating the current clean step
        # being executed, or None, indicating cleaning is not in progress
        # or has not yet started.
        'clean_step': object_fields.FlexibleDictField(nullable=True),

        # A deploy step dictionary, indicating the current step
        # being executed, or None, indicating deployment is not in progress
        # or has not yet started.
        'deploy_step': object_fields.FlexibleDictField(nullable=True),

        'raid_config': object_fields.FlexibleDictField(nullable=True),
        'target_raid_config': object_fields.FlexibleDictField(nullable=True),

        'instance_info': object_fields.FlexibleDictField(nullable=True),
        'properties': object_fields.FlexibleDictField(nullable=True),
        'reservation': object_fields.StringField(nullable=True),
        # a reference to the id of the conductor service, not its hostname,
        # that has most recently performed some action which could require
        # local state to be maintained (eg, built a PXE config)
        'conductor_affinity': object_fields.IntegerField(nullable=True),
        'conductor_group': object_fields.StringField(nullable=True),

        # One of states.POWER_ON|POWER_OFF|NOSTATE|ERROR
        'power_state': object_fields.StringField(nullable=True),

        # Set to one of states.POWER_ON|POWER_OFF when a power operation
        # starts, and set to NOSTATE when the operation finishes
        # (successfully or unsuccessfully).
        'target_power_state': object_fields.StringField(nullable=True),

        'provision_state': object_fields.StringField(nullable=True),
        'provision_updated_at': object_fields.DateTimeField(nullable=True),
        'target_provision_state': object_fields.StringField(nullable=True),

        'maintenance': object_fields.BooleanField(),
        'maintenance_reason': object_fields.StringField(nullable=True),
        'fault': object_fields.StringField(nullable=True),
        'console_enabled': object_fields.BooleanField(),

        # Any error from the most recent (last) asynchronous transaction
        # that started but failed to finish.
        'last_error': object_fields.StringField(nullable=True),

        # Used by nova to relate the node to a flavor
        'resource_class': object_fields.StringField(nullable=True),

        'inspection_finished_at': object_fields.DateTimeField(nullable=True),
        'inspection_started_at': object_fields.DateTimeField(nullable=True),

        'extra': object_fields.FlexibleDictField(nullable=True),
        'automated_clean': objects.fields.BooleanField(nullable=True),
        'protected': objects.fields.BooleanField(),
        'protected_reason': object_fields.StringField(nullable=True),
        'allocation_id': object_fields.IntegerField(nullable=True),

        'bios_interface': object_fields.StringField(nullable=True),
        'boot_interface': object_fields.StringField(nullable=True),
        'console_interface': object_fields.StringField(nullable=True),
        'deploy_interface': object_fields.StringField(nullable=True),
        'inspect_interface': object_fields.StringField(nullable=True),
        'management_interface': object_fields.StringField(nullable=True),
        'network_interface': object_fields.StringField(nullable=True),
        'power_interface': object_fields.StringField(nullable=True),
        'raid_interface': object_fields.StringField(nullable=True),
        'rescue_interface': object_fields.StringField(nullable=True),
        'storage_interface': object_fields.StringField(nullable=True),
        'vendor_interface': object_fields.StringField(nullable=True),
        'traits': object_fields.ObjectField('TraitList', nullable=True),
        'owner': object_fields.StringField(nullable=True),
        'lessee': object_fields.StringField(nullable=True),
        'description': object_fields.StringField(nullable=True),
        'retired': objects.fields.BooleanField(nullable=True),
        'retired_reason': object_fields.StringField(nullable=True),
        'network_data': object_fields.FlexibleDictField(nullable=True),
        'boot_mode': object_fields.StringField(nullable=True),
        'secure_boot': object_fields.BooleanField(nullable=True),
    }

    def as_dict(self, secure=False, mask_configdrive=True):
        d = super(Node, self).as_dict()
        if secure:
            d['driver_info'] = strutils.mask_dict_password(
                d.get('driver_info', {}), "******")
            iinfo = d.pop('instance_info', {})
            configdrive = iinfo.pop('configdrive', None)
            d['instance_info'] = strutils.mask_dict_password(iinfo, "******")
            if configdrive is not None:
                d['instance_info']['configdrive'] = (
                    "******" if mask_configdrive else configdrive
                )
            d['driver_internal_info'] = strutils.mask_dict_password(
                d.get('driver_internal_info', {}), "******")
        return d

    def _validate_property_values(self, properties):
        """Check if the input of local_gb, cpus and memory_mb are valid.

        :param properties: a dict contains the node's information.
        """
        if not properties:
            return
        invalid_msgs_list = []
        for param in REQUIRED_INT_PROPERTIES:
            value = properties.get(param)
            if value is None:
                continue
            try:
                int_value = int(value)
                if int_value < 0:
                    raise ValueError("Value must be non-negative")
            except (ValueError, TypeError):
                msg = (('%(param)s=%(value)s') %
                       {'param': param, 'value': value})
                invalid_msgs_list.append(msg)

        if invalid_msgs_list:
            msg = (_('The following properties for node %(node)s '
                     'should be non-negative integers, '
                     'but provided values are: %(msgs)s') %
                   {'node': self.uuid, 'msgs': ', '.join(invalid_msgs_list)})
            raise exception.InvalidParameterValue(msg)

    def _set_from_db_object(self, context, db_object, fields=None):
        use_fields = set(fields or self.fields) - {'traits'}
        super(Node, self)._set_from_db_object(context, db_object, use_fields)
        if not fields or 'traits' in fields:
            self.traits = object_base.obj_make_list(
                context, objects.TraitList(context),
                objects.Trait, db_object['traits'],
                fields=['trait', 'version'])
            self.traits.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get(cls, context, node_id):
        """Find a node based on its id or uuid and return a Node object.

        :param context: Security context
        :param node_id: the id *or* uuid of a node.
        :returns: a :class:`Node` object.
        """
        if strutils.is_int_like(node_id):
            return cls.get_by_id(context, node_id)
        elif uuidutils.is_uuid_like(node_id):
            return cls.get_by_uuid(context, node_id)
        else:
            raise exception.InvalidIdentity(identity=node_id)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_id(cls, context, node_id):
        """Find a node based on its integer ID and return a Node object.

        :param cls: the :class:`Node`
        :param context: Security context
        :param node_id: the ID of a node.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_id(node_id)
        node = cls._from_db_object(context, cls(), db_node)
        return node

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_uuid(cls, context, uuid):
        """Find a node based on UUID and return a Node object.

        :param cls: the :class:`Node`
        :param context: Security context
        :param uuid: the UUID of a node.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_uuid(uuid)
        node = cls._from_db_object(context, cls(), db_node)
        return node

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_name(cls, context, name):
        """Find a node based on name and return a Node object.

        :param cls: the :class:`Node`
        :param context: Security context
        :param name: the logical name of a node.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_name(name)
        node = cls._from_db_object(context, cls(), db_node)
        return node

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        """Find a node based on the instance UUID and return a Node object.

        :param cls: the :class:`Node`
        :param context: Security context
        :param uuid: the UUID of the instance.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_instance(instance_uuid)
        node = cls._from_db_object(context, cls(), db_node)
        return node

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def list(cls, context, limit=None, marker=None, sort_key=None,
             sort_dir=None, filters=None, fields=None):
        """Return a list of Node objects.

        :param cls: the :class:`Node`
        :param context: Security context.
        :param limit: maximum number of resources to return in a single result.
        :param marker: pagination marker for large data sets.
        :param sort_key: column to sort results by.
        :param sort_dir: direction to sort. "asc" or "desc".
        :param filters: Filters to apply.
        :param fields: Requested fields to be returned. Please note, some
                       fields are mandatory for the data model and are
                       automatically included. These are: id, version,
                       updated_at, created_at, owner, and lessee.
        :returns: a list of :class:`Node` object.
        """
        if fields:
            # All requests must include version, updated_at, created_at
            # owner, and lessee to support access controls and database
            # version model updates. Driver and conductor_group are required
            # for conductor mapping.
            target_fields = ['id'] + fields[:] + ['version', 'updated_at',
                                                  'created_at', 'owner',
                                                  'lessee', 'driver',
                                                  'conductor_group']
        else:
            target_fields = None

        db_nodes = cls.dbapi.get_node_list(filters=filters, limit=limit,
                                           marker=marker, sort_key=sort_key,
                                           sort_dir=sort_dir,
                                           fields=target_fields)
        return cls._from_db_object_list(context, db_nodes, target_fields)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def reserve(cls, context, tag, node_id):
        """Get and reserve a node.

        To prevent other ManagerServices from manipulating the given
        Node while a Task is performed, mark it reserved by this host.

        :param cls: the :class:`Node`
        :param context: Security context.
        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node ID or UUID.
        :raises: NodeNotFound if the node is not found.
        :returns: a :class:`Node` object.

        """
        db_node = cls.dbapi.reserve_node(tag, node_id)
        node = cls._from_db_object(context, cls(), db_node)
        return node

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable_classmethod
    @classmethod
    def release(cls, context, tag, node_id):
        """Release the reservation on a node.

        :param context: Security context.
        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id or uuid.
        :raises: NodeNotFound if the node is not found.

        """
        cls.dbapi.release_node(tag, node_id)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def create(self, context=None):
        """Create a Node record in the DB.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        node before updates are made.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        :raises: InvalidParameterValue if some property values are invalid.
        """
        values = self.do_version_changes_for_db()
        self._validate_property_values(values.get('properties'))
        self._validate_and_remove_traits(values)
        self._validate_and_format_conductor_group(values)
        db_node = self.dbapi.create_node(values)
        self._from_db_object(self._context, self, db_node)

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def destroy(self, context=None):
        """Delete the Node from the DB.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        """
        self.dbapi.destroy_node(self.uuid)
        self.obj_reset_changes()

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def save(self, context=None):
        """Save updates to this Node.

        Column-wise updates will be made based on the result of
        self.what_changed(). If target_power_state is provided,
        it will be checked against the in-database copy of the
        node before updates are made.

        :param context: Security context. NOTE: This should only
                        be used internally by the indirection_api.
                        Unfortunately, RPC requires context as the first
                        argument, even though we don't use it.
                        A context should be set when instantiating the
                        object, e.g.: Node(context)
        :raises: InvalidParameterValue if some property values are invalid.
        """

        for attr_name in ('last_error', 'maintenance_reason'):
            attr_value = getattr(self, attr_name, '')
            if (attr_value and isinstance(attr_value, str)
                    and len(attr_value) > CONF.log_in_db_max_size):
                LOG.info('Truncating too long %s to %s characters for node %s',
                         attr_name, CONF.log_in_db_max_size, self.uuid)
                setattr(self, attr_name,
                        attr_value[0:CONF.log_in_db_max_size])

        updates = self.do_version_changes_for_db()
        self._validate_property_values(updates.get('properties'))
        self._validate_and_remove_traits(updates)
        self._validate_and_format_conductor_group(updates)
        db_node = self.dbapi.update_node(self.uuid, updates)
        self._from_db_object(self._context, self, db_node)

    @staticmethod
    def _validate_and_remove_traits(fields):
        """Validate traits in fields for create or update, remove if present.

        :param fields: a dict of Node fields for create or update.
        :raises: BadRequest if fields contains a traits that are not None.
        """
        if 'traits' in fields:
            # NOTE(mgoddard): Traits should be updated via the node
            # object's traits field, which is itself an object. We shouldn't
            # get here with changes to traits, as this should be handled by the
            # API. When services are pinned to Pike, we can get here with
            # traits set to None in updates, due to changes made to the object
            # in _convert_to_version.
            if fields['traits']:
                # NOTE(mgoddard): We shouldn't get here as this should be
                # handled by the API.
                raise exception.BadRequest()
            fields.pop('traits')

    def _validate_and_format_conductor_group(self, fields):
        """Validate conductor_group and format it for our use.

        Currently formatting is just lowercasing it.

        :param fields: a dict of Node fields for create or update.
        :raises: InvalidConductorGroup if validation fails.
        """
        if 'conductor_group' in fields:
            utils.validate_conductor_group(fields['conductor_group'])
            fields['conductor_group'] = fields['conductor_group'].lower()

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

    # NOTE(xek): We don't want to enable RPC on this call just yet. Remotable
    # methods can be used in the future to replace current explicit RPC calls.
    # Implications of calling new remote procedures should be thought through.
    # @object_base.remotable
    def touch_provisioning(self, context=None):
        """Touch the database record to mark the provisioning as alive."""
        self.dbapi.touch_node_provisioning(self.id)

    @classmethod
    def get_by_port_addresses(cls, context, addresses):
        """Get a node by associated port addresses.

        :param cls: the :class:`Node`
        :param context: Security context.
        :param addresses: A list of port addresses.
        :raises: NodeNotFound if the node is not found.
        :returns: a :class:`Node` object.
        """
        db_node = cls.dbapi.get_node_by_port_addresses(addresses)
        node = cls._from_db_object(context, cls(), db_node)
        return node

    def _convert_deploy_step_field(self, target_version,
                                   remove_unavailable_fields=True):
        # NOTE(rloo): Typically we set the value to None. However,
        # deploy_step is a FlexibleDictField. Setting it to None
        # causes it to be set to {} under-the-hood. So I am being
        # explicit about that here.
        step_is_set = self.obj_attr_is_set('deploy_step')
        if target_version >= (1, 26):
            if not step_is_set:
                self.deploy_step = {}
        elif step_is_set:
            if remove_unavailable_fields:
                delattr(self, 'deploy_step')
            elif self.deploy_step:
                self.deploy_step = {}

    def _convert_conductor_group_field(self, target_version,
                                       remove_unavailable_fields=True):
        # NOTE(jroll): The default conductor_group is "", not None
        is_set = self.obj_attr_is_set('conductor_group')
        if target_version >= (1, 27):
            if not is_set:
                self.conductor_group = ''
        elif is_set:
            if remove_unavailable_fields:
                delattr(self, 'conductor_group')
            elif self.conductor_group:
                self.conductor_group = ''

    def _convert_network_data_field(self, target_version,
                                    remove_unavailable_fields=True):
        # NOTE(etingof): The default value for `network_data` is an empty
        # dict. Therefore we can't use generic version adjustment
        # routine.
        field_is_set = self.obj_attr_is_set('network_data')
        if target_version >= (1, 35):
            if not field_is_set:
                self.network_data = {}
        elif field_is_set:
            if remove_unavailable_fields:
                delattr(self, 'network_data')
            elif self.network_data:
                self.network_data = {}

    # NOTE (yolanda): new method created to avoid repeating code in
    # _convert_to_version, and to avoid pep8 too complex error
    def _adjust_field_to_version(self, field_name, field_default_value,
                                 target_version, major, minor,
                                 remove_unavailable_fields):
        field_is_set = self.obj_attr_is_set(field_name)
        if target_version >= (major, minor):
            # target version supports the major/minor specified
            if not field_is_set:
                # set it to its default value if it is not set
                setattr(self, field_name, field_default_value)
        elif field_is_set:
            # target version does not support the field, and it is set
            if remove_unavailable_fields:
                # (De)serialising: remove unavailable fields
                delattr(self, field_name)
            elif getattr(self, field_name) is not field_default_value:
                # DB: set unavailable field to the default value
                setattr(self, field_name, field_default_value)

    def _convert_to_version(self, target_version,
                            remove_unavailable_fields=True):
        """Convert to the target version.

        Convert the object to the target version. The target version may be
        the same, older, or newer than the version of the object. This is
        used for DB interactions as well as for serialization/deserialization.

        Version 1.22: rescue_interface field was added. Its default value is
            None. For versions prior to this, it should be set to None (or
            removed).
        Version 1.23: traits field was added. Its default value is
            None. For versions prior to this, it should be set to None (or
            removed).
        Version 1.24: bios_interface field was added. Its default value is
            None. For versions prior to this, it should be set to None (or
            removed).
        Version 1.25: fault field was added. For versions prior to
            this, it should be removed.
        Version 1.26: deploy_step field was added. For versions prior to
            this, it should be removed.
        Version 1.27: conductor_group field was added. For versions prior to
            this, it should be removed.
        Version 1.28: automated_clean was added. For versions prior to this, it
            should be set to None (or removed).
        Version 1.29: protected was added. For versions prior to this, it
            should be set to False (or removed).
        Version 1.30: owner was added. For versions prior to this, it should be
            set to None or removed.
        Version 1.31: allocation_id was added. For versions prior to this, it
            should be set to None (or removed).
        Version 1.32: description was added. For versions prior to this, it
            should be set to None (or removed).
        Version 1.33: retired was added. For versions prior to this, it
            should be set to False (or removed).
        Version 1.34: lessee was added. For versions prior to this, it should
            be set to None or removed.
        Version 1.35: network_data was added. For versions prior to this, it
            should be set to empty dict (or removed).
        Version 1.36: boot_mode, secure_boot were was added. Defaults are None.
            For versions prior to this, it should be set to None or removed.

        :param target_version: the desired version of the object
        :param remove_unavailable_fields: True to remove fields that are
            unavailable in the target version; set this to True when
            (de)serializing. False to set the unavailable fields to appropriate
            values; set this to False for DB interactions.
        """
        target_version = versionutils.convert_version_to_tuple(target_version)

        # Convert the different fields depending on version
        fields = [('rescue_interface', 22), ('traits', 23),
                  ('bios_interface', 24), ('fault', 25),
                  ('automated_clean', 28), ('protected_reason', 29),
                  ('owner', 30), ('allocation_id', 31), ('description', 32),
                  ('retired_reason', 33), ('lessee', 34), ('boot_mode', 36),
                  ('secure_boot', 36)]

        for name, minor in fields:
            self._adjust_field_to_version(name, None, target_version,
                                          1, minor, remove_unavailable_fields)

        # NOTE(dtantsur): the default is False for protected
        self._adjust_field_to_version('protected', False, target_version,
                                      1, 29, remove_unavailable_fields)

        self._convert_deploy_step_field(target_version,
                                        remove_unavailable_fields)
        self._convert_conductor_group_field(target_version,
                                            remove_unavailable_fields)

        self._adjust_field_to_version('retired', False, target_version,
                                      1, 33, remove_unavailable_fields)

        self._convert_network_data_field(target_version,
                                         remove_unavailable_fields)


@base.IronicObjectRegistry.register
class NodePayload(notification.NotificationPayloadBase):
    """Base class used for all notification payloads about a Node object."""
    # NOTE: This payload does not include the Node fields "chassis_id",
    # "driver_info", "driver_internal_info", "instance_info", "raid_config",
    # "network_data", "reservation", or "target_raid_config". These were
    # excluded for reasons including:
    # - increased complexity needed for creating the payload
    # - sensitive information in the fields that shouldn't be exposed to
    #   external services
    # - being internal-only or hardware-related fields
    SCHEMA = {
        'clean_step': ('node', 'clean_step'),
        'conductor_group': ('node', 'conductor_group'),
        'console_enabled': ('node', 'console_enabled'),
        'created_at': ('node', 'created_at'),
        'deploy_step': ('node', 'deploy_step'),
        'description': ('node', 'description'),
        'driver': ('node', 'driver'),
        'extra': ('node', 'extra'),
        'boot_mode': ('node', 'boot_mode'),
        'secure_boot': ('node', 'secure_boot'),
        'inspection_finished_at': ('node', 'inspection_finished_at'),
        'inspection_started_at': ('node', 'inspection_started_at'),
        'instance_uuid': ('node', 'instance_uuid'),
        'last_error': ('node', 'last_error'),
        'maintenance': ('node', 'maintenance'),
        'maintenance_reason': ('node', 'maintenance_reason'),
        'fault': ('node', 'fault'),
        'name': ('node', 'name'),
        'bios_interface': ('node', 'bios_interface'),
        'boot_interface': ('node', 'boot_interface'),
        'console_interface': ('node', 'console_interface'),
        'deploy_interface': ('node', 'deploy_interface'),
        'inspect_interface': ('node', 'inspect_interface'),
        'management_interface': ('node', 'management_interface'),
        'network_interface': ('node', 'network_interface'),
        'power_interface': ('node', 'power_interface'),
        'raid_interface': ('node', 'raid_interface'),
        'rescue_interface': ('node', 'rescue_interface'),
        'storage_interface': ('node', 'storage_interface'),
        'vendor_interface': ('node', 'vendor_interface'),
        'owner': ('node', 'owner'),
        'lessee': ('node', 'lessee'),
        'power_state': ('node', 'power_state'),
        'properties': ('node', 'properties'),
        'protected': ('node', 'protected'),
        'protected_reason': ('node', 'protected_reason'),
        'provision_state': ('node', 'provision_state'),
        'provision_updated_at': ('node', 'provision_updated_at'),
        'resource_class': ('node', 'resource_class'),
        'retired': ('node', 'retired'),
        'retired_reason': ('node', 'retired_reason'),
        'target_power_state': ('node', 'target_power_state'),
        'target_provision_state': ('node', 'target_provision_state'),
        'updated_at': ('node', 'updated_at'),
        'uuid': ('node', 'uuid')
    }

    # Version 1.0: Initial version, based off of Node version 1.18.
    # Version 1.1: Type of network_interface changed to just nullable string
    #              similar to version 1.20 of Node.
    # Version 1.2: Add nullable to console_enabled and maintenance.
    # Version 1.3: Add dynamic interfaces fields exposed via API.
    # Version 1.4: Add storage interface field exposed via API.
    # Version 1.5: Add rescue interface field exposed via API.
    # Version 1.6: Add traits field exposed via API.
    # Version 1.7: Add fault field exposed via API.
    # Version 1.8: Add bios interface field exposed via API.
    # Version 1.9: Add deploy_step field exposed via API.
    # Version 1.10: Add conductor_group field exposed via API.
    # Version 1.11: Add protected and protected_reason fields exposed via API.
    # Version 1.12: Add node owner field.
    # Version 1.13: Add description field.
    # Version 1.14: Add retired and retired_reason fields exposed via API.
    # Version 1.15: Add node lessee field.
    # Version 1.16: Add boot_mode and secure_boot fields.
    VERSION = '1.16'
    fields = {
        'clean_step': object_fields.FlexibleDictField(nullable=True),
        'conductor_group': object_fields.StringField(nullable=True),
        'console_enabled': object_fields.BooleanField(nullable=True),
        'created_at': object_fields.DateTimeField(nullable=True),
        'deploy_step': object_fields.FlexibleDictField(nullable=True),
        'description': object_fields.StringField(nullable=True),
        'driver': object_fields.StringField(nullable=True),
        'extra': object_fields.FlexibleDictField(nullable=True),
        'boot_mode': object_fields.StringField(nullable=True),
        'secure_boot': object_fields.BooleanField(nullable=True),
        'inspection_finished_at': object_fields.DateTimeField(nullable=True),
        'inspection_started_at': object_fields.DateTimeField(nullable=True),
        'instance_uuid': object_fields.UUIDField(nullable=True),
        'last_error': object_fields.StringField(nullable=True),
        'maintenance': object_fields.BooleanField(nullable=True),
        'maintenance_reason': object_fields.StringField(nullable=True),
        'fault': object_fields.StringField(nullable=True),
        'bios_interface': object_fields.StringField(nullable=True),
        'boot_interface': object_fields.StringField(nullable=True),
        'console_interface': object_fields.StringField(nullable=True),
        'deploy_interface': object_fields.StringField(nullable=True),
        'inspect_interface': object_fields.StringField(nullable=True),
        'management_interface': object_fields.StringField(nullable=True),
        'network_interface': object_fields.StringField(nullable=True),
        'power_interface': object_fields.StringField(nullable=True),
        'raid_interface': object_fields.StringField(nullable=True),
        'rescue_interface': object_fields.StringField(nullable=True),
        'storage_interface': object_fields.StringField(nullable=True),
        'vendor_interface': object_fields.StringField(nullable=True),
        'name': object_fields.StringField(nullable=True),
        'owner': object_fields.StringField(nullable=True),
        'lessee': object_fields.StringField(nullable=True),
        'power_state': object_fields.StringField(nullable=True),
        'properties': object_fields.FlexibleDictField(nullable=True),
        'protected': object_fields.BooleanField(nullable=True),
        'protected_reason': object_fields.StringField(nullable=True),
        'provision_state': object_fields.StringField(nullable=True),
        'provision_updated_at': object_fields.DateTimeField(nullable=True),
        'resource_class': object_fields.StringField(nullable=True),
        'retired': object_fields.BooleanField(nullable=True),
        'retired_reason': object_fields.StringField(nullable=True),
        'target_power_state': object_fields.StringField(nullable=True),
        'target_provision_state': object_fields.StringField(nullable=True),
        'traits': object_fields.ListOfStringsField(nullable=True),
        'updated_at': object_fields.DateTimeField(nullable=True),
        'uuid': object_fields.UUIDField()
    }

    def __init__(self, node, **kwargs):
        super(NodePayload, self).__init__(**kwargs)
        self.populate_schema(node=node)
        # NOTE(mgoddard): Populate traits with a list of trait names, rather
        # than the TraitList object.
        if node.obj_attr_is_set('traits') and node.traits is not None:
            self.traits = node.traits.get_trait_names()
        else:
            self.traits = []


@base.IronicObjectRegistry.register
class NodeSetPowerStateNotification(notification.NotificationBase):
    """Notification emitted when ironic changes a node's power state."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('NodeSetPowerStatePayload')
    }


@base.IronicObjectRegistry.register
class NodeSetPowerStatePayload(NodePayload):
    """Payload schema for when ironic changes a node's power state."""
    # Version 1.0: Initial version
    # Version 1.1: Parent NodePayload version 1.1
    # Version 1.2: Parent NodePayload version 1.2
    # Version 1.3: Parent NodePayload version 1.3
    # Version 1.4: Parent NodePayload version 1.4
    # Version 1.5: Parent NodePayload version 1.5
    # Version 1.6: Parent NodePayload version 1.6
    # Version 1.7: Parent NodePayload version 1.7
    # Version 1.8: Parent NodePayload version 1.8
    # Version 1.9: Parent NodePayload version 1.9
    # Version 1.10: Parent NodePayload version 1.10
    # Version 1.11: Parent NodePayload version 1.11
    # Version 1.12: Parent NodePayload version 1.12
    # Version 1.13: Parent NodePayload version 1.13
    # Version 1.14: Parent NodePayload version 1.14
    # Version 1.15: Parent NodePayload version 1.15
    # Version 1.16: Parent NodePayload version 1.16
    VERSION = '1.16'

    fields = {
        # "to_power" indicates the future target_power_state of the node. A
        # separate field from target_power_state is used so that the
        # baremetal.node.power_set.start notification, which is sent before
        # target_power_state is set on the node, has information about what
        # state the conductor will attempt to set on the node.
        'to_power': object_fields.StringField(nullable=True)
    }

    def __init__(self, node, to_power):
        super(NodeSetPowerStatePayload, self).__init__(
            node, to_power=to_power)


@base.IronicObjectRegistry.register
class NodeCorrectedPowerStateNotification(notification.NotificationBase):
    """Notification for when a node's power state is corrected in the database.

       This notification is emitted when ironic detects that the actual power
       state on a bare metal hardware is different from the power state on an
       ironic node (DB). This notification is emitted after the database is
       updated to reflect this correction.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('NodeCorrectedPowerStatePayload')
    }


@base.IronicObjectRegistry.register
class NodeCorrectedPowerStatePayload(NodePayload):
    """Notification payload schema for when a node's power state is corrected.

       "from_power" indicates the previous power state on the ironic node
       before the node was updated.
    """
    # Version 1.0: Initial version
    # Version 1.1: Parent NodePayload version 1.1
    # Version 1.2: Parent NodePayload version 1.2
    # Version 1.3: Parent NodePayload version 1.3
    # Version 1.4: Parent NodePayload version 1.4
    # Version 1.5: Parent NodePayload version 1.5
    # Version 1.6: Parent NodePayload version 1.6
    # Version 1.7: Parent NodePayload version 1.7
    # Version 1.8: Parent NodePayload version 1.8
    # Version 1.9: Parent NodePayload version 1.9
    # Version 1.10: Parent NodePayload version 1.10
    # Version 1.11: Parent NodePayload version 1.11
    # Version 1.12: Parent NodePayload version 1.12
    # Version 1.13: Parent NodePayload version 1.13
    # Version 1.14: Parent NodePayload version 1.14
    # Version 1.15: Parent NodePayload version 1.15
    # Version 1.16: Parent NodePayload version 1.16
    VERSION = '1.16'

    fields = {
        'from_power': object_fields.StringField(nullable=True)
    }

    def __init__(self, node, from_power):
        super(NodeCorrectedPowerStatePayload, self).__init__(
            node, from_power=from_power)


@base.IronicObjectRegistry.register
class NodeSetProvisionStateNotification(notification.NotificationBase):
    """Notification emitted when ironic changes a node provision state."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('NodeSetProvisionStatePayload')
    }


@base.IronicObjectRegistry.register
class NodeSetProvisionStatePayload(NodePayload):
    """Payload schema for when ironic changes a node provision state."""
    # Version 1.0: Initial version
    # Version 1.1: Parent NodePayload version 1.1
    # Version 1.2: Parent NodePayload version 1.2
    # Version 1.3: Parent NodePayload version 1.3
    # Version 1.4: Parent NodePayload version 1.4
    # Version 1.6: Parent NodePayload version 1.6
    # Version 1.7: Parent NodePayload version 1.7
    # Version 1.8: Parent NodePayload version 1.8
    # Version 1.9: Parent NodePayload version 1.9
    # Version 1.10: Parent NodePayload version 1.10
    # Version 1.11: Parent NodePayload version 1.11
    # Version 1.12: Parent NodePayload version 1.12
    # Version 1.13: Parent NodePayload version 1.13
    # Version 1.14: Parent NodePayload version 1.14
    # Version 1.15: Parent NodePayload version 1.15
    # Version 1.16: add driver_internal_info
    # Version 1.17: Parent NodePayload version 1.16
    VERSION = '1.17'

    SCHEMA = dict(NodePayload.SCHEMA,
                  **{'instance_info': ('node', 'instance_info'),
                     'driver_internal_info': ('node', 'driver_internal_info')})

    fields = {
        'instance_info': object_fields.FlexibleDictField(nullable=True),
        'driver_internal_info': object_fields.FlexibleDictField(nullable=True),
        'event': object_fields.StringField(nullable=True),
        'previous_provision_state': object_fields.StringField(nullable=True),
        'previous_target_provision_state':
            object_fields.StringField(nullable=True)
    }

    def __init__(self, node, prev_state, prev_target, event):
        super(NodeSetProvisionStatePayload, self).__init__(
            node, event=event, previous_provision_state=prev_state,
            previous_target_provision_state=prev_target)


@base.IronicObjectRegistry.register
class NodeCRUDNotification(notification.NotificationBase):
    """Notification emitted when ironic creates, updates or deletes a node."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('NodeCRUDPayload')
    }


@base.IronicObjectRegistry.register
class NodeCRUDPayload(NodePayload):
    """Payload schema for when ironic creates, updates or deletes a node."""
    # Version 1.0: Initial version
    # Version 1.1: Parent NodePayload version 1.3
    # Version 1.2: Parent NodePayload version 1.4
    # Version 1.3: Parent NodePayload version 1.5
    # Version 1.4: Parent NodePayload version 1.6
    # Version 1.5: Parent NodePayload version 1.7
    # Version 1.6: Parent NodePayload version 1.8
    # Version 1.7: Parent NodePayload version 1.9
    # Version 1.8: Parent NodePayload version 1.10
    # Version 1.9: Parent NodePayload version 1.11
    # Version 1.10: Parent NodePayload version 1.12
    # Version 1.11: Parent NodePayload version 1.13
    # Version 1.12: Parent NodePayload version 1.14
    # Version 1.13: Parent NodePayload version 1.15
    # Version 1.14: Parent NodePayload version 1.16
    VERSION = '1.14'

    SCHEMA = dict(NodePayload.SCHEMA,
                  **{'instance_info': ('node', 'instance_info'),
                     'driver_info': ('node', 'driver_info')})

    fields = {
        'chassis_uuid': object_fields.UUIDField(nullable=True),
        'instance_info': object_fields.FlexibleDictField(nullable=True),
        'driver_info': object_fields.FlexibleDictField(nullable=True)
    }

    def __init__(self, node, chassis_uuid):
        super(NodeCRUDPayload, self).__init__(node, chassis_uuid=chassis_uuid)


@base.IronicObjectRegistry.register
class NodeMaintenanceNotification(notification.NotificationBase):
    """Notification emitted when maintenance state changed via API."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('NodePayload')
    }


@base.IronicObjectRegistry.register
class NodeConsoleNotification(notification.NotificationBase):
    """Notification emitted when node console state changed."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': object_fields.ObjectField('NodePayload')
    }
