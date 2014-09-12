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


def _raise_unsupported_error(method=None):
    if method:
        raise exception.UnsupportedDriverExtension(_(
            "Unsupported method (%s) passed through to vendor extension.")
            % method)
    raise exception.MissingParameterValue(_(
        "Method not specified when calling vendor extension."))


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

    def _map(self, **kwargs):
        method = kwargs.get('method')
        return self.mapping.get(method) or _raise_unsupported_error(method)

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

    def validate(self, *args, **kwargs):
        """Call validate on the appropriate interface only.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if **kwargs does not contain 'method'.
        :raisee: MissingParameterValue if missing parameters in kwargs.

        """
        route = self._map(**kwargs)
        route.validate(*args, **kwargs)

    def vendor_passthru(self, task, **kwargs):
        """Call vendor_passthru on the appropriate interface only.

        Returns or raises according to the requested vendor_passthru method.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: MissingParameterValue if **kwargs does not contain 'method'.

        """
        route = self._map(**kwargs)
        return route.vendor_passthru(task, **kwargs)

    def driver_vendor_passthru(self, context, method, **kwargs):
        """Call driver_vendor_passthru on a mapped interface based on the
        specified method.

        Returns or raises according to the requested driver_vendor_passthru

        :raises: UnsupportedDriverExtension if 'method' cannot be mapped to
                 a supported interface.
        """
        iface = self.driver_level_mapping.get(method)
        if iface is None:
            _raise_unsupported_error(method)

        return iface.driver_vendor_passthru(context, method, **kwargs)


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
    capabilities = node.properties.get('capabilities')

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
    node.properties['capabilities'] = new_cap_str if new_cap_str else None
    node.save(task.context)


def add_node_capability(task, capability, value):
    """Add 'capability' to node's 'capabilities' property.

    If 'capability' is already present, then a duplicate entry
    will be added.

    :param task: Task object.
    :param capability: Capability key.
    :param value: Capability value.

    """
    node = task.node
    capabilities = node.properties.get('capabilities')

    new_cap = ':'.join([capability, value])

    if capabilities:
        capabilities = ','.join([capabilities, new_cap])
    else:
        capabilities = new_cap

    node.properties['capabilities'] = capabilities
    node.save(task.context)


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
