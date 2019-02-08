# Copyright 2016 Cisco Systems
# All Rights Reserved
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

import collections

from neutronclient.common import exceptions as neutron_exceptions
from oslo_config import cfg
from oslo_log import log

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import network
from ironic.common import neutron
from ironic.common.pxe_utils import DHCP_CLIENT_ID
from ironic.common import states
from ironic import objects

CONF = cfg.CONF
LOG = log.getLogger(__name__)

TENANT_VIF_KEY = 'tenant_vif_port_id'


def _vif_attached(port_like_obj, vif_id):
    """Check if VIF is already attached to a port or portgroup.

    Raises an exception if a VIF with id=vif_id is attached to the port-like
    (Port or Portgroup) object. Otherwise, returns whether a VIF is attached.

    :param port_like_obj: port-like object to check.
    :param vif_id: identifier of the VIF to look for in port_like_obj.
    :returns: True if a VIF (but not vif_id) is attached to port_like_obj,
        False otherwise.
    :raises: VifAlreadyAttached, if vif_id is attached to port_like_obj.
    """
    attached_vif_id = port_like_obj.internal_info.get(
        TENANT_VIF_KEY, port_like_obj.extra.get('vif_port_id'))
    if attached_vif_id == vif_id:
        raise exception.VifAlreadyAttached(
            object_type=port_like_obj.__class__.__name__,
            vif=vif_id, object_uuid=port_like_obj.uuid)
    return attached_vif_id is not None


def _is_port_physnet_allowed(port, physnets):
    """Check whether a port's physical network is allowed for a VIF.

    Supports VIFs on networks with no physical network configuration by
    allowing all ports regardless of their physical network. This will be the
    case when the port is not a neutron port because we're in standalone mode
    or not using neutron.

    Allows ports with physical_network=None to ensure backwards compatibility
    and provide support for simple deployments with no physical network
    configuration in ironic.

    When the physnets set is not empty and the port's physical_network field is
    not None, the port's physical_network field must be present in the physnets
    set.

    :param port: A Port object to check.
    :param physnets: Set of physical networks on which the VIF may be
        attached. This is governed by the segments of the VIF's network. An
        empty set indicates that the ports' physical networks should be
        ignored.
    :returns: True if the port's physical network is allowed, False otherwise.
    """
    return (not physnets
            or port.physical_network is None
            or port.physical_network in physnets)


def _get_free_portgroups_and_ports(task, vif_id, physnets):
    """Get free portgroups and ports.

    It only returns ports or portgroups that can be used for attachment of
    vif_id.

    :param task: a TaskManager instance.
    :param vif_id: Name or UUID of a VIF.
    :param physnets: Set of physical networks on which the VIF may be
        attached. This is governed by the segments of the VIF's network. An
        empty set indicates that the ports' physical networks should be
        ignored.
    :returns: list of free ports and portgroups.
    :raises: VifAlreadyAttached, if vif_id is attached to any of the
        node's ports or portgroups.
    """

    # This list contains ports and portgroups selected as candidates for
    # attachment.
    free_port_like_objs = []
    # This is a mapping of portgroup id to collection of its free ports
    ports_by_portgroup = collections.defaultdict(list)
    # This set contains IDs of portgroups that should be ignored, as they have
    # at least one port with vif already attached to it
    non_usable_portgroups = set()

    for p in task.ports:
        # Validate that port has needed information
        if not neutron.validate_port_info(task.node, p):
            continue
        if _vif_attached(p, vif_id):
            # Consider such portgroup unusable. The fact that we can have None
            # added in this set is not a problem
            non_usable_portgroups.add(p.portgroup_id)
            continue
        if not _is_port_physnet_allowed(p, physnets):
            continue
        if p.portgroup_id is None:
            # ports without portgroup_id are always considered candidates
            free_port_like_objs.append(p)
        else:
            ports_by_portgroup[p.portgroup_id].append(p)

    for pg in task.portgroups:
        if _vif_attached(pg, vif_id):
            continue
        if pg.id in non_usable_portgroups:
            # This portgroup has vifs attached to its ports, consider its
            # ports instead to avoid collisions
            free_port_like_objs.extend(ports_by_portgroup[pg.id])
        # Also ignore empty portgroups
        elif ports_by_portgroup[pg.id]:
            free_port_like_objs.append(pg)

    return free_port_like_objs


def get_free_port_like_object(task, vif_id, physnets):
    """Find free port-like object (portgroup or port) VIF will be attached to.

    Ensures that the VIF is not already attached to this node.  When selecting
    a port or portgroup to attach the virtual interface to, the following
    ordered criteria are applied:

    * Require ports or portgroups to have a physical network that is either
      None or one of the VIF's allowed physical networks.
    * Prefer ports or portgroups with a physical network field which is not
      None.
    * Prefer portgroups to ports.
    * Prefer ports with PXE enabled.

    :param task: a TaskManager instance.
    :param vif_id: Name or UUID of a VIF.
    :param physnets: Set of physical networks on which the VIF may be
        attached. This is governed by the segments of the VIF's network. An
        empty set indicates that the ports' physical networks should be
        ignored.
    :raises: VifAlreadyAttached, if VIF is already attached to the node.
    :raises: NoFreePhysicalPorts, if there is no port-like object VIF can be
        attached to.
    :raises: PortgroupPhysnetInconsistent if one of the node's portgroups
             has ports which are not all assigned the same physical network.
    :returns: port-like object VIF will be attached to.
    """
    free_port_like_objs = _get_free_portgroups_and_ports(task, vif_id,
                                                         physnets)

    if not free_port_like_objs:
        raise exception.NoFreePhysicalPorts(vif=vif_id)

    def sort_key(port_like_obj):
        """Key function for sorting a combined list of ports and portgroups.

        We key the port-like objects using the following precedence:

        1. Prefer objects with a physical network field which is in the
           physnets set.
        2. Prefer portgroups to ports.
        3. Prefer ports with PXE enabled.

        :param port_like_obj: The port or portgroup to key.
        :returns: A key value for sorting the object.
        """
        is_pg = isinstance(port_like_obj, objects.Portgroup)
        if is_pg:
            pg_physnets = network.get_physnets_by_portgroup_id(
                task, port_like_obj.id)
            pg_physnet = pg_physnets.pop()
            physnet_matches = pg_physnet in physnets
            pxe_enabled = True
        else:
            physnet_matches = port_like_obj.physical_network in physnets
            pxe_enabled = port_like_obj.pxe_enabled
        return (physnet_matches, is_pg, pxe_enabled)

    sorted_free_plos = sorted(free_port_like_objs, key=sort_key, reverse=True)
    return sorted_free_plos[0]


def plug_port_to_tenant_network(task, port_like_obj, client=None):
    """Plug port like object to tenant network.

    :param task: A TaskManager instance.
    :param port_like_obj: port-like object to plug.
    :param client: Neutron client instance.
    :raises: NetworkError if failed to update Neutron port.
    :raises: VifNotAttached if tenant VIF is not associated with port_like_obj.
    """

    node = task.node
    local_link_info = []
    local_group_info = None
    client_id_opt = None

    vif_id = (
        port_like_obj.internal_info.get(TENANT_VIF_KEY)
        or port_like_obj.extra.get('vif_port_id'))

    if not vif_id:
        obj_name = port_like_obj.__class__.__name__.lower()
        raise exception.VifNotAttached(
            _("Tenant VIF is not associated with %(obj_name)s "
              "%(obj_id)s") % {'obj_name': obj_name,
                               'obj_id': port_like_obj.uuid})

    LOG.debug('Mapping tenant port %(vif_id)s to node '
              '%(node_id)s',
              {'vif_id': vif_id, 'node_id': node.uuid})

    if isinstance(port_like_obj, objects.Portgroup):
        pg_ports = [p for p in task.ports
                    if p.portgroup_id == port_like_obj.id]
        for port in pg_ports:
            local_link_info.append(port.local_link_connection)
        local_group_info = neutron.get_local_group_information(
            task, port_like_obj)
    else:
        # We iterate only on ports or portgroups, no need to check
        # that it is a port
        local_link_info.append(port_like_obj.local_link_connection)
        client_id = port_like_obj.extra.get('client-id')
        if client_id:
            client_id_opt = ({'opt_name': DHCP_CLIENT_ID,
                              'opt_value': client_id})

    # NOTE(sambetts) Only update required binding: attributes,
    # because other port attributes may have been set by the user or
    # nova.
    body = {
        'port': {
            'binding:vnic_type': neutron.VNIC_BAREMETAL,
            'binding:host_id': node.uuid,
            'mac_address': port_like_obj.address
        }
    }
    binding_profile = {'local_link_information': local_link_info}
    if local_group_info:
        binding_profile['local_group_information'] = local_group_info
    body['port']['binding:profile'] = binding_profile

    if client_id_opt:
        body['port']['extra_dhcp_opts'] = [client_id_opt]

    is_smart_nic = neutron.is_smartnic_port(port_like_obj)
    if is_smart_nic:
        link_info = local_link_info[0]
        LOG.debug('Setting hostname as host_id in case of Smart NIC, '
                  'port %(port_id)s, hostname %(hostname)s',
                  {'port_id': vif_id,
                   'hostname': link_info['hostname']})
        body['port']['binding:host_id'] = link_info['hostname']
        body['port']['binding:vnic_type'] = neutron.VNIC_SMARTNIC

    if not client:
        client = neutron.get_client(context=task.context)

    if is_smart_nic:
        neutron.wait_for_host_agent(client, body['port']['binding:host_id'])

    try:
        client.update_port(vif_id, body)
        if is_smart_nic:
            neutron.wait_for_port_status(client, vif_id, 'ACTIVE')
    except neutron_exceptions.ConnectionFailed as e:
        msg = (_('Could not add public network VIF %(vif)s '
                 'to node %(node)s, possible network issue. %(exc)s') %
               {'vif': vif_id,
                'node': node.uuid,
                'exc': e})
        LOG.error(msg)
        raise exception.NetworkError(msg)


class VIFPortIDMixin(object):
    """VIF port ID mixin class for non-neutron network interfaces.

    Mixin class that provides VIF-related network interface methods for
    non-neutron network interfaces. There are no effects due to VIF
    attach/detach that are external to ironic.

    NOTE: This does not yet support the full set of VIF methods, as it does
    not provide vif_attach, vif_detach, port_changed, or portgroup_changed.
    """

    @staticmethod
    def _save_vif_to_port_like_obj(port_like_obj, vif_id):
        """Save the ID of a VIF to a port or portgroup.

        :param port_like_obj: port-like object to save to.
        :param vif_id: VIF ID to save.
        """
        int_info = port_like_obj.internal_info
        int_info[TENANT_VIF_KEY] = vif_id
        port_like_obj.internal_info = int_info
        port_like_obj.save()

    @staticmethod
    def _clear_vif_from_port_like_obj(port_like_obj):
        """Clear the VIF ID field from a port or portgroup.

        :param port_like_obj: port-like object to clear from.
        """
        int_info = port_like_obj.internal_info
        extra = port_like_obj.extra
        int_info.pop(TENANT_VIF_KEY, None)
        extra.pop('vif_port_id', None)
        port_like_obj.extra = extra
        port_like_obj.internal_info = int_info
        port_like_obj.save()

    def _get_port_like_obj_by_vif_id(self, task, vif_id):
        """Lookup a port or portgroup by its attached VIF ID.

        :param task: A TaskManager instance.
        :param vif_id: ID of the attached VIF.
        :returns: A Port or Portgroup object to which the VIF is attached.
        :raises: VifNotAttached if the VIF is not attached.
        """
        for port_like_obj in task.portgroups + task.ports:
            vif_port_id = self._get_vif_id_by_port_like_obj(port_like_obj)
            if vif_port_id == vif_id:
                return port_like_obj
        raise exception.VifNotAttached(vif=vif_id, node=task.node.uuid)

    @staticmethod
    def _get_vif_id_by_port_like_obj(port_like_obj):
        """Lookup the VIF attached to a port or portgroup.

        :param port_like_obj: A port or portgroup to check.
        :returns: The ID of the attached VIF, or None.
        """
        # FIXME(sambetts) Remove this when we no longer support a nova
        # driver that uses port.extra
        return (port_like_obj.internal_info.get(TENANT_VIF_KEY)
                or port_like_obj.extra.get('vif_port_id'))

    def vif_list(self, task):
        """List attached VIF IDs for a node

        :param task: A TaskManager instance.
        :returns: List of VIF dictionaries, each dictionary will have an 'id'
            entry with the ID of the VIF.
        """
        vifs = []
        for port_like_obj in task.ports + task.portgroups:
            vif_id = self._get_vif_id_by_port_like_obj(port_like_obj)
            if vif_id:
                vifs.append({'id': vif_id})
        return vifs

    def get_current_vif(self, task, p_obj):
        """Returns the currently used VIF associated with port or portgroup

        We are booting the node only in one network at a time, and presence of
        cleaning_vif_port_id means we're doing cleaning,
        of provisioning_vif_port_id - provisioning,
        of rescuing_vif_port_id - rescuing.
        Otherwise it's a tenant network

        :param task: A TaskManager instance.
        :param p_obj: Ironic port or portgroup object.
        :returns: VIF ID associated with p_obj or None.
        """

        return (p_obj.internal_info.get('cleaning_vif_port_id')
                or p_obj.internal_info.get('provisioning_vif_port_id')
                or p_obj.internal_info.get('rescuing_vif_port_id')
                or self._get_vif_id_by_port_like_obj(p_obj) or None)


class NeutronVIFPortIDMixin(VIFPortIDMixin):
    """VIF port ID mixin class for neutron network interfaces.

    Mixin class that provides VIF-related network interface methods for neutron
    network interfaces. On VIF attach/detach, the associated neutron port will
    be updated.
    """

    def port_changed(self, task, port_obj):
        """Handle any actions required when a port changes

        :param task: a TaskManager instance.
        :param port_obj: a changed Port object from the API before it is saved
            to database.
        :raises: FailedToUpdateDHCPOptOnPort, Conflict
        """
        context = task.context
        node = task.node
        port_uuid = port_obj.uuid
        portgroup_obj = None
        if port_obj.portgroup_id:
            portgroup_obj = [pg for pg in task.portgroups if
                             pg.id == port_obj.portgroup_id][0]
        vif = self._get_vif_id_by_port_like_obj(port_obj)
        if 'address' in port_obj.obj_what_changed():
            if vif:
                neutron.update_port_address(vif, port_obj.address,
                                            context=task.context)

        if 'extra' in port_obj.obj_what_changed():
            original_port = objects.Port.get_by_id(context, port_obj.id)
            updated_client_id = port_obj.extra.get('client-id')

            if (original_port.extra.get('client-id')
                != updated_client_id):
                # DHCP Option with opt_value=None will remove it
                # from the neutron port
                if vif:
                    api = dhcp_factory.DHCPFactory()
                    client_id_opt = {'opt_name': DHCP_CLIENT_ID,
                                     'opt_value': updated_client_id}

                    api.provider.update_port_dhcp_opts(
                        vif, [client_id_opt], context=task.context)
                # Log warning if there is no VIF and an instance
                # is associated with the node.
                elif node.instance_uuid:
                    LOG.warning(
                        "No VIF found for instance %(instance)s "
                        "port %(port)s when attempting to update port "
                        "client-id.",
                        {'port': port_uuid,
                         'instance': node.instance_uuid})

        if portgroup_obj and ((set(port_obj.obj_what_changed())
                              & {'pxe_enabled', 'portgroup_id'}) or vif):
            if not portgroup_obj.standalone_ports_supported:
                reason = []
                if port_obj.pxe_enabled:
                    reason.append("'pxe_enabled' was set to True")
                if vif:
                    reason.append('VIF %s is attached to the port' % vif)

                if reason:
                    msg = (_("Port group %(portgroup)s doesn't support "
                             "standalone ports. This port %(port)s cannot be "
                             " a member of that port group because of: "
                             "%(reason)s") % {"reason": ', '.join(reason),
                                              "portgroup": portgroup_obj.uuid,
                                              "port": port_uuid})
                    raise exception.Conflict(msg)

    def portgroup_changed(self, task, portgroup_obj):
        """Handle any actions required when a portgroup changes

        :param task: a TaskManager instance.
        :param portgroup_obj: a changed Portgroup object from the API before
            it is saved to database.
        :raises: FailedToUpdateDHCPOptOnPort, Conflict
        """

        portgroup_uuid = portgroup_obj.uuid
        # NOTE(vsaienko) address is not mandatory field in portgroup.
        # Do not touch neutron port if we removed address on portgroup.
        if ('address' in portgroup_obj.obj_what_changed()
                and portgroup_obj.address):
            pg_vif = self._get_vif_id_by_port_like_obj(portgroup_obj)
            if pg_vif:
                neutron.update_port_address(pg_vif, portgroup_obj.address,
                                            context=task.context)

        if ('standalone_ports_supported' in
                portgroup_obj.obj_what_changed()):
            if not portgroup_obj.standalone_ports_supported:
                ports = [p for p in task.ports if
                         p.portgroup_id == portgroup_obj.id]
                for p in ports:
                    vif = self._get_vif_id_by_port_like_obj(p)
                    reason = []
                    if p.pxe_enabled:
                        reason.append("'pxe_enabled' is set to True")
                    if vif:
                        reason.append('VIF %s is attached to this port' % vif)

                    if reason:
                        msg = (_("standalone_ports_supported can not be set "
                                 "to False, because the port group %(pg_id)s "
                                 "contains port with %(reason)s") % {
                               'pg_id': portgroup_uuid,
                               'reason': ', '.join(reason)})
                        raise exception.Conflict(msg)

    def vif_attach(self, task, vif_info):
        """Attach a virtual network interface to a node

        Attach a virtual interface to a node.  When selecting a port or
        portgroup to attach the virtual interface to, the following ordered
        criteria are applied:

        * Require ports or portgroups to have a physical network that is either
          None or one of the VIF's allowed physical networks.
        * Prefer ports or portgroups with a physical network field which is not
          None.
        * Prefer portgroups to ports.
        * Prefer ports with PXE enabled.

        :param task: A TaskManager instance.
        :param vif_info: a dictionary of information about a VIF.
                         It must have an 'id' key, whose value is a unique
                         identifier for that VIF.
        :raises: NetworkError, VifAlreadyAttached, NoFreePhysicalPorts
        :raises: PortgroupPhysnetInconsistent if one of the node's portgroups
                 has ports which are not all assigned the same physical
                 network.
        """
        vif_id = vif_info['id']
        client = neutron.get_client(context=task.context)

        # Determine whether any of the node's ports have a physical network. If
        # not, we don't need to check the VIF's network's physical networks as
        # they will not affect the VIF to port mapping.
        physnets = set()
        if any(port.physical_network is not None for port in task.ports):
            physnets = neutron.get_physnets_by_port_uuid(client, vif_id)

            if len(physnets) > 1:
                # NOTE(mgoddard): Neutron cannot currently handle hosts which
                # are mapped to multiple segments in the same routed network.
                node_physnets = network.get_physnets_for_node(task)
                if len(node_physnets.intersection(physnets)) > 1:
                    reason = _("Node has ports which map to multiple segments "
                               "of the routed network to which the VIF is "
                               "attached. Currently neutron only supports "
                               "hosts which map to one segment of a routed "
                               "network")
                    raise exception.VifInvalidForAttach(
                        node=task.node.uuid, vif=vif_id, reason=reason)

        port_like_obj = get_free_port_like_object(task, vif_id, physnets)

        # Address is optional for portgroups
        if port_like_obj.address:
            try:
                neutron.update_port_address(vif_id, port_like_obj.address,
                                            context=task.context)
            except exception.FailedToUpdateMacOnPort:
                raise exception.NetworkError(_(
                    "Unable to attach VIF %(vif)s because Ironic can not "
                    "update Neutron port %(port)s MAC address to match "
                    "physical MAC address %(mac)s") % {
                        'vif': vif_id, 'port': vif_id,
                        'mac': port_like_obj.address})

        self._save_vif_to_port_like_obj(port_like_obj, vif_id)

        # NOTE(vsaienko) allow to attach VIF to active instance.
        if task.node.provision_state == states.ACTIVE:
            plug_port_to_tenant_network(task, port_like_obj, client=client)

    def vif_detach(self, task, vif_id):
        """Detach a virtual network interface from a node

        :param task: A TaskManager instance.
        :param vif_id: A VIF ID to detach
        :raises: VifNotAttached if VIF not attached.
        :raises: NetworkError if unbind Neutron port failed.
        """
        # NOTE(mgoddard): Lookup the port first to check that the VIF is
        # attached, and fail if not.
        port_like_obj = self._get_port_like_obj_by_vif_id(task, vif_id)

        self._clear_vif_from_port_like_obj(port_like_obj)

        # NOTE(vsaienko): allow to unplug VIFs from ACTIVE instance.
        # NOTE(TheJulia): Also ensure that we delete the vif when in
        # DELETING state.
        if task.node.provision_state in [states.ACTIVE, states.DELETING]:
            neutron.unbind_neutron_port(vif_id, context=task.context)
