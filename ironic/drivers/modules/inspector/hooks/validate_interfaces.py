# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_log import log as logging
from oslo_utils import netutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import base

LOG = logging.getLogger(__name__)


class ValidateInterfacesHook(base.InspectionHook):
    """Hook to validate network interfaces."""

    def preprocess(self, task, inventory, plugin_data):
        all_interfaces = get_interfaces(task.node, inventory)
        valid_interfaces = validate_interfaces(task.node, inventory,
                                               all_interfaces)
        valid_macs = [iface['mac_address'] for iface in
                      valid_interfaces.values()]

        plugin_data['all_interfaces'] = all_interfaces
        plugin_data['valid_interfaces'] = valid_interfaces
        plugin_data['macs'] = valid_macs

    def __call__(self, task, inventory, plugin_data):
        pass


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


def get_pxe_mac(inventory):
    """Get MAC address of the PXE interface."""
    pxe_mac = inventory.get('boot', {}).get('pxe_interface')
    if pxe_mac and '-' in pxe_mac:
        # pxelinux format: 01-aa-bb-cc-dd-ee-ff
        pxe_mac = pxe_mac.split('-', 1)[1]
        pxe_mac = pxe_mac.replace('-', ':').lower()
    return pxe_mac
