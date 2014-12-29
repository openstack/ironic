# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
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

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LW
from ironic.drivers import base
from ironic.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class MixinVendorInterface(base.VendorInterface):
    """Wrapper around multiple VendorInterfaces."""

    def __init__(self, mapping, driver_passthru_mapping=None):
        """Wrapper around multiple VendorInterfaces.

        :param mapping: dict of {'method': interface} specifying how to combine
                        multiple vendor interfaces into one vendor driver.
        :param driver_passthru_mapping: dict of {'method': interface}
                                        specifying how to map
                                        driver_vendor_passthru calls to
                                        interfaces.

        """
        self.mapping = mapping
        self.driver_level_mapping = driver_passthru_mapping or {}
        self.vendor_routes = self._build_routes(self.mapping)
        self.driver_routes = self._build_routes(self.driver_level_mapping,
                                                driver_passthru=True)

    def _build_routes(self, map_dict, driver_passthru=False):
        """Build the mapping for the vendor calls.

        Build the mapping between the given methods and the corresponding
        method metadata.

        :param map_dict: dict of {'method': interface} specifying how
                         to map multiple vendor calls to interfaces.
        :param driver_passthru: Boolean value. Whether build the mapping
                                to the node vendor passthru or driver
                                vendor passthru.
        """
        d = {}
        for method_name in map_dict:
            iface = map_dict[method_name]
            if driver_passthru:
                driver_methods = iface.driver_routes
            else:
                driver_methods = iface.vendor_routes

            try:
                d.update({method_name: driver_methods[method_name]})
            except KeyError:
                pass
        return d

    def _get_route(self, method):
        """Return the driver interface which contains the given method.

        :param method: The name of the vendor method.
        """
        if not method:
            raise exception.MissingParameterValue(
                _("Method not specified when calling vendor extension."))

        try:
            route = self.mapping[method]
        except KeyError:
            raise exception.InvalidParameterValue(
                _('No handler for method %s') % method)

        return route

    def get_properties(self):
        """Return the properties from all the VendorInterfaces.

        :returns: a dictionary of <property_name>:<property_description>
                  entries.
        """
        properties = {}
        interfaces = set(self.mapping.values())
        for interface in interfaces:
            properties.update(interface.get_properties())
        return properties

    def validate(self, task, method, **kwargs):
        """Call validate on the appropriate interface only.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if 'method' is invalid.
        :raisee: MissingParameterValue if missing 'method' or parameters
                 in kwargs.

        """
        route = self._get_route(method)
        route.validate(task, method=method, **kwargs)


def get_node_mac_addresses(task):
    """Get all MAC addresses for the ports belonging to this task's node.

    :param task: a TaskManager instance containing the node to act on.
    :returns: A list of MAC addresses in the format xx:xx:xx:xx:xx:xx.
    """
    return [p.address for p in task.ports]


def get_node_capability(node, capability):
    """Returns 'capability' value from node's 'capabilities' property.

    :param node: Node object.
    :param capability: Capability key.
    :return: Capability value.
             If capability is not present, then return "None"

    """
    capabilities = node.properties.get('capabilities')

    if not capabilities:
        return

    for node_capability in capabilities.split(','):
        parts = node_capability.split(':')
        if len(parts) == 2 and parts[0] and parts[1]:
            if parts[0] == capability:
                return parts[1]
        else:
            LOG.warn(_LW("Ignoring malformed capability '%s'. "
                "Format should be 'key:val'."), node_capability)


def rm_node_capability(task, capability):
    """Remove 'capability' from node's 'capabilities' property.

    :param task: Task object.
    :param capability: Capability key.

    """
    node = task.node
    properties = node.properties
    capabilities = properties.get('capabilities')

    if not capabilities:
        return

    caps = []
    for cap in capabilities.split(','):
        parts = cap.split(':')
        if len(parts) == 2 and parts[0] and parts[1]:
            if parts[0] == capability:
                continue
        caps.append(cap)
    new_cap_str = ",".join(caps)
    properties['capabilities'] = new_cap_str if new_cap_str else None
    node.properties = properties
    node.save()


def add_node_capability(task, capability, value):
    """Add 'capability' to node's 'capabilities' property.

    If 'capability' is already present, then a duplicate entry
    will be added.

    :param task: Task object.
    :param capability: Capability key.
    :param value: Capability value.

    """
    node = task.node
    properties = node.properties
    capabilities = properties.get('capabilities')

    new_cap = ':'.join([capability, value])

    if capabilities:
        capabilities = ','.join([capabilities, new_cap])
    else:
        capabilities = new_cap

    properties['capabilities'] = capabilities
    node.properties = properties
    node.save()


def validate_boot_mode_capability(node):
    """Validate the boot_mode capability set in node property.

    :param node: an ironic node object.
    :raises: InvalidParameterValue, if 'boot_mode' capability is set
             other than 'bios' or 'uefi' or None.

    """
    boot_mode = get_node_capability(node, 'boot_mode')

    if boot_mode and boot_mode not in ['bios', 'uefi']:
        raise exception.InvalidParameterValue(_("Invalid boot_mode "
                          "parameter '%s'.") % boot_mode)
