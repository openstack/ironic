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
Hardware type for IPMI (using ipmitool).
"""

from ironic.drivers import generic
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import noop
from ironic.drivers.modules import noop_mgmt


class IPMIHardware(generic.GenericHardware):
    """IPMI hardware type.

    Uses ``ipmitool`` to implement power and management.
    Provides serial console implementations via ``shellinabox`` or ``socat``.
    """

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [ipmitool.IPMISocatConsole, ipmitool.IPMIShellinaboxConsole,
                noop.NoConsole]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [ipmitool.IPMIManagement, noop_mgmt.NoopManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [ipmitool.IPMIPower]

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return [ipmitool.VendorPassthru, noop.NoVendor]
