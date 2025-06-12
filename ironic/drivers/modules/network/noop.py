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

from ironic.drivers import base


class NoopNetwork(base.NetworkInterface):
    """Noop network interface."""

    def port_changed(self, task, port_obj):
        """Handle any actions required when a port changes

        :param task: a TaskManager instance.
        :param port_obj: a changed Port object.
        :raises: Conflict, FailedToUpdateDHCPOptOnPort
        """
        pass

    def portgroup_changed(self, task, portgroup_obj):
        """Handle any actions required when a portgroup changes

        :param task: a TaskManager instance.
        :param portgroup_obj: a changed Portgroup object.
        :raises: Conflict, FailedToUpdateDHCPOptOnPort
        """
        pass

    def vif_attach(self, task, vif_info):
        """Attach a virtual network interface to a node

        :param task: A TaskManager instance.
        :param vif_info: a dictionary of information about a VIF.
            It must have an 'id' key, whose value is a unique
            identifier for that VIF.
        :raises: NetworkError, VifAlreadyAttached, NoFreePhysicalPorts
        """
        pass

    def vif_detach(self, task, vif_id):
        """Detach a virtual network interface from a node

        :param task: A TaskManager instance.
        :param vif_id: A VIF ID to detach
        :raises: NetworkError, VifNotAttached
        """
        pass

    def vif_list(self, task):
        """List attached VIF IDs for a node.

        :param task: A TaskManager instance.
        :returns: List of VIF dictionaries, each dictionary will have an 'id'
            entry with the ID of the VIF.
        """
        return []

    def get_current_vif(self, task, p_obj):
        """Returns the currently used VIF associated with port or portgroup

        We are booting the node only in one network at a time, and presence of
        cleaning_vif_port_id means we're doing cleaning,
        of provisioning_vif_port_id - provisioning
        of rescuing_vif_port_id - rescuing.
        Otherwise it's a tenant network

        :param task: A TaskManager instance.
        :param p_obj: Ironic port or portgroup object.
        :returns: VIF ID associated with p_obj or None.
        """
        pass

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
        pass

    def add_cleaning_network(self, task):
        """Add the cleaning network to a node.

        :param task: A TaskManager instance.
        """
        pass

    def remove_cleaning_network(self, task):
        """Remove the cleaning network from a node.

        :param task: A TaskManager instance.
        """
        pass

    def validate_inspection(self, task):
        """Validate that the node has required properties for inspection.

        :param task: A TaskManager instance with the node being checked
        """
        pass
