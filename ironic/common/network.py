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
        # NOTE(vdrok): We are booting the node only in one network at a time,
        # and presence of cleaning_vif_port_id means we're doing cleaning, of
        # provisioning_vif_port_id - provisioning. Otherwise it's a tenant
        # network
        vif = (portgroup.internal_info.get('cleaning_vif_port_id') or
               portgroup.internal_info.get('provisioning_vif_port_id') or
               portgroup.extra.get('vif_port_id'))
        if vif:
            portgroup_vifs[portgroup.uuid] = vif
    vifs['portgroups'] = portgroup_vifs
    for port in task.ports:
        vif = (port.internal_info.get('cleaning_vif_port_id') or
               port.internal_info.get('provisioning_vif_port_id') or
               port.extra.get('vif_port_id'))
        if vif:
            port_vifs[port.uuid] = vif
    vifs['ports'] = port_vifs
    return vifs
