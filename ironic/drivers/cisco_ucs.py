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
Hardware types for Cisco UCS Servers
"""

from ironic.drivers import ipmi

from ironic.drivers.modules.cimc import management as cimc_mgmt
from ironic.drivers.modules.cimc import power as cimc_power

from ironic.drivers.modules.ucs import management as ucs_mgmt
from ironic.drivers.modules.ucs import power as ucs_power


class CiscoUCSStandalone(ipmi.IPMIHardware):
    """Cisco UCS in standalone mode"""

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        mgmt = super(CiscoUCSStandalone, self).supported_management_interfaces
        return [cimc_mgmt.CIMCManagement] + mgmt

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        power = super(CiscoUCSStandalone, self).supported_power_interfaces
        return [cimc_power.Power] + power


class CiscoUCSManaged(CiscoUCSStandalone):
    """Cisco UCS under UCSM management"""

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        mgmt = super(CiscoUCSManaged, self).supported_management_interfaces
        return [ucs_mgmt.UcsManagement] + mgmt

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        power = super(CiscoUCSManaged, self).supported_power_interfaces
        return [ucs_power.Power] + power
