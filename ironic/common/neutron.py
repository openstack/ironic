# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutronclient.common import exceptions as neutron_exceptions
from neutronclient.v2_0 import client as clientv20
from oslo_log import log
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.common.pxe_utils import DHCP_CLIENT_ID
from ironic.conf import CONF

LOG = log.getLogger(__name__)

DEFAULT_NEUTRON_URL = 'http://%s:9696' % CONF.my_ip

_NEUTRON_SESSION = None

PHYSNET_PARAM_NAME = 'provider:physical_network'
"""Name of the neutron network API physical network parameter."""

SEGMENTS_PARAM_NAME = 'segments'
"""Name of the neutron network API segments parameter."""


def _get_neutron_session():
    global _NEUTRON_SESSION
    if not _NEUTRON_SESSION:
        auth = keystone.get_auth('neutron')
        _NEUTRON_SESSION = keystone.get_session('neutron', auth=auth)
    return _NEUTRON_SESSION


def get_client(token=None):
    params = {'retries': CONF.neutron.retries}
    url = CONF.neutron.url
    if CONF.neutron.auth_strategy == 'noauth':
        params['endpoint_url'] = url or DEFAULT_NEUTRON_URL
        params['auth_strategy'] = 'noauth'
        params.update({
            'timeout': CONF.neutron.url_timeout or CONF.neutron.timeout,
            'insecure': CONF.neutron.insecure,
            'ca_cert': CONF.neutron.cafile})
    else:
        session = _get_neutron_session()
        if token is None:
            params['session'] = session
            # NOTE(pas-ha) endpoint_override==None will auto-discover
            # endpoint from Keystone catalog.
            # Region is needed only in this case.
            # SSL related options are ignored as they are already embedded
            # in keystoneauth Session object
            if url:
                params['endpoint_override'] = url
            else:
                params['region_name'] = CONF.keystone.region_name
        else:
            params['token'] = token
            params['endpoint_url'] = url or keystone.get_service_url(
                session,
                service_type='network',
                region_name=CONF.keystone.region_name)
            params.update({
                'timeout': CONF.neutron.url_timeout or CONF.neutron.timeout,
                'insecure': CONF.neutron.insecure,
                'ca_cert': CONF.neutron.cafile})

    return clientv20.Client(**params)


def unbind_neutron_port(port_id, client=None):
    """Unbind a neutron port

    Remove a neutron port's binding profile and host ID so that it returns to
    an unbound state.

    :param port_id: Neutron port ID.
    :param client: Optional a Neutron client object.
    :raises: NetworkError
    """

    if not client:
        client = get_client()

    body = {'port': {'binding:host_id': '',
                     'binding:profile': {}}}

    try:
        client.update_port(port_id, body)
    # NOTE(vsaienko): Ignore if port was deleted before calling vif detach.
    except neutron_exceptions.PortNotFoundClient:
        LOG.info('Port %s was not found while unbinding.', port_id)
    except neutron_exceptions.NeutronClientException as e:
        msg = (_('Unable to clear binding profile for '
                 'neutron port %(port_id)s. Error: '
                 '%(err)s') % {'port_id': port_id, 'err': e})
        LOG.exception(msg)
        raise exception.NetworkError(msg)


def update_port_address(port_id, address):
    """Update a port's mac address.

    :param port_id: Neutron port id.
    :param address: new MAC address.
    :raises: FailedToUpdateMacOnPort
    """
    client = get_client()
    port_req_body = {'port': {'mac_address': address}}

    try:
        msg = (_("Failed to get the current binding on Neutron "
                 "port %s.") % port_id)
        port = client.show_port(port_id).get('port', {})
        binding_host_id = port.get('binding:host_id')
        binding_profile = port.get('binding:profile')

        if binding_host_id:
            # Unbind port before we update it's mac address, because you can't
            # change a bound port's mac address.
            msg = (_("Failed to remove the current binding from "
                     "Neutron port %s, while updating its MAC "
                     "address.") % port_id)
            unbind_neutron_port(port_id, client=client)
            port_req_body['port']['binding:host_id'] = binding_host_id
            port_req_body['port']['binding:profile'] = binding_profile

        msg = (_("Failed to update MAC address on Neutron port %s.") % port_id)
        client.update_port(port_id, port_req_body)
    except (neutron_exceptions.NeutronClientException, exception.NetworkError):
        LOG.exception(msg)
        raise exception.FailedToUpdateMacOnPort(port_id=port_id)


def _verify_security_groups(security_groups, client):
    """Verify that the security groups exist.

    :param security_groups: a list of security group UUIDs; may be None or
        empty
    :param client: Neutron client
    :raises: NetworkError
    """

    if not security_groups:
        return
    try:
        neutron_sec_groups = (
            client.list_security_groups().get('security_groups', []))
    except neutron_exceptions.NeutronClientException as e:
        msg = (_("Could not retrieve security groups from neutron: %(exc)s") %
               {'exc': e})
        LOG.exception(msg)
        raise exception.NetworkError(msg)

    existing_sec_groups = [sec_group['id'] for sec_group in neutron_sec_groups]
    missing_sec_groups = set(security_groups) - set(existing_sec_groups)
    if missing_sec_groups:
        msg = (_('Could not find these security groups (specified via ironic '
                 'config) in neutron: %(ir-sg)s')
               % {'ir-sg': list(missing_sec_groups)})
        LOG.error(msg)
        raise exception.NetworkError(msg)


def add_ports_to_network(task, network_uuid, security_groups=None):
    """Create neutron ports to boot the ramdisk.

    Create neutron ports for each pxe_enabled port on task.node to boot
    the ramdisk.

    :param task: a TaskManager instance.
    :param network_uuid: UUID of a neutron network where ports will be
        created.
    :param security_groups: List of Security Groups UUIDs to be used for
        network.
    :raises: NetworkError
    :returns: a dictionary in the form {port.uuid: neutron_port['id']}
    """
    client = get_client()
    node = task.node

    # If Security Groups are specified, verify that they exist
    _verify_security_groups(security_groups, client)

    LOG.debug('For node %(node)s, creating neutron ports on network '
              '%(network_uuid)s using %(net_iface)s network interface.',
              {'net_iface': task.driver.network.__class__.__name__,
               'node': node.uuid, 'network_uuid': network_uuid})
    body = {
        'port': {
            'network_id': network_uuid,
            'admin_state_up': True,
            'binding:vnic_type': 'baremetal',
            'device_owner': 'baremetal:none',
            'binding:host_id': node.uuid,
        }
    }
    if security_groups:
        body['port']['security_groups'] = security_groups

    # Since instance_uuid will not be available during cleaning
    # operations, we need to check that and populate them only when
    # available
    body['port']['device_id'] = node.instance_uuid or node.uuid

    ports = {}
    failures = []
    portmap = get_node_portmap(task)
    pxe_enabled_ports = [p for p in task.ports if p.pxe_enabled]
    for ironic_port in pxe_enabled_ports:
        # Skip ports that are missing required information for deploy.
        if not validate_port_info(node, ironic_port):
            failures.append(ironic_port.uuid)
            continue
        body['port']['mac_address'] = ironic_port.address
        binding_profile = {'local_link_information':
                           [portmap[ironic_port.uuid]]}
        body['port']['binding:profile'] = binding_profile
        client_id = ironic_port.extra.get('client-id')
        if client_id:
            client_id_opt = {'opt_name': DHCP_CLIENT_ID,
                             'opt_value': client_id}
            extra_dhcp_opts = body['port'].get('extra_dhcp_opts', [])
            extra_dhcp_opts.append(client_id_opt)
            body['port']['extra_dhcp_opts'] = extra_dhcp_opts
        try:
            port = client.create_port(body)
        except neutron_exceptions.NeutronClientException as e:
            failures.append(ironic_port.uuid)
            LOG.warning("Could not create neutron port for node's "
                        "%(node)s port %(ir-port)s on the neutron "
                        "network %(net)s. %(exc)s",
                        {'net': network_uuid, 'node': node.uuid,
                         'ir-port': ironic_port.uuid, 'exc': e})
        else:
            ports[ironic_port.uuid] = port['port']['id']

    if failures:
        if len(failures) == len(pxe_enabled_ports):
            rollback_ports(task, network_uuid)
            raise exception.NetworkError(_(
                "Failed to create neutron ports for any PXE enabled port "
                "on node %s.") % node.uuid)
        else:
            LOG.warning("Some errors were encountered when updating "
                        "vif_port_id for node %(node)s on "
                        "the following ports: %(ports)s.",
                        {'node': node.uuid, 'ports': failures})
    else:
        LOG.info('Successfully created ports for node %(node_uuid)s in '
                 'network %(net)s.',
                 {'node_uuid': node.uuid, 'net': network_uuid})

    return ports


def remove_ports_from_network(task, network_uuid):
    """Deletes the neutron ports created for booting the ramdisk.

    :param task: a TaskManager instance.
    :param network_uuid: UUID of a neutron network ports will be deleted from.
    :raises: NetworkError
    """
    macs = [p.address for p in task.ports if p.pxe_enabled]
    if macs:
        params = {
            'network_id': network_uuid,
            'mac_address': macs,
        }
        LOG.debug("Removing ports on network %(net)s on node %(node)s.",
                  {'net': network_uuid, 'node': task.node.uuid})

        remove_neutron_ports(task, params)


def remove_neutron_ports(task, params):
    """Deletes the neutron ports matched by params.

    :param task: a TaskManager instance.
    :param params: Dict of params to filter ports.
    :raises: NetworkError
    """
    client = get_client()
    node_uuid = task.node.uuid

    try:
        response = client.list_ports(**params)
    except neutron_exceptions.NeutronClientException as e:
        msg = (_('Could not get given network VIF for %(node)s '
                 'from neutron, possible network issue. %(exc)s') %
               {'node': node_uuid, 'exc': e})
        LOG.exception(msg)
        raise exception.NetworkError(msg)

    ports = response.get('ports', [])
    if not ports:
        LOG.debug('No ports to remove for node %s', node_uuid)
        return

    for port in ports:
        LOG.debug('Deleting neutron port %(vif_port_id)s of node '
                  '%(node_id)s.',
                  {'vif_port_id': port['id'], 'node_id': node_uuid})

        try:
            client.delete_port(port['id'])
        # NOTE(mgoddard): Ignore if the port was deleted by nova.
        except neutron_exceptions.PortNotFoundClient:
            LOG.info('Port %s was not found while deleting.', port['id'])
        except neutron_exceptions.NeutronClientException as e:
            msg = (_('Could not remove VIF %(vif)s of node %(node)s, possibly '
                     'a network issue: %(exc)s') %
                   {'vif': port['id'], 'node': node_uuid, 'exc': e})
            LOG.exception(msg)
            raise exception.NetworkError(msg)

    LOG.info('Successfully removed node %(node_uuid)s neutron ports.',
             {'node_uuid': node_uuid})


def get_node_portmap(task):
    """Extract the switch port information for the node.

    :param task: a task containing the Node object.
    :returns: a dictionary in the form
        {
            port.uuid: {
                'switch_id': 'abc',
                'port_id': 'Po0/1',
                'other_llc_key': 'val'
            }
        }
    """

    portmap = {}
    for port in task.ports:
        portmap[port.uuid] = port.local_link_connection
    return portmap
    # TODO(jroll) raise InvalidParameterValue if a port doesn't have the
    # necessary info? (probably)


def get_local_group_information(task, portgroup):
    """Extract the portgroup information.

    :param task: a task containing the Node object.
    :param portgroup: Ironic portgroup object to extract data for.
    :returns: a dictionary in the form:
              {
                  'id': portgroup.uuid,
                  'name': portgroup.name,
                  'bond_mode': portgroup.mode,
                  'bond_properties': {
                      'bond_propertyA': 'valueA',
                      'bond_propertyB': 'valueB',
                  }
              }
    """

    portgroup_properties = {}
    for prop, value in portgroup.properties.items():
        # These properties are the bonding driver options described
        # at https://www.kernel.org/doc/Documentation/networking/bonding.txt .
        # cloud-init checks the same way, parameter name has to start with
        # 'bond'. Keep this structure when passing properties to neutron ML2
        # drivers.
        key = prop if prop.startswith('bond') else 'bond_%s' % prop
        portgroup_properties[key] = value

    return {
        'id': portgroup.uuid,
        'name': portgroup.name,
        'bond_mode': portgroup.mode,
        'bond_properties': portgroup_properties
    }


def rollback_ports(task, network_uuid):
    """Attempts to delete any ports created by cleaning/provisioning

    Purposefully will not raise any exceptions so error handling can
    continue.

    :param task: a TaskManager instance.
    :param network_uuid: UUID of a neutron network.
    """
    try:
        remove_ports_from_network(task, network_uuid)
    except exception.NetworkError:
        # Only log the error
        LOG.exception('Failed to rollback port changes for '
                      'node %(node)s on network %(network)s',
                      {'node': task.node.uuid, 'network': network_uuid})


def validate_network(uuid_or_name, net_type=_('network')):
    """Check that the given network is present.

    :param uuid_or_name: network UUID or name
    :param net_type: human-readable network type for error messages
    :return: network UUID
    :raises: MissingParameterValue if uuid_or_name is empty
    :raises: NetworkError on failure to contact Neutron
    :raises: InvalidParameterValue for missing or duplicated network
    """
    if not uuid_or_name:
        raise exception.MissingParameterValue(
            _('UUID or name of %s is not set in configuration') % net_type)

    client = get_client()
    network = _get_network_by_uuid_or_name(client, uuid_or_name,
                                           net_type=net_type, fields=['id'])
    return network['id']


def validate_port_info(node, port):
    """Check that port contains enough information for deploy.

    Neutron network interface requires that local_link_information field is
    filled before we can use this port.

    :param node: Ironic node object.
    :param port: Ironic port object.
    :returns: True if port info is valid, False otherwise.
    """
    # Note(moshele): client-id in the port extra field indicates an InfiniBand
    # port.  In this case we don't require local_link_connection to be
    # populated because the network topology is discoverable by the Infiniband
    # Subnet Manager.
    if port.extra.get('client-id'):
        return True
    if (node.network_interface == 'neutron' and
            not port.local_link_connection):
        LOG.warning("The local_link_connection is required for "
                    "'neutron' network interface and is not present "
                    "in the nodes %(node)s port %(port)s",
                    {'node': node.uuid, 'port': port.uuid})
        return False

    return True


def _get_network_by_uuid_or_name(client, uuid_or_name, net_type=_('network'),
                                 **params):
    """Return a neutron network by UUID or name.

    :param client: A Neutron client object.
    :param uuid_or_name: network UUID or name
    :param net_type: human-readable network type for error messages
    :param params: Additional parameters to pass to the neutron client
        list_networks method.
    :returns: A dict describing the neutron network.
    :raises: NetworkError on failure to contact Neutron
    :raises: InvalidParameterValue for missing or duplicated network
    """
    if uuidutils.is_uuid_like(uuid_or_name):
        params['id'] = uuid_or_name
    else:
        params['name'] = uuid_or_name

    try:
        networks = client.list_networks(**params)
    except neutron_exceptions.NeutronClientException as exc:
        raise exception.NetworkError(_('Could not retrieve network list: %s') %
                                     exc)

    LOG.debug('Got list of networks matching %(cond)s: %(result)s',
              {'cond': params, 'result': networks})
    networks = networks.get('networks', [])
    if not networks:
        raise exception.InvalidParameterValue(
            _('%(type)s with name or UUID %(uuid_or_name)s was not found') %
            {'type': net_type, 'uuid_or_name': uuid_or_name})
    elif len(networks) > 1:
        network_ids = [n['id'] for n in networks]
        raise exception.InvalidParameterValue(
            _('More than one %(type)s was found for name %(name)s: %(nets)s') %
            {'name': uuid_or_name, 'nets': ', '.join(network_ids),
             'type': net_type})
    return networks[0]


def _get_port_by_uuid(client, port_uuid, **params):
    """Return a neutron port by UUID.

    :param client: A Neutron client object.
    :param port_uuid: UUID of a Neutron port to query.
    :param params: Additional parameters to pass to the neutron client
        show_port method.
    :returns: A dict describing the neutron port.
    :raises: InvalidParameterValue if the port does not exist.
    :raises: NetworkError on failure to contact Neutron.
    """
    try:
        port = client.show_port(port_uuid, **params)
    except neutron_exceptions.PortNotFoundClient:
        raise exception.InvalidParameterValue(
            _('Neutron port %(port_uuid)s was not found') %
            {'port_uuid': port_uuid})
    except neutron_exceptions.NeutronClientException as exc:
        raise exception.NetworkError(_('Could not retrieve neutron port: %s') %
                                     exc)
    return port['port']


def get_physnets_by_port_uuid(client, port_uuid):
    """Return the set of physical networks associated with a neutron port.

    Query the network to which the port is attached and return the set of
    physical networks associated with the segments in that network.

    :param client: A Neutron client object.
    :param port_uuid: UUID of a Neutron port to query.
    :returns: A set of physical networks.
    :raises: NetworkError if the network query fails.
    :raises: InvalidParameterValue for missing network.
    """
    port = _get_port_by_uuid(client, port_uuid, fields=['network_id'])
    network_uuid = port['network_id']

    fields = [PHYSNET_PARAM_NAME, SEGMENTS_PARAM_NAME]
    network = _get_network_by_uuid_or_name(client, network_uuid, fields=fields)

    if SEGMENTS_PARAM_NAME in network:
        # A network with multiple segments will have a 'segments' parameter
        # which will contain a list of segments. Each segment should have a
        # 'provider:physical_network' parameter which contains the physical
        # network of the segment.
        segments = network[SEGMENTS_PARAM_NAME]
    else:
        # A network with a single segment will have a
        # 'provider:physical_network' parameter which contains the network's
        # physical network.
        segments = [network]

    return set(segment[PHYSNET_PARAM_NAME]
               for segment in segments
               if segment[PHYSNET_PARAM_NAME])


class NeutronNetworkInterfaceMixin(object):

    _cleaning_network_uuid = None
    _provisioning_network_uuid = None

    def get_cleaning_network_uuid(self):
        if self._cleaning_network_uuid is None:
            self._cleaning_network_uuid = validate_network(
                CONF.neutron.cleaning_network,
                _('cleaning network'))
        return self._cleaning_network_uuid

    def get_provisioning_network_uuid(self):
        if self._provisioning_network_uuid is None:
            self._provisioning_network_uuid = validate_network(
                CONF.neutron.provisioning_network,
                _('provisioning network'))
        return self._provisioning_network_uuid
