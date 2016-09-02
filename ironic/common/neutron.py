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

from ironic.common import exception
from ironic.common.i18n import _, _LE, _LI, _LW
from ironic.common import keystone
from ironic.conf import CONF

LOG = log.getLogger(__name__)

DEFAULT_NEUTRON_URL = 'http://%s:9696' % CONF.my_ip

_NEUTRON_SESSION = None


def _get_neutron_session():
    global _NEUTRON_SESSION
    if not _NEUTRON_SESSION:
        _NEUTRON_SESSION = keystone.get_session('neutron')
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
                session, service_type='network')
            params.update({
                'timeout': CONF.neutron.url_timeout or CONF.neutron.timeout,
                'insecure': CONF.neutron.insecure,
                'ca_cert': CONF.neutron.cafile})

    return clientv20.Client(**params)


def add_ports_to_network(task, network_uuid, is_flat=False):
    """Create neutron ports to boot the ramdisk.

    Create neutron ports for each pxe_enabled port on task.node to boot
    the ramdisk.

    :param task: a TaskManager instance.
    :param network_uuid: UUID of a neutron network where ports will be
        created.
    :param is_flat: Indicates whether it is a flat network or not.
    :raises: NetworkError
    :returns: a dictionary in the form {port.uuid: neutron_port['id']}
    """
    client = get_client(task.context.auth_token)
    node = task.node

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
        }
    }

    if not is_flat:
        # NOTE(vdrok): It seems that change
        # I437290affd8eb87177d0626bf7935a165859cbdd to neutron broke the
        # possibility to always bind port. Set binding:host_id only in
        # case of non flat network.
        body['port']['binding:host_id'] = node.uuid

    # Since instance_uuid will not be available during cleaning
    # operations, we need to check that and populate them only when
    # available
    body['port']['device_id'] = node.instance_uuid or node.uuid

    ports = {}
    failures = []
    portmap = get_node_portmap(task)
    pxe_enabled_ports = [p for p in task.ports if p.pxe_enabled]
    for ironic_port in pxe_enabled_ports:
        body['port']['mac_address'] = ironic_port.address
        binding_profile = {'local_link_information':
                           [portmap[ironic_port.uuid]]}
        body['port']['binding:profile'] = binding_profile
        client_id = ironic_port.extra.get('client-id')
        if client_id:
            client_id_opt = {'opt_name': 'client-id', 'opt_value': client_id}
            extra_dhcp_opts = body['port'].get('extra_dhcp_opts', [])
            extra_dhcp_opts.append(client_id_opt)
            body['port']['extra_dhcp_opts'] = extra_dhcp_opts
        try:
            port = client.create_port(body)
        except neutron_exceptions.NeutronClientException as e:
            failures.append(ironic_port.uuid)
            LOG.warning(_LW("Could not create neutron port for node's "
                            "%(node)s port %(ir-port) on the neutron "
                            "network %(net)s. %(exc)s"),
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
            LOG.warning(_LW("Some errors were encountered when updating "
                            "vif_port_id for node %(node)s on "
                            "the following ports: %(ports)s."),
                        {'node': node.uuid, 'ports': failures})
    else:
        LOG.info(_LI('Successfully created ports for node %(node_uuid)s in '
                     'network %(net)s.'),
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
    client = get_client(task.context.auth_token)
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
        except neutron_exceptions.NeutronClientException as e:
            msg = (_('Could not remove VIF %(vif)s of node %(node)s, possibly '
                     'a network issue: %(exc)s') %
                   {'vif': port['id'], 'node': node_uuid, 'exc': e})
            LOG.exception(msg)
            raise exception.NetworkError(msg)

    LOG.info(_LI('Successfully removed node %(node_uuid)s neutron ports.'),
             {'node_uuid': node_uuid})


def get_node_portmap(task):
    """Extract the switch port information for the node.

    :param task: a task containing the Node object.
    :returns: a dictionary in the form {port.uuid: port.local_link_connection}
    """

    portmap = {}
    for port in task.ports:
        portmap[port.uuid] = port.local_link_connection
    return portmap
    # TODO(jroll) raise InvalidParameterValue if a port doesn't have the
    # necessary info? (probably)


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
        LOG.exception(_LE(
            'Failed to rollback port changes for node %(node)s '
            'on network %(network)s'), {'node': task.node.uuid,
                                        'network': network_uuid})
