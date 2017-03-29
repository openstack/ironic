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
from ironic.common.i18n import _, _LW
from ironic.common import neutron
from ironic.common import states
from ironic.common import utils
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


def _get_free_portgroups_and_ports(task, vif_id):
    """Get free portgroups and ports.

    It only returns ports or portgroups that can be used for attachment of
    vif_id.

    :param task: a TaskManager instance.
    :param vif_id: Name or UUID of a VIF.
    :returns: tuple of: list of free portgroups, list of free ports.
    :raises: VifAlreadyAttached, if vif_id is attached to any of the
        node's ports or portgroups.
    """

    # This list contains ports selected as candidates for attachment
    free_ports = []
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
        if p.portgroup_id is None:
            # ports without portgroup_id are always considered candidates
            free_ports.append(p)
        else:
            ports_by_portgroup[p.portgroup_id].append(p)

    # This list contains portgroups selected as candidates for attachment
    free_portgroups = []

    for pg in task.portgroups:
        if _vif_attached(pg, vif_id):
            continue
        if pg.id in non_usable_portgroups:
            # This portgroup has vifs attached to its ports, consider its
            # ports instead to avoid collisions
            free_ports.extend(ports_by_portgroup[pg.id])
        # Also ignore empty portgroups
        elif ports_by_portgroup[pg.id]:
            free_portgroups.append(pg)

    return free_portgroups, free_ports


def get_free_port_like_object(task, vif_id):
    """Find free port-like object (portgroup or port) VIF will be attached to.

    Ensures that VIF is not already attached to this node. It will return the
    first free port group. If there are no free port groups, then the first
    available port (pxe_enabled preferably) is used.

    :param task: a TaskManager instance.
    :param vif_id: Name or UUID of a VIF.
    :raises: VifAlreadyAttached, if VIF is already attached to the node.
    :raises: NoFreePhysicalPorts, if there is no port-like object VIF can be
        attached to.
    :returns: port-like object VIF will be attached to.
    """

    free_portgroups, free_ports = _get_free_portgroups_and_ports(task, vif_id)

    if free_portgroups:
        # portgroups are higher priority
        return free_portgroups[0]

    if not free_ports:
        raise exception.NoFreePhysicalPorts(vif=vif_id)

    # Sort ports by pxe_enabled to ensure we always bind pxe_enabled ports
    # first
    sorted_free_ports = sorted(free_ports, key=lambda p: p.pxe_enabled,
                               reverse=True)
    return sorted_free_ports[0]


def plug_port_to_tenant_network(task, port_like_obj, client=None):
    """Plug port like object to tenant network.

    :param task: A TaskManager instance.
    :param port_like_obj: port-like object to plug.
    :param client: Neutron client instance.
    :raises NetworkError: if failed to update Neutron port.
    :raises VifNotAttached if tenant VIF is not associated with port_like_obj.
    """

    node = task.node
    local_link_info = []
    client_id_opt = None

    vif_id = (
        port_like_obj.internal_info.get(TENANT_VIF_KEY) or
        port_like_obj.extra.get('vif_port_id'))

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
    else:
        # We iterate only on ports or portgroups, no need to check
        # that it is a port
        local_link_info.append(port_like_obj.local_link_connection)
        client_id = port_like_obj.extra.get('client-id')
        if client_id:
            client_id_opt = ({'opt_name': 'client-id', 'opt_value': client_id})

    # NOTE(sambetts) Only update required binding: attributes,
    # because other port attributes may have been set by the user or
    # nova.
    body = {
        'port': {
            'binding:vnic_type': 'baremetal',
            'binding:host_id': node.uuid,
            'binding:profile': {
                'local_link_information': local_link_info,
            },
        }
    }
    if client_id_opt:
        body['port']['extra_dhcp_opts'] = [client_id_opt]

    if not client:
        client = neutron.get_client()

    try:
        client.update_port(vif_id, body)
    except neutron_exceptions.ConnectionFailed as e:
        msg = (_('Could not add public network VIF %(vif)s '
                 'to node %(node)s, possible network issue. %(exc)s') %
               {'vif': vif_id,
                'node': node.uuid,
                'exc': e})
        LOG.error(msg)
        raise exception.NetworkError(msg)


class VIFPortIDMixin(object):

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
        vif = (port_obj.internal_info.get(TENANT_VIF_KEY) or
               port_obj.extra.get('vif_port_id'))
        if 'address' in port_obj.obj_what_changed():
            if vif:
                neutron.update_port_address(vif, port_obj.address)

        if 'extra' in port_obj.obj_what_changed():
            original_port = objects.Port.get_by_id(context, port_obj.id)
            updated_client_id = port_obj.extra.get('client-id')
            if (port_obj.extra.get('vif_port_id') and
                    (port_obj.extra['vif_port_id'] !=
                     original_port.extra.get('vif_port_id'))):
                utils.warn_about_deprecated_extra_vif_port_id()
            if (original_port.extra.get('client-id') !=
                updated_client_id):
                # DHCP Option with opt_value=None will remove it
                # from the neutron port
                if vif:
                    api = dhcp_factory.DHCPFactory()
                    client_id_opt = {'opt_name': 'client-id',
                                     'opt_value': updated_client_id}

                    api.provider.update_port_dhcp_opts(
                        vif, [client_id_opt])
                # Log warning if there is no VIF and an instance
                # is associated with the node.
                elif node.instance_uuid:
                    LOG.warning(_LW(
                        "No VIF found for instance %(instance)s "
                        "port %(port)s when attempting to update port "
                        "client-id."),
                        {'port': port_uuid,
                         'instance': node.instance_uuid})

        if portgroup_obj and ((set(port_obj.obj_what_changed()) &
                              {'pxe_enabled', 'portgroup_id'}) or vif):
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

        context = task.context
        portgroup_uuid = portgroup_obj.uuid
        # NOTE(vsaienko) address is not mandatory field in portgroup.
        # Do not touch neutron port if we removed address on portgroup.
        if ('address' in portgroup_obj.obj_what_changed() and
                portgroup_obj.address):
            pg_vif = (portgroup_obj.internal_info.get(TENANT_VIF_KEY) or
                      portgroup_obj.extra.get('vif_port_id'))
            if pg_vif:
                neutron.update_port_address(pg_vif, portgroup_obj.address)

        if 'extra' in portgroup_obj.obj_what_changed():
            original_portgroup = objects.Portgroup.get_by_id(context,
                                                             portgroup_obj.id)
            if (portgroup_obj.extra.get('vif_port_id') and
                    portgroup_obj.extra['vif_port_id'] !=
                    original_portgroup.extra.get('vif_port_id')):
                utils.warn_about_deprecated_extra_vif_port_id()

        if ('standalone_ports_supported' in
                portgroup_obj.obj_what_changed()):
            if not portgroup_obj.standalone_ports_supported:
                ports = [p for p in task.ports if
                         p.portgroup_id == portgroup_obj.id]
                for p in ports:
                    vif = p.internal_info.get(
                        TENANT_VIF_KEY, p.extra.get('vif_port_id'))
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

    def vif_list(self, task):
        """List attached VIF IDs for a node

        :param task: A TaskManager instance.
        :returns: List of VIF dictionaries, each dictionary will have an 'id'
            entry with the ID of the VIF.
        """
        vifs = []
        for port_like_obj in task.ports + task.portgroups:
            vif_id = port_like_obj.internal_info.get(
                TENANT_VIF_KEY, port_like_obj.extra.get('vif_port_id'))
            if vif_id:
                vifs.append({'id': vif_id})
        return vifs

    def vif_attach(self, task, vif_info):
        """Attach a virtual network interface to a node

        Attach a virtual interface to a node. It will use the first free port
        group. If there are no free port groups, then the first available port
        (pxe_enabled preferably) is used.

        :param task: A TaskManager instance.
        :param vif_info: a dictionary of information about a VIF.
             It must have an 'id' key, whose value is a unique
             identifier for that VIF.
        :raises: NetworkError, VifAlreadyAttached, NoFreePhysicalPorts
        """
        vif_id = vif_info['id']

        port_like_obj = get_free_port_like_object(task, vif_id)

        client = neutron.get_client()
        # Address is optional for portgroups
        if port_like_obj.address:
            # Check if the requested vif_id is a neutron port. If it is
            # then attempt to update the port's MAC address.
            try:
                client.show_port(vif_id)
            except neutron_exceptions.NeutronClientException:
                # NOTE(sambetts): If a client error occurs this is because
                # either neutron doesn't exist because we're running in
                # standalone environment or we can't find a matching neutron
                # port which means a user might be requesting a non-neutron
                # port. So skip trying to update the neutron port MAC address
                # in these cases.
                pass
            else:
                try:
                    neutron.update_port_address(vif_id, port_like_obj.address)
                except exception.FailedToUpdateMacOnPort:
                    raise exception.NetworkError(_(
                        "Unable to attach VIF %(vif)s because Ironic can not "
                        "update Neutron port %(port)s MAC address to match "
                        "physical MAC address %(mac)s") % {
                            'vif': vif_id, 'port': vif_id,
                            'mac': port_like_obj.address})

        int_info = port_like_obj.internal_info
        int_info[TENANT_VIF_KEY] = vif_id
        port_like_obj.internal_info = int_info
        port_like_obj.save()
        # NOTE(vsaienko) allow to attach VIF to active instance.
        if task.node.provision_state == states.ACTIVE:
            plug_port_to_tenant_network(task, port_like_obj, client=client)

    def vif_detach(self, task, vif_id):
        """Detach a virtual network interface from a node

        :param task: A TaskManager instance.
        :param vif_id: A VIF ID to detach
        :raises: VifNotAttached if VIF not attached.
        :raises: NetworkError: if unbind Neutron port failed.
        """

        # NOTE(vsaienko) We picking object to attach on vif-attach side.
        # Here we should only detach VIF and shouldn't duplicate/follow
        # attach rules, just walk over all objects and detach VIF.
        for port_like_obj in task.portgroups + task.ports:
            # FIXME(sambetts) Remove this when we no longer support a nova
            # driver that uses port.extra
            vif_port_id = port_like_obj.internal_info.get(
                TENANT_VIF_KEY, port_like_obj.extra.get("vif_port_id"))
            if vif_port_id == vif_id:
                int_info = port_like_obj.internal_info
                extra = port_like_obj.extra
                int_info.pop(TENANT_VIF_KEY, None)
                extra.pop('vif_port_id', None)
                port_like_obj.extra = extra
                port_like_obj.internal_info = int_info
                port_like_obj.save()
                # NOTE(vsaienko) allow to unplug VIFs from ACTIVE instance.
                if task.node.provision_state == states.ACTIVE:
                    neutron.unbind_neutron_port(vif_port_id)
                break
        else:
            raise exception.VifNotAttached(vif=vif_id, node=task.node.uuid)

    def get_current_vif(self, task, p_obj):
        """Returns the currently used VIF associated with port or portgroup

        We are booting the node only in one network at a time, and presence of
        cleaning_vif_port_id means we're doing cleaning, of
        provisioning_vif_port_id - provisioning.
        Otherwise it's a tenant network

        :param task: A TaskManager instance.
        :param p_obj: Ironic port or portgroup object.
        :returns: VIF ID associated with p_obj or None.
        """

        return (p_obj.internal_info.get('cleaning_vif_port_id') or
                p_obj.internal_info.get('provisioning_vif_port_id') or
                p_obj.internal_info.get(TENANT_VIF_KEY) or
                p_obj.extra.get('vif_port_id') or None)
