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

"""
DRAC Driver for remote system management using Dell Remote Access Card.
"""

from oslo_config import cfg

from ironic.drivers.modules.drac import bios
from ironic.drivers.modules.drac import boot
from ironic.drivers.modules.drac import inspect as drac_inspect
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import power
from ironic.drivers.modules.drac import raid
from ironic.drivers.modules.drac import vendor_passthru
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import inspect as redfish_inspect
from ironic.drivers.modules.redfish import raid as redfish_raid
from ironic.drivers import redfish


CONF = cfg.CONF


class IDRACHardware(redfish.RedfishHardware):
    """integrated Dell Remote Access Controller hardware type"""

    # Required hardware interfaces

    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        inherited = super().supported_boot_interfaces
        # remove the generic redfish one in favor of the Dell specific
        idx = inherited.index(redfish_boot.RedfishVirtualMediaBoot)
        inherited[idx] = boot.DracRedfishVirtualMediaBoot
        return inherited

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.DracRedfishManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return ([power.DracRedfishPower]
                + super().supported_power_interfaces)

    # Optional hardware interfaces

    @property
    def supported_bios_interfaces(self):
        """List of supported bios interfaces."""
        return ([bios.DracRedfishBIOS]
                + super().supported_bios_interfaces)

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        # Inspector support should have a higher priority than NoInspect
        # if it is enabled by an operator (implying that the service is
        # installed).
        inherited = super().supported_inspect_interfaces
        # remove the generic redfish one in favor of the Dell specific
        idx = inherited.index(redfish_inspect.RedfishInspect)
        inherited[idx] = drac_inspect.DracRedfishInspect
        return inherited

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        inherited = super().supported_raid_interfaces
        # remove the generic redfish one in favor of the Dell specific
        idx = inherited.index(redfish_raid.RedfishRAID)
        inherited[idx] = raid.DracRedfishRAID
        return inherited

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return ([vendor_passthru.DracRedfishVendorPassthru]
                + super().supported_vendor_interfaces)
