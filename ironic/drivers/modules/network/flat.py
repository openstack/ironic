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

"""
Flat network interface. Useful for shared, flat networks.
"""

from oslo_config import cfg
from oslo_log import log
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _, _LI, _LW
from ironic.common import neutron
from ironic.drivers import base


LOG = log.getLogger(__name__)

CONF = cfg.CONF


class FlatNetwork(base.NetworkInterface):
    """Flat network interface."""

    def __init__(self):
        cleaning_net = CONF.neutron.cleaning_network_uuid
        # TODO(vdrok): Switch to DriverLoadError in Ocata
        if not uuidutils.is_uuid_like(cleaning_net):
            LOG.warning(_LW(
                'Please specify a valid UUID for '
                '[neutron]/cleaning_network_uuid configuration option so that '
                'this interface is able to perform cleaning. It will be '
                'required starting with the Ocata release, and if not '
                'specified then, the conductor service will fail to start if '
                '"flat" is in the list of values for '
                '[DEFAULT]enabled_network_interfaces configuration option.'))

    def add_provisioning_network(self, task):
        """Add the provisioning network to a node.

        :param task: A TaskManager instance.
        """
        pass

    def remove_provisioning_network(self, task):
        """Remove the provisioning network from a node.

        :param task: A TaskManager instance.
        """
        pass

    def configure_tenant_networks(self, task):
        """Configure tenant networks for a node.

        :param task: A TaskManager instance.
        """
        pass

    def unconfigure_tenant_networks(self, task):
        """Unconfigure tenant networks for a node.

        :param task: A TaskManager instance.
        """
        for port in task.ports:
            extra_dict = port.extra
            extra_dict.pop('vif_port_id', None)
            port.extra = extra_dict
            port.save()

    def add_cleaning_network(self, task):
        """Add the cleaning network to a node.

        :param task: A TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        :raises: NetworkError, InvalidParameterValue
        """
        if not uuidutils.is_uuid_like(CONF.neutron.cleaning_network_uuid):
            raise exception.InvalidParameterValue(_(
                'You must provide a valid cleaning network UUID in '
                '[neutron]cleaning_network_uuid configuration option.'))
        # If we have left over ports from a previous cleaning, remove them
        neutron.rollback_ports(task, CONF.neutron.cleaning_network_uuid)
        LOG.info(_LI('Adding cleaning network to node %s'), task.node.uuid)
        vifs = neutron.add_ports_to_network(
            task, CONF.neutron.cleaning_network_uuid, is_flat=True)
        for port in task.ports:
            if port.uuid in vifs:
                internal_info = port.internal_info
                internal_info['cleaning_vif_port_id'] = vifs[port.uuid]
                port.internal_info = internal_info
                port.save()
        return vifs

    def remove_cleaning_network(self, task):
        """Remove the cleaning network from a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        LOG.info(_LI('Removing ports from cleaning network for node %s'),
                 task.node.uuid)
        neutron.remove_ports_from_network(
            task, CONF.neutron.cleaning_network_uuid)
        for port in task.ports:
            if 'cleaning_vif_port_id' in port.internal_info:
                internal_info = port.internal_info
                del internal_info['cleaning_vif_port_id']
                port.internal_info = internal_info
                port.save()
