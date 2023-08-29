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

from ironic.common import exception
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import base
from ironic import objects

LOG = logging.getLogger(__name__)


class PortsHook(base.InspectionHook):
    """Hook to create ironic ports."""

    dependencies = ['validate-interfaces']

    def __call__(self, task, inventory, plugin_data):
        if CONF.inspector.add_ports != 'disabled':
            add_ports(task, plugin_data['valid_interfaces'])

        update_ports(task, plugin_data['all_interfaces'], plugin_data['macs'])


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
                LOG.debug("Changing pxe_enabled=%(val)s on port %(port)s "
                          "of node %(node)s to match the inventory",
                          {'port': port.address, 'val': pxe_enabled,
                           'node': task.node.uuid})
                port.pxe_enabled = pxe_enabled
                port.save()
