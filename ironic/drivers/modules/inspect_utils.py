# Copyright 2018 Red Hat, Inc.
# All Rights Reserved.
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

from oslo_log import log as logging
from oslo_utils import netutils
import swiftclient.exceptions

from ironic.common import exception
from ironic.common import swift
from ironic.conf import CONF
from ironic import objects
from ironic.objects import node_inventory

LOG = logging.getLogger(__name__)
_OBJECT_NAME_PREFIX = 'inspector_data'


def create_ports_if_not_exist(task, macs=None):
    """Create ironic ports from MAC addresses data dict.

    Creates ironic ports from MAC addresses data returned with inspection or
    as requested by operator. Helper argument to detect the MAC address
    ``get_mac_address`` defaults to 'value' part of MAC address dict key-value
    pair.

    :param task: A TaskManager instance.
    :param macs: A sequence of MAC addresses. If ``None``, fetched from
        the task's management interface.
    """
    if macs is None:
        macs = task.driver.management.get_mac_addresses(task)
        if not macs:
            LOG.warning("Not attempting to create any port as no NICs "
                        "were discovered in 'enabled' state for node %s",
                        task.node.uuid)
            return

    node = task.node
    for mac in macs:
        if not netutils.is_valid_mac(mac):
            LOG.warning("Ignoring NIC address %(address)s for node %(node)s "
                        "because it is not a valid MAC",
                        {'address': mac, 'node': node.uuid})
            continue

        port_dict = {'address': mac, 'node_id': node.id}
        port = objects.Port(task.context, **port_dict)

        try:
            port.create()
            LOG.info("Port created for MAC address %(address)s for node "
                     "%(node)s", {'address': mac, 'node': node.uuid})
        except exception.MACAlreadyExists:
            LOG.info("Port already exists for MAC address %(address)s "
                     "for node %(node)s", {'address': mac, 'node': node.uuid})


def clean_up_swift_entries(task):
    """Delete swift entries containing inspection data.

    Delete swift entries related to the node in task.node containing
    inspection data. The entries are
    ``inspector_data-<task.node.uuid>-inventory`` for hardware inventory and
    similar for ``-plugin`` containing the rest of the inspection data.

    :param task: A TaskManager instance.
    """
    if CONF.inventory.data_backend != 'swift':
        return
    swift_api = swift.SwiftAPI()
    container = CONF.inventory.swift_data_container
    inventory_obj_name = f'{_OBJECT_NAME_PREFIX}-{task.node.uuid}-inventory'
    plugin_obj_name = f'{_OBJECT_NAME_PREFIX}-{task.node.uuid}-plugin'
    try:
        swift_api.delete_object(inventory_obj_name, container)
    except swiftclient.exceptions.ClientException as e:
        if e.http_status != 404:
            LOG.error("Object %(obj)s in container %(cont)s with inventory "
                      "for node %(node)s failed to be deleted: %(e)s",
                      {'obj': inventory_obj_name, 'node': task.node.uuid,
                       'e': e, 'cont': container})
            raise exception.SwiftObjectStillExists(obj=inventory_obj_name,
                                                   node=task.node.uuid)
    try:
        swift_api.delete_object(plugin_obj_name, container)
    except swiftclient.exceptions.ClientException as e:
        if e.http_status != 404:
            LOG.error("Object %(obj)s in container %(cont)s with plugin data "
                      "for node %(node)s failed to be deleted: %(e)s",
                      {'obj': plugin_obj_name, 'node': task.node.uuid,
                       'e': e, 'cont': container})
            raise exception.SwiftObjectStillExists(obj=plugin_obj_name,
                                                   node=task.node.uuid)


def store_inspection_data(node, inventory, plugin_data, context):
    """Store inspection data.

    Store the inspection data for a node. The storage is either the database
    or the Object Storage API (swift/radosgw) as configured.

    :param node: the Ironic node that the inspection data is about
    :param inventory: the inventory to store
    :param plugin_data: the plugin data (if any) to store
    :param context: an admin context
    """
    # If store_data == 'none', do not store the data
    store_data = CONF.inventory.data_backend
    if store_data == 'none':
        LOG.debug('Inspection data storage is disabled, the data will '
                  'not be saved for node %s', node.uuid)
        return
    if store_data == 'database':
        node_inventory.NodeInventory(
            context,
            node_id=node.id,
            inventory_data=inventory,
            plugin_data=plugin_data).create()
        LOG.info('Inspection data was stored in database for node %s',
                 node.uuid)
    if store_data == 'swift':
        swift_object_name = _store_inspection_data_in_swift(
            node_uuid=node.uuid,
            inventory_data=inventory,
            plugin_data=plugin_data)
        LOG.info('Inspection data was stored in Swift for node %(node)s: '
                 'objects %(obj_name)s-inventory and %(obj_name)s-plugin',
                 {'node': node.uuid, 'obj_name': swift_object_name})


def get_inspection_data(node, context):
    """Get inspection data.

    Retrieve the inspection data for a node either from database
    or the Object Storage API (swift/radosgw) as configured.

    :param node: the Ironic node that the required data is about
    :param context: an admin context
    :returns: dictionary with ``inventory`` and ``plugin_data`` fields
    :raises: NodeInventoryNotFound if no inventory has been saved
    """
    store_data = CONF.inventory.data_backend
    if store_data == 'none':
        raise exception.NodeInventoryNotFound(node=node.uuid)
    if store_data == 'database':
        node_inventory = objects.NodeInventory.get_by_node_id(
            context, node.id)
        return {"inventory": node_inventory.inventory_data,
                "plugin_data": node_inventory.plugin_data}
    if store_data == 'swift':
        try:
            return _get_inspection_data_from_swift(node.uuid)
        except exception.SwiftObjectNotFoundError:
            raise exception.NodeInventoryNotFound(node=node.uuid)


def _store_inspection_data_in_swift(node_uuid, inventory_data, plugin_data):
    """Uploads inspection data to Swift.

    :param data: data to store in Swift
    :param node_id: ID of the Ironic node that the data came from
    :returns: name of the Swift object that the data is stored in
    """
    swift_api = swift.SwiftAPI()
    swift_object_name = f'{_OBJECT_NAME_PREFIX}-{node_uuid}'
    container = CONF.inventory.swift_data_container
    swift_api.create_object_from_data(f'{swift_object_name}-inventory',
                                      inventory_data,
                                      container)
    swift_api.create_object_from_data(f'{swift_object_name}-plugin',
                                      plugin_data,
                                      container)
    return swift_object_name


def _get_inspection_data_from_swift(node_uuid):
    """Get inspection data from Swift.

    :param node_uuid: UUID of the Ironic node that the data came from
    :returns: dictionary with ``inventory`` and ``plugin_data`` fields
    """
    swift_api = swift.SwiftAPI()
    container = CONF.inventory.swift_data_container
    inv_obj = f'{_OBJECT_NAME_PREFIX}-{node_uuid}-inventory'
    plug_obj = f'{_OBJECT_NAME_PREFIX}-{node_uuid}-plugin'
    try:
        inventory_data = swift_api.get_object(inv_obj, container)
    except exception.SwiftOperationError:
        LOG.error("Failed to retrieve object %(obj)s from container %(cont)s",
                  {'obj': inv_obj, 'cont': container})
        raise exception.SwiftObjectNotFoundError(obj=inv_obj,
                                                 container=container,
                                                 operation='get')
    try:
        plugin_data = swift_api.get_object(plug_obj, container)
    except exception.SwiftOperationError:
        LOG.error("Failed to retrieve object %(obj)s from container %(cont)s",
                  {'obj': plug_obj, 'cont': container})
        raise exception.SwiftObjectNotFoundError(obj=plug_obj,
                                                 container=container,
                                                 operation='get')
    return {"inventory": inventory_data, "plugin_data": plugin_data}
