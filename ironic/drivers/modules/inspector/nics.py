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

from oslo_log import log as logging
from oslo_utils import netutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF
from ironic import objects

LOG = logging.getLogger(__name__)


def get_pxe_mac(inventory):
    """Get MAC address of the PXE interface."""
    pxe_mac = inventory.get('boot', {}).get('pxe_interface')
    if pxe_mac and '-' in pxe_mac:
        # pxelinux format: 01-aa-bb-cc-dd-ee-ff
        pxe_mac = pxe_mac.split('-', 1)[1]
        pxe_mac = pxe_mac.replace('-', ':').lower()
    return pxe_mac


def get_interfaces(node, inventory):
    """Convert inventory to a dict with interfaces.

    :return: dict interface name -> interface (for valid interfaces).
    """
    result = {}
    pxe_mac = get_pxe_mac(inventory)

    for iface in inventory['interfaces']:
        name = iface.get('name')
        mac = iface.get('mac_address')
        ipv4_address = iface.get('ipv4_address')
        ipv6_address = iface.get('ipv6_address')
        # NOTE(kaifeng) ipv6 address may in the form of fd00::1%enp2s0,
        # which is not supported by netaddr, remove the suffix if exists.
        if ipv6_address and '%' in ipv6_address:
            ipv6_address = ipv6_address.split('%')[0]
        ip = ipv4_address or ipv6_address
        client_id = iface.get('client_id')

        if not name:
            LOG.error('Malformed interface record for node %(node)s: %(if)s',
                      {'node': node.uuid, 'if': iface})
            continue

        if not mac:
            LOG.debug('Skipping interface %(if)s for node %(node)s without '
                      'link information',
                      {'node': node.uuid, 'if': iface})
            continue

        if not netutils.is_valid_mac(mac):
            LOG.warning('MAC address of interface %(if)s of node %(node)s '
                        'is not valid, skipping',
                        {'node': node.uuid, 'if': iface})
            continue

        mac = mac.lower()

        LOG.debug('Found interface %(name)s with MAC "%(mac)s", '
                  'IP address "%(ip)s" and client_id "%(client_id)s" '
                  'for node %(node)s',
                  {'name': name, 'mac': mac, 'ip': ip,
                   'client_id': client_id, 'node': node.uuid})
        result[name] = dict(iface, pxe_enabled=(mac == pxe_mac),
                            # IPv6 address without scope.
                            ipv6_address=ipv6_address)

    return result


def validate_interfaces(node, inventory, interfaces):
    """Validate interfaces on correctness and suitability.

    :return: dict interface name -> interface.
    """
    if not interfaces:
        raise exception.InvalidNodeInventory(
            node=node.uuid,
            reason=_('no valid network interfaces'))

    pxe_mac = get_pxe_mac(inventory)
    if not pxe_mac and CONF.inspector.add_ports == 'pxe':
        LOG.warning('No boot interface provided in the inventory for node '
                    '%s, will add all ports with IP addresses', node.uuid)

    result = {}

    for name, iface in interfaces.items():
        ip = iface.get('ipv4_address') or iface.get('ipv6_address')
        pxe = iface.get('pxe_enabled', True)

        if name == 'lo' or (ip and utils.is_loopback(ip)):
            LOG.debug('Skipping local interface %(iface)s for node %(node)s',
                      {'iface': name, 'node': node.uuid})
            continue

        if CONF.inspector.add_ports == 'pxe' and pxe_mac and not pxe:
            LOG.debug('Skipping interface %(iface)s for node %(node)s as it '
                      'was not PXE booting and add_ports is set to "pxe"',
                      {'iface': name, 'node': node.uuid})
            continue

        if CONF.inspector.add_ports == 'active' and not ip:
            LOG.debug('Skipping interface %(iface)s for node %(node)s as it '
                      'did not have an IP address assigned during the ramdisk '
                      'run and add_ports is set to "active"',
                      {'iface': name, 'node': node.uuid})
            continue

        result[name] = iface.copy()

    if not result:
        raise exception.InvalidNodeInventory(
            node=node.uuid,
            reason=_('no network interfaces match the configuration '
                     '(add_ports set to "%s")') % CONF.inspector.add_ports)
    return result


def add_ports(task, interfaces):
    """Add ports for all previously validated interfaces."""
    for iface in interfaces.values():
        mac = iface['mac_address']
        extra = {}
        if iface.get('client_id'):
            extra['client-id'] = iface['client_id']
        port_dict = {'address': mac, 'node_id': task.node.id,
                     'pxe_enabled': iface['pxe_enabled'], 'extra': extra}
        port = objects.Port(task.context, **port_dict)
        try:
            port.create()
            LOG.info("Port created for MAC address %(address)s for "
                     "node %(node)s%(pxe)s",
                     {'address': mac, 'node': task.node.uuid,
                      'pxe': ' (PXE booting)' if iface['pxe_enabled'] else ''})
        except exception.MACAlreadyExists:
            LOG.info("Port already exists for MAC address %(address)s "
                     "for node %(node)s",
                     {'address': mac, 'node': task.node.uuid})


def update_ports(task, all_interfaces, valid_macs):
    """Update ports to match the valid MACs.

    Depending on the value of ``[inspector]keep_ports``, some ports may be
    removed.
    """
    # TODO(dtantsur): no port update for active nodes (when supported)

    if CONF.inspector.keep_ports == 'present':
        expected_macs = {iface['mac_address']
                         for iface in all_interfaces.values()}
    elif CONF.inspector.keep_ports == 'added':
        expected_macs = set(valid_macs)
    else:
        expected_macs = None  # unused

    pxe_macs = {iface['mac_address'] for iface in all_interfaces.values()
                if iface['pxe_enabled']}

    for port in objects.Port.list_by_node_id(task.context, task.node.id):
        if expected_macs and port.address not in expected_macs:
            expected_str = ', '.join(sorted(expected_macs))
            LOG.info("Deleting port %(port)s of node %(node)s as its MAC "
                     "%(mac)s is not in the expected MAC list [%(expected)s]",
                     {'port': port.uuid, 'mac': port.address,
                      'node': task.node.uuid, 'expected': expected_str})
            port.destroy()
        elif CONF.inspector.update_pxe_enabled:
            pxe_enabled = port.address in pxe_macs
            if pxe_enabled != port.pxe_enabled:
                LOG.debug('Changing pxe_enabled=%(val)s on port %(port)s '
                          'of node %(node)s to match the inventory',
                          {'port': port.address, 'val': pxe_enabled,
                           'node': task.node.uuid})
                port.pxe_enabled = pxe_enabled
                port.save()


def process_interfaces(task, inventory, plugin_data):
    """Process network interfaces in the inventory."""
    # TODO(dtantsur): this function will become two hooks in the future.
    all_interfaces = get_interfaces(task.node, inventory)
    interfaces = validate_interfaces(task.node, inventory, all_interfaces)
    valid_macs = [iface['mac_address'] for iface in interfaces.values()]

    plugin_data['all_interfaces'] = all_interfaces
    plugin_data['valid_interfaces'] = interfaces
    plugin_data['macs'] = valid_macs

    if CONF.inspector.add_ports != 'disabled':
        add_ports(task, interfaces)

    update_ports(task, all_interfaces, valid_macs)
