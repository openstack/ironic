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
iBMC Driver for managing HUAWEI V5 series rack servers such as 2288H V5,
CH121 V5.
"""

from ironic.drivers import generic
from ironic.drivers.modules.ibmc import management as ibmc_mgmt
from ironic.drivers.modules.ibmc import power as ibmc_power
from ironic.drivers.modules.ibmc import raid as ibmc_raid
from ironic.drivers.modules.ibmc import vendor as ibmc_vendor
from ironic.drivers.modules import inspector
from ironic.drivers.modules import noop


class IBMCHardware(generic.GenericHardware):
    """Huawei iBMC hardware type."""

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [ibmc_mgmt.IBMCManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [ibmc_power.IBMCPower]

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return [ibmc_vendor.IBMCVendor, noop.NoVendor]

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [ibmc_raid.IbmcRAID, noop.NoRAID]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [inspector.Inspector, noop.NoInspect]
