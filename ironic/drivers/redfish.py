# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
#
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

from ironic.drivers import generic
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import noop
from ironic.drivers.modules import noop_mgmt
from ironic.drivers.modules import pxe
from ironic.drivers.modules.redfish import bios as redfish_bios
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import inspect as redfish_inspect
from ironic.drivers.modules.redfish import management as redfish_mgmt
from ironic.drivers.modules.redfish import power as redfish_power


class RedfishHardware(generic.GenericHardware):
    """Redfish hardware type."""

    @property
    def supported_bios_interfaces(self):
        """List of supported bios interfaces."""
        return [redfish_bios.RedfishBIOS, noop.NoBIOS]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [redfish_mgmt.RedfishManagement, noop_mgmt.NoopManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [redfish_power.RedfishPower]

    @property
    def supported_inspect_interfaces(self):
        """List of supported power interfaces."""
        return [redfish_inspect.RedfishInspect, inspector.Inspector,
                noop.NoInspect]

    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        # NOTE(dtantsur): virtual media goes last because of limited hardware
        # vendors support.
        return [ipxe.iPXEBoot, pxe.PXEBoot,
                redfish_boot.RedfishVirtualMediaBoot]
