# Copyright 2015 FUJITSU LIMITED
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
iRMC Driver for managing FUJITSU PRIMERGY BX S4 or RX S8 generation
of FUJITSU PRIMERGY servers, and above servers.
"""

from ironic.drivers import generic
from ironic.drivers.modules import agent
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import ipxe
from ironic.drivers.modules.irmc import bios
from ironic.drivers.modules.irmc import boot
from ironic.drivers.modules.irmc import inspect
from ironic.drivers.modules.irmc import management
from ironic.drivers.modules.irmc import power
from ironic.drivers.modules.irmc import raid
from ironic.drivers.modules import noop
from ironic.drivers.modules import pxe


class IRMCHardware(generic.GenericHardware):
    """iRMC hardware type.

    iRMC hardware type is targeted for FUJITSU PRIMERGY servers which
    have iRMC S4 management system.
    """

    supported = False

    @property
    def supported_bios_interfaces(self):
        """List of supported bios interfaces."""
        return [bios.IRMCBIOS, noop.NoBIOS]

    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        # NOTE: Support for pxe boot is deprecated, and will be
        # removed from the list in the future.
        return [boot.IRMCVirtualMediaBoot, boot.IRMCPXEBoot,
                ipxe.iPXEBoot, pxe.PXEBoot]

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [ipmitool.IPMISocatConsole, ipmitool.IPMIShellinaboxConsole,
                noop.NoConsole]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [inspect.IRMCInspect, inspector.Inspector,
                noop.NoInspect]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.IRMCManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.IRMCPower, ipmitool.IPMIPower]

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [noop.NoRAID, raid.IRMCRAID, agent.AgentRAID]
