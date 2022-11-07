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

from ironic.drivers import generic
from ironic.drivers.modules.drac import bios
from ironic.drivers.modules.drac import boot
from ironic.drivers.modules.drac import console
from ironic.drivers.modules.drac import inspect as drac_inspect
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import power
from ironic.drivers.modules.drac import raid
from ironic.drivers.modules.drac import vendor_passthru
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import noop
from ironic.drivers.modules import pxe


CONF = cfg.CONF


class IDRACHardware(generic.GenericHardware):
    """integrated Dell Remote Access Controller hardware type"""

    # Required hardware interfaces

    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        return [ipxe.iPXEBoot, pxe.PXEBoot, boot.DracRedfishVirtualMediaBoot]

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [ipmitool.IPMISocatConsole, ipmitool.IPMIShellinaboxConsole,
                noop.NoConsole, console.DracRedFishVNCConsole,
                console.DracRedFishKVMConsole]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.DracWSManManagement, management.DracManagement,
                management.DracRedfishManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.DracWSManPower, power.DracPower, power.DracRedfishPower]

    # Optional hardware interfaces

    @property
    def supported_bios_interfaces(self):
        """List of supported bios interfaces."""
        return [bios.DracWSManBIOS, bios.DracRedfishBIOS, noop.NoBIOS]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        # Inspector support should have a higher priority than NoInspect
        # if it is enabled by an operator (implying that the service is
        # installed).
        return [drac_inspect.DracWSManInspect, drac_inspect.DracInspect,
                drac_inspect.DracRedfishInspect] + super(
                    IDRACHardware, self).supported_inspect_interfaces

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [raid.DracWSManRAID, raid.DracRAID,
                raid.DracRedfishRAID] + super(
                    IDRACHardware, self).supported_raid_interfaces

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return [vendor_passthru.DracWSManVendorPassthru,
                vendor_passthru.DracVendorPassthru,
                vendor_passthru.DracRedfishVendorPassthru, noop.NoVendor]
