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
Ironic Networking Network Interface

This is a network interface designed for standalone Ironic deployments that
require minimal network configuration. It implements all required
NetworkInterface methods but performs no actual operations, making it suitable
for environments where external network configuration is handled separately or
not required.
"""

from oslo_config import cfg

import jsonschema
from jsonschema import exceptions as json_schema_exc
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import network
from ironic.common import states
from ironic.conf import ironic_networking
from ironic.drivers import base
from ironic.drivers.modules.network import ironic_networking_schemas
from ironic.networking import api as networking_api

LOG = log.getLogger(__name__)

CONF = cfg.CONF

# Register networking configuration options
ironic_networking.register_opts(CONF)


class IronicNetworking(base.NetworkInterface):
    """Ironic Networking network interface.

    This network interface is designed for standalone Ironic deployments
    where configuration of switch ports should be handled by Ironic.

    Port Configuration:
    This interface validates and processes ports that have an 'extra' property
    containing a 'switchport' sub-property. The switchport configuration must
    conform to the SWITCHPORT_SCHEMA defined in ironic_networking_schemas.py.

    Expected switchport configuration format:
    - mode: 'access', 'trunk', or 'hybrid'
    - native_vlan: VLAN ID (required)
    - allowed_vlans: List of VLAN IDs (required for trunk/hybrid modes only)
    - lag_name: Optional LAG name

    Portgroup Configuration:
    This interface validates and processes portgroups that have an 'extra'
    property containing a 'lag' sub-property. The lag configuration must
    conform to the LAG_SCHEMA defined in ironic_networking_schemas.py.
    """

    def __init__(self):
        """Initialize the IronicNetworking interface."""
        super(IronicNetworking, self).__init__()

        self.switchport_schema = ironic_networking_schemas.SWITCHPORT_SCHEMA
        self.lag_schema = ironic_networking_schemas.LAG_SCHEMA

    def validate(self, task):
        """Validate the network interface configuration.

        For the ironic networking interface, this validates any ports
        that have switchport configuration in their 'extra' field and any
        portgroups that have LAG configuration in their 'extra' field.

        :param task: A TaskManager instance.
        :raises: InvalidParameterValue if switchport or lag
                 configuration is invalid.
        """
        # Validate ports with switchport configuration
        for port in task.ports:
            self._validate_port_switchport_config(task, port)

        # Validate portgroups with LAG configuration
        for portgroup in task.portgroups:
            self._validate_portgroup_lag_config(portgroup)
            self._validate_portgroup_member_ports(task, portgroup)

    @staticmethod
    def _get_network_mode_and_vlan(task, network_type):
        """Get the mode and native_vlan for a given network type.

        The value is determined by first checking the node's driver_info
        for an override, and then falling back to the global conf option.

        :param task: A TaskManager instance.
        :param network_type: One of 'cleaning', 'provisioning', 'servicing',
                             'rescuing', or 'inspection'.
        :returns: Tuple of (mode, native_vlan, allowed_vlans) or
                  (None, None, None) if not set.
        :raises: InvalidParameterValue if the network value is set but
                 has an invalid format.
        """
        node = task.node
        driver_info_key = f'{network_type}_network'
        conf_key = f'{network_type}_network'

        # Check driver_info override
        network_value = node.driver_info.get(driver_info_key)
        if not network_value:
            # Fallback to global conf
            try:
                network_value = getattr(CONF.ironic_networking, conf_key, '')
                LOG.debug("Retrieved config value for %s: %s",
                          conf_key, network_value)
            except AttributeError as e:
                LOG.warning(
                    "Networking configuration not available or option '%s' "
                    "not found: %s", conf_key, e)
                network_value = ''

        if not network_value:
            LOG.warning(
                "No network configured for network type '%s'. "
                "Falling back to port's switchport attributes.",
                network_type
            )
            return None, None, None

        # Expected format:
        # {access|trunk|hybrid}/native_vlan=VLAN_ID/[allowed_vlans=CSV]
        try:
            # TODO(alegacy): Add support for allowed_vlans
            mode_part, vlan_part = network_value.split('/', 1)
            mode = mode_part.strip()
            if vlan_part.startswith('native_vlan='):
                native_vlan = int(vlan_part.split('=', 1)[1])
            else:
                native_vlan = None
        except ValueError as e:
            raise exception.InvalidParameterValue(
                _("Invalid %(network_type)s network value '%(value)s'. "
                  "Expected: {access|trunk|hybrid}/native_vlan=VLAN_ID. "
                  "Error: %(error)s")
                % {'network_type': network_type, 'value': network_value,
                   'error': e})

        LOG.debug(
            "Called _get_network_mode_and_vlan with node=%(node)s, "
            "network_type=%(network_type)s; returning mode=%(mode)s, "
            "native_vlan=%(native_vlan)s from value='%(value)s'",
            {'node': task.node.uuid, 'network_type': network_type,
             'mode': mode, 'native_vlan': native_vlan,
             'value': network_value})

        # TODO(alegacy): Add support for allowed_vlans from above
        return mode, native_vlan, None

    def _validate_network_requirements(self, task, network_type):
        """Validate that at least one port has required network configuration.

        This method checks that at least one port on the node has both
        local_link_connection information and valid mode/native_vlan
        configuration either from the network configuration or the port's
        switchport configuration.

        :param task: A TaskManager instance.
        :param network_type: The type of network to validate (e.g.,
                             'cleaning', 'rescuing', 'inspection',
                             'servicing').
        :raises: InvalidParameterValue if unable to parse network configuration
        """
        for port in task.ports:
            # Check if port has local_link_connection
            if not port.local_link_connection:
                continue

            # Try to get switchport info from port.extra
            switchport = port.extra.get('switchport') if port.extra else None
            if not switchport:
                continue

            # Get the mode and native_vlan for the network type
            mode, native_vlan, ignored_allowed_vlans = (
                self._get_network_mode_and_vlan(task, network_type)
            )

            # If network configuration is not set, use port's switchport info
            if mode is None or native_vlan is None:
                mode = switchport.get('mode')
                native_vlan = switchport.get('native_vlan')

            # If we have valid configuration, we found at least one valid port
            if mode and native_vlan is not None:
                return

        # TODO(alegacy): Need to consider how far the validation should go.
        # For example, the initial inspection may not have any ports so no
        # validation is required, but then later we could cause issues with
        # cleaning or rescuing if we require ports to be present and
        # configured.  Needs more thought.  Maybe just enforce that ports
        # that have switchport configuration must have a
        # local_link_connection?
        LOG.warning(
            _("Node %(node)s requires at least one port with "
              "local_link_connection and valid mode/native_vlan "
              "configuration for %(network_type)s network"),
            {'node': task.node.uuid, 'network_type': network_type})

    def _validate_port_switchport_config(self, task, port):
        """Validate switchport configuration in port's extra field.

        :param task: A TaskManager instance.
        :param port: A Port object.
        :raises: InvalidParameterValue if switchport configuration is invalid.
        """
        if not port.extra:
            return

        switchport_config = port.extra.get('switchport')
        if not switchport_config:
            return

        try:
            jsonschema.validate(switchport_config, self.switchport_schema)
        except json_schema_exc.ValidationError as e:
            raise exception.InvalidParameterValue(
                _("Invalid switchport configuration for port %(port)s: "
                  "%(error)s") % {'port': port.uuid, 'error': e})

        # Validate that PXE-enabled ports use access mode
        if port.pxe_enabled:
            mode = switchport_config.get('mode')
            if mode != 'access':
                raise exception.InvalidParameterValue(
                    _("Port %(port)s is PXE-enabled but has switchport mode "
                      "'%(mode)s'. PXE-enabled ports must use 'access' mode "
                      "when switchport configuration is present.")
                    % {'port': port.uuid, 'mode': mode})

        # Validate that local_link_connection has required fields
        if not port.local_link_connection:
            # Inspection is the only state where not having a
            # local_link_connection is permitted since we expect it to be
            # populated by LLDP if it is available.  If the intent is not to
            # use inspection then the user should have manually populated
            # this field.
            if task.node.provision_state not in states.INSPECTION_STATES:
                raise exception.InvalidParameterValue(
                    _("Port %(port)s has switchport configuration but is "
                      "missing local_link_connection in state: %(state)s.")
                    % {'port': port.uuid, 'state': task.node.provision_state})

            # During inspection, we allow this and just log it hoping that
            # inspection will populate it.
            LOG.debug(
                "Port %s is missing local_link_connection in state: %s",
                port.uuid, task.node.provision_state)
            return

        switch_id = port.local_link_connection.get('switch_id')
        port_id = port.local_link_connection.get('port_id')

        errors = []
        if not switch_id:
            errors.append("'switch_id'")
        if not port_id:
            errors.append("'port_id'")

        if errors:
            raise exception.InvalidParameterValue(
                _("Port %(port)s local_link_connection missing required "
                  "field(s): %(fields)s")
                % {'port': port.uuid, 'fields': ', '.join(errors)})

    def _validate_portgroup_lag_config(self, portgroup):
        """Validate LAG configuration in portgroup's extra field.

        :param portgroup: A Portgroup object.
        :raises: InvalidParameterValue if LAG configuration is
                 invalid.
        """
        if not portgroup.extra:
            return

        lag_config = portgroup.extra.get('lag')
        if not lag_config:
            return

        try:
            jsonschema.validate(lag_config, self.lag_schema)
            LOG.debug("Portgroup %s LAG configuration is valid",
                      portgroup.uuid)
        except json_schema_exc.ValidationError as e:
            raise exception.InvalidParameterValue(
                _("Invalid LAG configuration for portgroup "
                  "%(portgroup)s: %(error)s")
                % {'portgroup': portgroup.uuid, 'error': e})

    @staticmethod
    def _validate_portgroup_member_ports(task, portgroup):
        """Validate that portgroup member ports have switchport configuration.

        :param task: A TaskManager instance.
        :param portgroup: A Portgroup object.
        :raises: InvalidParameterValue if member ports lack switchport
                 configuration.
        """
        if not portgroup.extra or not portgroup.extra.get('lag'):
            return

        # Find member ports of this portgroup
        member_ports = [port for port in task.ports
                        if port.portgroup_id == portgroup.id]

        if not member_ports:
            raise exception.InvalidParameterValue(
                _("Portgroup %(portgroup)s has LAG configuration "
                  "but no member ports") % {'portgroup': portgroup.uuid})

        # Check that all member ports have switchport configuration
        ports_without_switchport = []
        ports_without_local_link = []
        for port in member_ports:
            if not port.extra or not port.extra.get('switchport'):
                ports_without_switchport.append(port.uuid)
            elif (not port.local_link_connection
                  or not port.local_link_connection.get('switch_id')
                  or not port.local_link_connection.get('port_id')):
                ports_without_local_link.append(port.uuid)

        errors = []
        if ports_without_switchport:
            errors.append(
                _("member ports %(ports)s lack switchport configuration")
                % {'ports': ', '.join(ports_without_switchport)})
        if ports_without_local_link:
            errors.append(
                _("member ports %(ports)s lack proper local_link_connection "
                  "with switch_id and port_id fields")
                % {'ports': ', '.join(ports_without_local_link)})

        if errors:
            raise exception.InvalidParameterValue(
                _("Portgroup %(portgroup)s has LAG configuration but: "
                  "%(errors)s")
                % {'portgroup': portgroup.uuid, 'errors': '; '.join(errors)})

    @staticmethod
    def _get_portgroup_switch_ids(task, portgroup):
        """Get switch IDs from member ports of a portgroup.

        :param task: A TaskManager instance.
        :param portgroup: A Portgroup object.
        :returns: List of unique switch IDs from member ports, or None if
                  no valid ports.
        """
        if not portgroup.extra or not portgroup.extra.get('lag'):
            return None

        # Find member ports of this portgroup
        member_ports = [port for port in task.ports
                        if port.portgroup_id == portgroup.id]

        if not member_ports:
            return None

        # Extract switch IDs from member ports' local_link_connection
        switch_ids = set()
        for port in member_ports:
            if (port.extra and port.extra.get('switchport')
                    and port.local_link_connection):
                switch_id = port.local_link_connection.get('switch_id')
                if switch_id:
                    switch_ids.add(switch_id)

        return list(switch_ids) if switch_ids else None

    @staticmethod
    def _get_portgroup_lag_name(portgroup):
        """Get LAG name from portgroup configuration.

        For now, we'll use the portgroup name as the LAG name.
        This could be enhanced to use a specific field in the future.

        :param portgroup: A Portgroup object.
        :returns: LAG name string.
        """
        if portgroup.name:
            return portgroup.name
        else:
            # TODO(alegacy): naming of LAG instances needs to be re-visited
            # when that part of the feature is completed.  Some switches will
            # want to name the LAG itself and others may have specific naming
            # requirements which may make this tricky at best.
            return f"lag-{portgroup.uuid[:8]}"

    @staticmethod
    def _get_port_switch_info(port):
        """Get switch ID and port name from port's local_link_connection.

        :param port: A Port object.
        :returns: Tuple of (switch_id, port_name) or (None, None) if not
                  available.
        """
        if not port.local_link_connection:
            return None, None

        switch_id = port.local_link_connection.get('switch_id')
        port_name = port.local_link_connection.get('port_id')

        return switch_id, port_name

    @staticmethod
    def _get_port_description(port):
        """Generate description for a port.

        :param port: A Port object.
        :returns: Description string.
        """
        return f"Ironic Port {port.uuid}"

    @staticmethod
    def _get_portgroup_description(portgroup):
        """Generate description for a portgroup.

        :param portgroup: A Portgroup object.
        :returns: Description string.
        """
        return f"Ironic PortGroup {portgroup.uuid}"

    def _resolve_network_configuration(self, task, port_obj, network_type):
        """Resolve network configuration for a port based on network type.

        :param task: A TaskManager instance.
        :param port_obj: A Port object.
        :param network_type: The type of network to resolve configuration for.
        :returns: Tuple of (mode, native_vlan, allowed_vlans).
        :raises: InvalidParameterValue if unable to parse network configuration
        """
        # Try network-specific configuration first
        mode, native_vlan, allowed_vlans = self._get_network_mode_and_vlan(
            task, network_type)

        if mode is None or native_vlan is None:
            # Fallback to port's switchport configuration unless the network
            # is the idle network in which case we simply allow the port to
            # remain unconfigured (or configured to the switch-wide default)
            if network_type == network.IDLE_NETWORK:
                return None, None, None
            switchport = (port_obj.extra.get('switchport', {})
                          if port_obj.extra else {})
            mode = switchport.get('mode')
            native_vlan = switchport.get('native_vlan')
            allowed_vlans = switchport.get('allowed_vlans')

        LOG.debug(
            "Resolving network configuration for port %(port)s, "
            "network_type=%(network_type)s: mode=%(mode)s, "
            "native_vlan=%(native_vlan)s, allowed_vlans=%(allowed_vlans)s",
            {
                'port': getattr(port_obj, 'uuid', None),
                'network_type': network_type,
                'mode': mode,
                'native_vlan': native_vlan,
                'allowed_vlans': allowed_vlans
            })
        return mode, native_vlan, allowed_vlans

    def _get_original_port_config(self, task, port_obj):
        """Get original port configuration before changes.

        Called from port_changed() to retrieve the port's configuration
        from task.ports before the current changes were applied. This
        allows comparison between original and new values to determine
        what network operations are needed.

        :param task: A TaskManager instance.
        :param port_obj: The changed Port object with new values.
        :returns: Tuple of (original_port, original_switchport,
            original_local_link) where original_port is the Port object
            from task.ports, original_switchport is the switchport dict
            from port.extra, and original_local_link is the
            local_link_connection dict. Any value may be None if not found.
        """
        original_port = None
        for port in task.ports:
            if port.uuid == port_obj.uuid:
                original_port = port
                break

        original_switchport = None
        original_local_link = None
        if original_port:
            original_switchport = (original_port.extra.get('switchport')
                                   if original_port.extra else None)
            original_local_link = original_port.local_link_connection

        return original_port, original_switchport, original_local_link

    def _determine_port_changes(self, original_switchport, current_switchport,
                                original_local_link, current_local_link):
        """Determine what changes occurred to the port.

        Called from port_changed() after retrieving original configuration
        to classify the type of change that occurred. The result is used
        to decide which network operations (reset, update, etc.) are needed.

        :param original_switchport: The switchport dict from the original
            port.extra, or None.
        :param current_switchport: The switchport dict from the changed
            port.extra, or None.
        :param original_local_link: The original local_link_connection
            dict, or None.
        :param current_local_link: The current local_link_connection
            dict, or None.
        :returns: Tuple of (switchport_removed, local_link_removed,
            local_link_changed, switchport_changed, switchport_added)
            where each value is a boolean indicating that type of change.
        """
        switchport_removed = original_switchport and not current_switchport
        local_link_removed = original_local_link and not current_local_link
        local_link_changed = (original_local_link != current_local_link
                              and original_local_link
                              and current_local_link)
        switchport_changed = (original_switchport != current_switchport
                              and original_switchport
                              and current_switchport)
        switchport_added = not original_switchport and current_switchport

        return (switchport_removed, local_link_removed, local_link_changed,
                switchport_changed, switchport_added)

    def _handle_port_removal(self, task, port_obj, original_port,
                             original_local_link, original_switchport,
                             active_network_type):
        """Handle port removal cases.

        Called when switchport or local_link_connection is removed from a port.
        Resets the switch port configuration using the original values.

        :param task: A TaskManager instance.
        :param port_obj: The changed Port object.
        :param original_port: The original Port object from task.ports.
        :param original_local_link: The original local_link_connection dict.
        :param original_switchport: The original switchport configuration.
        :param active_network_type: The network type that should be active.
        :raises: InvalidParameterValue if unable to parse network configuration
        :raises: NetworkError if the networking service call fails
        """
        LOG.debug(
            "Port %(port)s switchport or local_link_connection removed",
            {'port': port_obj.uuid})

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        if original_local_link and original_switchport:
            # Get configuration for reset operation using original values
            (original_mode, original_native_vlan,
             original_allowed_vlans) = (
                self._resolve_network_configuration(
                    task, original_port, active_network_type))

            if original_mode and original_native_vlan is not None:
                # Get switch and port info from original state
                switch_id = original_local_link.get('switch_id')
                port_name = original_local_link.get('port_id')

                if switch_id and port_name:
                    result = networking_api.reset_port(
                        task.context, switch_id, port_name,
                        original_native_vlan,
                        allowed_vlans=original_allowed_vlans,
                        default_vlan=idle_native_vlan)
                    LOG.debug(
                        "Successfully reset port %(port_name)s on "
                        "switch %(switch_id)s via networking service: "
                        "%(result)s",
                        {'port_name': port_name,
                         'switch_id': switch_id,
                         'result': result})
                else:
                    LOG.warning(
                        "Cannot reset port %(port)s: missing "
                        "switch_id or port_id",
                        {'port': port_obj.uuid})
            elif active_network_type != 'idle':
                LOG.warning(
                    "Cannot reset port %(port)s: missing mode or "
                    "native_vlan for %(active_network_type)s network",
                    {'port': port_obj.uuid})

    def _handle_local_link_change(self, task, port_obj, original_port,
                                  original_local_link, original_switchport,
                                  active_network_type):
        """Handle local_link_connection change (requires reset + update).

        Called when the local_link_connection changes on a port. Resets the
        old switch port configuration before the new configuration is applied.

        :param task: A TaskManager instance.
        :param port_obj: The changed Port object.
        :param original_port: The original Port object from task.ports.
        :param original_local_link: The original local_link_connection dict.
        :param original_switchport: The original switchport configuration.
        :param active_network_type: The network type that should be active.
        :raises: InvalidParameterValue if unable to parse network configuration
        :raises: NetworkError if the networking service call fails
        """
        LOG.debug("Port %(port)s local_link_connection changed",
                  {'port': port_obj.uuid})

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        # First, reset the old port
        if original_local_link and original_switchport:
            (original_mode, original_native_vlan,
             original_allowed_vlans) = (
                self._resolve_network_configuration(
                    task, original_port, active_network_type))

            if original_mode and original_native_vlan is not None:
                switch_id = original_local_link.get('switch_id')
                port_name = original_local_link.get('port_id')

                if switch_id and port_name:
                    result = networking_api.reset_port(
                        task.context, switch_id, port_name,
                        original_native_vlan,
                        allowed_vlans=original_allowed_vlans,
                        default_vlan=idle_native_vlan)
                    LOG.debug(
                        "Successfully reset old port %(port_name)s "
                        "on switch %(switch_id)s via networking "
                        "service: %(result)s",
                        {'port_name': port_name,
                         'switch_id': switch_id,
                         'result': result})

    def _handle_switchport_update(self, task, port_obj, current_local_link,
                                  current_switchport, active_network_type,
                                  switchport_added):
        """Handle switchport addition or modification.

        Called when switchport configuration is added or changed on a port.
        Validates the configuration and updates the switch port.

        :param task: A TaskManager instance.
        :param port_obj: The changed Port object.
        :param current_local_link: The current local_link_connection dict.
        :param current_switchport: The current switchport configuration.
        :param active_network_type: The network type that should be active.
        :param switchport_added: True if switchport was added, False if
            updated.
        :raises: InvalidParameterValue if unable to parse network configuration
        :raises: NetworkError if the networking service call fails
        """
        if switchport_added:
            LOG.info("Port %(port)s switchport configuration added",
                     {'port': port_obj.uuid})
        else:
            LOG.info("Port %(port)s switchport configuration updated",
                     {'port': port_obj.uuid})

        if not current_local_link:
            return

        # Validate the current switchport configuration
        self._validate_port_switchport_config(task, port_obj)

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        # Resolve configuration based on active network type
        mode, native_vlan, allowed_vlans = (
            self._resolve_network_configuration(
                task, port_obj, active_network_type))

        if mode and native_vlan is not None:
            # Get switch and port info from current state
            switch_id = current_local_link.get('switch_id')
            port_name = current_local_link.get('port_id')
            description = self._get_port_description(port_obj)
            lag_name = current_switchport.get('lag_name')

            if switch_id and port_name:
                result = networking_api.update_port(
                    task.context, switch_id, port_name,
                    description, mode, native_vlan,
                    allowed_vlans=allowed_vlans,
                    lag_name=lag_name,
                    default_vlan=idle_native_vlan)
                LOG.debug(
                    "Successfully updated port %(port_name)s "
                    "on switch %(switch_id)s for %(network_type)s "
                    "network via networking service: %(result)s",
                    {'port_name': port_name,
                     'switch_id': switch_id,
                     'network_type': active_network_type,
                     'result': result})
            else:
                LOG.warning(
                    "Cannot update port %(port)s: missing "
                    "switch_id or port_id",
                    {'port': port_obj.uuid})
        else:
            LOG.warning(
                "Cannot update port %(port)s: missing mode or "
                "native_vlan for %(network_type)s network",
                {'port': port_obj.uuid,
                 'network_type': active_network_type})

    def port_changed(self, task, port_obj):
        """Handle any actions required when a port changes.

        In the ironic networking interface, this method processes
        ports that have switchport configuration in their 'extra' field
        and calls the networking service API accordingly based on the
        node's current provision state and what network should be active.

        :param task: A TaskManager instance.
        :param port_obj: A changed Port object.
        """
        # Check if relevant fields have changed
        changed_fields = port_obj.obj_what_changed()
        if not ({'extra', 'local_link_connection'} & changed_fields):
            # No relevant changes, skip this port
            return

        # Determine what network should be active based on node state
        active_network_type = network.get_network_type_for_state(
            task.node.provision_state)

        LOG.debug(
            "Port %(port)s changed on node %(node)s in state %(state)s, "
            "active network type: %(network_type)s, changed fields: "
            "%(fields)s",
            {'port': port_obj.uuid, 'node': task.node.uuid,
             'state': task.node.provision_state,
             'network_type': active_network_type,
             'fields': list(changed_fields)})

        # Get current configuration
        current_switchport = (port_obj.extra.get('switchport')
                              if port_obj.extra else None)
        current_local_link = port_obj.local_link_connection

        # Get original port configuration (before changes)
        (original_port, original_switchport,
         original_local_link) = self._get_original_port_config(task, port_obj)

        # Determine what actions need to be taken
        (switchport_removed, local_link_removed, local_link_changed,
         switchport_changed, switchport_added) = self._determine_port_changes(
            original_switchport, current_switchport,
            original_local_link, current_local_link)

        # Handle removal cases
        if switchport_removed or local_link_removed:
            self._handle_port_removal(task, port_obj, original_port,
                                      original_local_link, original_switchport,
                                      active_network_type)
            return

        # Handle local_link_connection change (requires reset + update)
        if local_link_changed:
            self._handle_local_link_change(task, port_obj, original_port,
                                           original_local_link,
                                           original_switchport,
                                           active_network_type)
            # Then configure the new port (fall through to update logic)
            switchport_changed = True  # Force update with new configuration

        # Handle switchport addition or modification
        if switchport_added or switchport_changed:
            self._handle_switchport_update(task, port_obj, current_local_link,
                                           current_switchport,
                                           active_network_type,
                                           switchport_added)

    def portgroup_changed(self, task, portgroup_obj):
        """Handle any actions required when a portgroup changes.

        In the ironic networking interface, portgroup changes are not
        currently supported and will be logged but no action will be taken.

        :param task: A TaskManager instance.
        :param portgroup_obj: A changed Portgroup object.
        """
        LOG.debug(
            "Portgroup %(portgroup)s (%(name)s) configuration changed - "
            "portgroup changes not currently supported by "
            "ironic-networking interface",
            {'portgroup': portgroup_obj.uuid,
             'name': portgroup_obj.name or 'unnamed'})

    def vif_attach(self, task, vif_info):
        """Attach a virtual network interface to a node.

        In the ironic networking interface, VIF attachment is a no-op.
        This allows the operation to complete successfully without performing
        any actual network configuration.

        :param task: A TaskManager instance.
        :param vif_info: A dictionary of information about a VIF.
            It must have an 'id' key, whose value is a unique
            identifier for that VIF.
        """
        pass

    def vif_detach(self, task, vif_id):
        """Detach a virtual network interface from a node.

        In the ironic networking interface, VIF detachment is a no-op.
        This allows the operation to complete successfully without performing
        any actual network configuration.

        :param task: A TaskManager instance.
        :param vif_id: A VIF ID to detach.
        """
        pass

    def vif_list(self, task):
        """List attached VIF IDs for a node.

        In the ironic networking interface, no VIFs are ever attached,
        so this always returns an empty list.

        :param task: A TaskManager instance.
        :returns: Empty list as no VIFs are managed by this interface.
        """
        return []

    def get_current_vif(self, task, p_obj):
        """Return the currently used VIF associated with port or portgroup.

        In the ironic networking interface, no VIFs are managed,
        so this always returns None.

        :param task: A TaskManager instance.
        :param p_obj: Ironic port or portgroup object.
        :returns: None as no VIFs are managed by this interface.
        """
        return None

    def _add_tenant_networks(self, task):
        """Add tenant networks to a node.

        This method attempts to configure the tenant network for each port
        on the node using only the port's switchport configuration. If the
        switchport configuration is missing or incomplete, the port is skipped.

        :param task: A TaskManager instance.
        """
        LOG.debug("Adding tenant networks to node %(node)s",
                  {'node': task.node.uuid})

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        for port in task.ports:
            switchport = port.extra.get('switchport') if port.extra else None
            link_info = port.local_link_connection

            if not switchport or not link_info:
                LOG.debug(
                    "Skipping port %(port)s: missing switchport or "
                    "local_link_connection info for tenant network setup.",
                    {'port': port.uuid}
                )
                continue

            mode = switchport.get('mode')
            native_vlan = switchport.get('native_vlan')
            allowed_vlans = switchport.get('allowed_vlans')

            if not mode or native_vlan is None:
                LOG.debug(
                    "Skipping port %(port)s: missing mode or native_vlan for "
                    "tenant network setup.",
                    {'port': port.uuid}
                )
                continue

            try:
                networking_api.update_port(
                    task.context,
                    link_info.get('switch_id'),
                    link_info.get('port_id'),
                    self._get_port_description(port),
                    mode,
                    native_vlan,
                    allowed_vlans=allowed_vlans,
                    lag_name=None,
                    default_vlan=idle_native_vlan,
                )
            except (exception.InvalidParameterValue,
                    exception.NetworkError) as exc:
                LOG.error(
                    "Failed to update port %(port)s for tenant network: "
                    "%(err)s",
                    {'port': port.uuid, 'err': exc}
                )
                raise exception.NetworkError(
                    _("Failed to configure tenant network for port "
                      "%(port)s: %(err)s")
                    % {'port': port.uuid, 'err': exc}
                )

    def _remove_tenant_networks(self, task):
        """Remove tenant networks from a node.

        This method attempts to reset the tenant network configuration for
        each port on the node. It uses the tenant network configuration if
        set, otherwise falls
        back to the port's switchport configuration. If neither is available,
        the port is skipped with a log message.

        :param task: A TaskManager instance.
        """
        LOG.debug("Removing tenant networks from node %(node)s",
                  {'node': task.node.uuid})

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        errors = []
        for port in task.ports:
            switchport = port.extra.get('switchport') if port.extra else None
            link_info = port.local_link_connection

            if not switchport or not link_info:
                LOG.debug(
                    "Skipping port %(port)s: missing switchport or "
                    "local_link_connection info for tenant network removal.",
                    {'port': port.uuid}
                )
                continue

            mode = switchport.get('mode')
            native_vlan = switchport.get('native_vlan')
            allowed_vlans = switchport.get('allowed_vlans')

            if not mode or native_vlan is None:
                LOG.debug(
                    "Skipping port %(port)s: missing mode or native_vlan for "
                    "tenant network removal.",
                    {'port': port.uuid}
                )
                continue

            try:
                networking_api.reset_port(
                    task.context,
                    link_info.get('switch_id'),
                    link_info.get('port_id'),
                    native_vlan,
                    allowed_vlans=allowed_vlans,
                    default_vlan=idle_native_vlan
                )
            except (exception.InvalidParameterValue,
                    exception.NetworkError) as exc:
                # Accumulate errors to ensure that we attempt to reset each
                # port regardless of if any single port had an error.
                message = (f"Failed to reset tenant network for "
                           f"port {port.uuid}: {exc}")
                LOG.error(message)
                errors.append(message)

        if len(errors) > 0:
            raise exception.NetworkError(
                _("Failed to reset ports for tenant network, "
                  "errors: %(errors)s") %
                {"errors": errors})

    def _add_network(self, task, network_type):
        """Add a network to a node.

        This method attempts to configure the specified network for each port
        on the node. It uses the network configuration if set, otherwise falls
        back to the port's switchport configuration. If neither is available,
        the port is skipped with a log message.

        :param task: A TaskManager instance.
        :param network_type: The type of network to add (e.g.,
                             'provisioning', 'cleaning', 'rescuing',
                             'inspection', 'servicing').
        """
        LOG.info("Adding %(network_type)s network to node %(node)s",
                 {'network_type': network_type, 'node': task.node.uuid})

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        # Get the mode and native_vlan for the network type. It may be
        # overridden by the port's switchport configuration.
        global_mode, global_native_vlan, global_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network_type))

        for port in task.ports:
            # If the local_link_connection info is missing, skip the port
            link_info = port.local_link_connection
            if not link_info:
                LOG.debug(
                    "Skipping port %(port)s: missing local_link_connection "
                    "info for %(network_type)s network setup.",
                    {'port': port.uuid, 'network_type': network_type}
                )
                continue

            # If the global mode and native_vlan are not set, try to get
            # switchport info from port.extra
            mode = None
            native_vlan = None
            allowed_vlans = None
            if global_mode is None or global_native_vlan is None:
                # Try to get switchport info from port.extra
                switchport = (port.extra.get('switchport')
                              if port.extra else None)
                if switchport:
                    mode = switchport.get('mode')
                    native_vlan = switchport.get('native_vlan')
                    allowed_vlans = switchport.get('allowed_vlans')
            else:
                mode = global_mode
                native_vlan = global_native_vlan
                allowed_vlans = global_allowed_vlans

            if not mode or native_vlan is None:
                LOG.debug(
                    "Skipping port %(port)s: missing mode or native_vlan for "
                    "%(network_type)s network setup.",
                    {'port': port.uuid, 'network_type': network_type}
                )
                continue

            try:
                networking_api.update_port(
                    task.context,
                    link_info.get('switch_id'),
                    link_info.get('port_id'),
                    self._get_port_description(port),
                    mode,
                    native_vlan,
                    allowed_vlans=allowed_vlans,
                    lag_name=None,
                    default_vlan=idle_native_vlan
                )
                LOG.debug(
                    "Configured %(network_type)s network for port %(port)s: "
                    "switch_id=%(switch_id)s, port_name=%(port_name)s, "
                    "mode=%(mode)s, native_vlan=%(native_vlan)s, "
                    "allowed_vlans=%(allowed_vlans)s",
                    {
                        'network_type': network_type,
                        'port': port.uuid,
                        'switch_id': link_info.get('switch_id'),
                        'port_name': link_info.get('port_id'),
                        'mode': mode,
                        'native_vlan': native_vlan,
                        'allowed_vlans': allowed_vlans,
                        'default_vlan': idle_native_vlan
                    }
                )
            except (exception.InvalidParameterValue,
                    exception.NetworkError) as exc:
                LOG.error(
                    "Failed to configure %(network_type)s network for port "
                    "%(port)s: %(err)s",
                    {'network_type': network_type, 'port': port.uuid,
                     'err': exc}
                )
                raise exception.NetworkError(
                    _("Failed to configure %(network_type)s network for port "
                      "%(port)s: %(err)s")
                    % {'network_type': network_type, 'port': port.uuid,
                       'err': exc}
                )

    def _remove_network(self, task, network_type):
        """Remove a network from a node.

        This method attempts to reset the specified network configuration for
        each port
        on the node. It uses the network configuration if set, otherwise falls
        back to the port's switchport configuration. If neither is available,
        the port is skipped with a log message.

        :param task: A TaskManager instance.
        :param network_type: The type of network to remove (e.g.,
                             'provisioning', 'cleaning', 'rescuing',
                             'inspection', 'servicing').
        """
        LOG.info("Removing %(network_type)s network from node %(node)s",
                 {'network_type': network_type, 'node': task.node.uuid})

        # Resolve the idle network configuration (if any)
        idle_mode, idle_native_vlan, idle_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network.IDLE_NETWORK))

        # Get the mode and native_vlan for the network type. It may be
        # overridden by the port's switchport configuration.
        global_mode, global_native_vlan, global_allowed_vlans = (
            self._get_network_mode_and_vlan(task, network_type))

        errors = []
        for port in task.ports:
            # Get the switch and port info from the port's
            # local_link_connection
            link_info = port.local_link_connection
            if not link_info:
                LOG.debug(
                    "Skipping port %(port)s: missing local_link_connection "
                    "info for %(network_type)s network removal.",
                    {'port': port.uuid, 'network_type': network_type}
                )
                continue

            # If the global mode and native_vlan are not set, try to get
            # switchport info from port.extra
            mode = None
            native_vlan = None
            allowed_vlans = None
            if global_mode is None or global_native_vlan is None:
                # Try to get switchport info from port.extra
                switchport = (port.extra.get('switchport')
                              if port.extra else None)
                if switchport:
                    mode = switchport.get('mode')
                    native_vlan = switchport.get('native_vlan')
                    allowed_vlans = switchport.get('allowed_vlans')
            else:
                mode = global_mode
                native_vlan = global_native_vlan
                allowed_vlans = global_allowed_vlans

            if not mode or native_vlan is None:
                LOG.debug(
                    "Skipping port %(port)s: missing mode or native_vlan for "
                    "%(network_type)s network removal.",
                    {'port': port.uuid, 'network_type': network_type}
                )
                continue

            try:
                networking_api.reset_port(
                    task.context,
                    link_info.get('switch_id'),
                    link_info.get('port_id'),
                    native_vlan,
                    allowed_vlans=allowed_vlans,
                    default_vlan=idle_native_vlan
                )
                LOG.debug(
                    "Reset %(network_type)s network for port %(port)s: "
                    "switch_id=%(switch_id)s, port_name=%(port_name)s, "
                    "native_vlan=%(native_vlan)s, "
                    "allowed_vlans=%(allowed_vlans)s",
                    {
                        'network_type': network_type,
                        'port': port.uuid,
                        'switch_id': link_info.get('switch_id'),
                        'port_name': link_info.get('port_id'),
                        'native_vlan': native_vlan,
                        'allowed_vlans': allowed_vlans,
                        'default_vlan': idle_native_vlan
                    }
                )
            except (exception.InvalidParameterValue,
                    exception.NetworkError) as exc:
                # Accumulate errors to ensure that we attempt to reset each
                # port regardless of if any single port had an error.
                message = (f"Failed to reset {network_type} network for "
                           f"port {port.uuid}: {exc}")
                LOG.error(message)
                errors.append(message)

        if len(errors) > 0:
            raise exception.NetworkError(
                _("Failed to reset %(network_type)s network, "
                  "errors: %(errors)s") %
                {"network_type": network_type, "errors": errors})

    def add_provisioning_network(self, task):
        """Add the provisioning network to a node.

        This method configures the provisioning network for each port on the
        node by applying the port's switchport configuration with the
        provisioning network VLAN/segment ID override if set.

        :param task: A TaskManager instance.
        """
        self._add_network(task, network.PROVISIONING_NETWORK)

    def remove_provisioning_network(self, task):
        """Remove the provisioning network from a node.

        This method resets the provisioning network configuration for each
        port on the node by restoring the port's default switchport
        configuration.

        :param task: A TaskManager instance.
        """
        self._remove_network(task, network.PROVISIONING_NETWORK)

    def configure_tenant_networks(self, task):
        """Configure tenant networks for a node.

        This method configures tenant network connectivity for each port on
        the node by applying the port's switchport configuration with any
        tenant network overrides.

        :param task: A TaskManager instance.
        """
        self._add_tenant_networks(task)

    def unconfigure_tenant_networks(self, task):
        """Unconfigure tenant networks for a node.

        This method removes tenant network configuration for each port on the
        node by restoring the port's default switchport configuration.

        :param task: A TaskManager instance.
        """
        self._remove_tenant_networks(task)

    def add_cleaning_network(self, task):
        """Add the cleaning network to a node.

        This method configures the cleaning network for each port on the node
        by applying the port's switchport configuration with the cleaning
        network VLAN/segment ID override if set.

        :param task: A TaskManager instance.
        :returns: Empty dictionary as no ports are configured.
        """
        self._add_network(task, network.CLEANING_NETWORK)

    def remove_cleaning_network(self, task):
        """Remove the cleaning network from a node.

        This method resets the cleaning network configuration for each port on
        the node by restoring the port's default switchport configuration.

        :param task: A TaskManager instance.
        """
        self._remove_network(task, network.CLEANING_NETWORK)

    def validate_rescue(self, task):
        """Validate the network interface for rescue operation.

        This method validates that at least one port has the required network
        configuration for rescue operations.

        :param task: A TaskManager instance.
        :raises: InvalidParameterValue if unable to parse network configuration
        """
        self._validate_network_requirements(task, network.RESCUING_NETWORK)

    def add_rescuing_network(self, task):
        """Add the rescuing network to the node.

        This method configures the rescuing network for each port on the node
        by applying the port's switchport configuration with the rescuing
        network VLAN/segment ID override if set.

        :param task: A TaskManager instance.
        :returns: Empty dictionary as no ports are configured.
        """
        self._add_network(task, network.RESCUING_NETWORK)

    def remove_rescuing_network(self, task):
        """Remove the rescuing network from a node.

        This method resets the rescuing network configuration for each port on
        the node by restoring the port's default switchport configuration.

        :param task: A TaskManager instance.
        """
        self._remove_network(task, network.RESCUING_NETWORK)

    def validate_inspection(self, task):
        """Validate that the node has required properties for inspection.

        This method validates that at least one port has the required network
        configuration for inspection operations.

        :param task: A TaskManager instance with the node being checked.
        :raises: InvalidParameterValue if unable to parse network configuration
        """
        self._validate_network_requirements(task, network.INSPECTION_NETWORK)

    def add_inspection_network(self, task):
        """Add the inspection network to the node.

        This method configures the inspection network for each port on the
        node by applying the port's switchport configuration with the
        inspection network VLAN/segment ID override if set.

        :param task: A TaskManager instance.
        :returns: Empty dictionary as no ports are configured.
        """
        self._add_network(task, network.INSPECTION_NETWORK)

    def remove_inspection_network(self, task):
        """Remove the inspection network from a node.

        This method resets the inspection network configuration for each port
        on the node by restoring the port's default switchport configuration.

        :param task: A TaskManager instance.
        """
        self._remove_network(task, network.INSPECTION_NETWORK)

    def need_power_on(self, task):
        """Check if node must be powered on before applying network changes.

        Switch operations can be performed without powering on the node.

        :param task: A TaskManager instance.
        :returns: False as no power state changes are needed.
        """
        return False

    def get_node_network_data(self, task):
        """Return network configuration for node NICs.

        This method returns network configuration data for the node. It first
        checks if static network data is configured on the node itself. If
        present, that takes precedence. Otherwise, it builds network data from
        the ports and portgroups attached to the node.

        The network data is returned in Nova network metadata layout
        (`network_data.json`) format.

        For the ironic-networking interface, this generates:
        - Physical links (type: "phy") for each port with a MAC address
        - VLAN interfaces (type: "vlan") for ports with allowed_vlans
          configured in their switchport settings

        :param task: A TaskManager instance.
        :returns: a dict holding network configuration information adhering
            to Nova network metadata layout (`network_data.json`).
        """
        # Static network data takes precedence
        if task.node.network_data:
            return task.node.network_data

        LOG.debug('Building network data from ports for node %(node)s',
                  {'node': task.node.uuid})

        links = []

        # Process each port to build physical and VLAN links
        for port in task.ports:
            # Skip ports without MAC addresses
            if not port.address:
                LOG.debug('Skipping port %(port)s: no MAC address',
                          {'port': port.uuid})
                continue

            # Create physical link for this port
            phy_link = {
                'id': port.uuid,
                'type': 'phy',
                'ethernet_mac_address': port.address,
                'mtu': 1500
            }
            links.append(phy_link)

            # Check for VLAN configuration in switchport settings
            switchport = port.extra.get('switchport', {}) if port.extra else {}
            allowed_vlans = switchport.get('allowed_vlans', [])

            # Generate VLAN interfaces for each allowed VLAN
            for vlan_id in allowed_vlans:
                vlan_link = {
                    'id': f'{port.uuid}_vlan_{vlan_id}',
                    'type': 'vlan',
                    'vlan_mac_address': port.address,
                    'vlan_id': vlan_id,
                    'vlan_link': port.uuid,
                    'mtu': 1500
                }
                links.append(vlan_link)

        LOG.debug('Generated network data for node %(node)s: %(links)d links',
                  {'node': task.node.uuid, 'links': len(links)})

        # TODO(alegacy): enhance this for LAG support
        return {'links': links}

    def add_servicing_network(self, task):
        """Add the servicing network to the node.

        This method configures the servicing network for each port on the node
        by applying the port's switchport configuration with the servicing
        network VLAN/segment ID override if set.

        :param task: A TaskManager instance.
        :returns: Empty dictionary as no ports are configured.
        """
        self._add_network(task, network.SERVICING_NETWORK)

    def remove_servicing_network(self, task):
        """Remove the servicing network from a node.

        This method resets the servicing network configuration for each port
        on the node by restoring the port's default switchport configuration.

        :param task: A TaskManager instance.
        """
        self._remove_network(task, network.SERVICING_NETWORK)
