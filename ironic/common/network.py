# Copyright 2014 Rackspace, Inc.
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


def get_node_vif_ids(task):
    """Get all VIF ids for a node.

    This function does not handle multi node operations.

    :param task: a TaskManager instance.
    :returns: A dict of Node's neutron ports where keys are
        'ports' & 'portgroups' and the values are dict of UUIDs
        and their associated VIFs, e.g.

              ::

               {'ports': {'port.uuid': vif.id},
                'portgroups': {'portgroup.uuid': vif.id}}
    """
    vifs = {}
    portgroup_vifs = {}
    port_vifs = {}
    for portgroup in task.portgroups:
        vif = task.driver.network.get_current_vif(task, portgroup)
        if vif:
            portgroup_vifs[portgroup.uuid] = vif
    vifs['portgroups'] = portgroup_vifs
    for port in task.ports:
        vif = task.driver.network.get_current_vif(task, port)
        if vif:
            port_vifs[port.uuid] = vif
    vifs['ports'] = port_vifs
    return vifs


def get_portgroup_by_id(task, portgroup_id):
    """Lookup a portgroup by ID on a task object.

    :param task: a TaskManager instance
    :param portgroup_id: ID of the portgroup.
    :returns: A Portgroup object or None.
    """
    for portgroup in task.portgroups:
        if portgroup.id == portgroup_id:
            return portgroup


def get_ports_by_portgroup_id(task, portgroup_id):
    """Lookup ports by their portgroup ID on a task object.

    :param task: a TaskManager instance
    :param portgroup_id: ID of the portgroup.
    :returns: A list of Port objects.
    """
    return [port for port in task.ports if port.portgroup_id == portgroup_id]


def get_physnets_for_node(task):
    """Return the set of physical networks for a node.

    Returns the set of physical networks associated with a node's ports. The
    physical network None is excluded from the set.

    :param task: a TaskManager instance
    :returns: A set of physical networks.
    """
    return set(port.physical_network
               for port in task.ports
               if port.physical_network is not None)
