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
"""
iLO Driver for managing HP Proliant Gen8 and above servers.
"""

from ironic.drivers import generic
from ironic.drivers.modules.ilo import bios
from ironic.drivers.modules.ilo import boot
from ironic.drivers.modules.ilo import console
from ironic.drivers.modules.ilo import inspect
from ironic.drivers.modules.ilo import management
from ironic.drivers.modules.ilo import power
from ironic.drivers.modules.ilo import raid
from ironic.drivers.modules.ilo import vendor
from ironic.drivers.modules import noop


class IloHardware(generic.GenericHardware):
    """iLO hardware type.

    iLO hardware type is targeted for iLO 4 based Proliant Gen8
    and Gen9 servers.
    """

    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        return [boot.IloVirtualMediaBoot, boot.IloPXEBoot, boot.IloiPXEBoot]

    @property
    def supported_bios_interfaces(self):
        """List of supported bios interfaces."""
        return [bios.IloBIOS, noop.NoBIOS]

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [console.IloConsoleInterface, noop.NoConsole]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [inspect.IloInspect] + super(
            IloHardware, self).supported_inspect_interfaces

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.IloManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.IloPower]

    @property
    def supported_vendor_interfaces(self):
        """List of supported power interfaces."""
        return [vendor.VendorPassthru, noop.NoVendor]


class Ilo5Hardware(IloHardware):
    """iLO5 hardware type.

    iLO5 hardware type is targeted for iLO5 based Proliant Gen10 servers.
    """

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [raid.Ilo5RAID] + super(
            Ilo5Hardware, self).supported_raid_interfaces

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.Ilo5Management]
