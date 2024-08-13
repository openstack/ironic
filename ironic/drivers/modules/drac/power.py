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
DRAC power interface
"""


from ironic.drivers.modules.redfish import power as redfish_power


class DracRedfishPower(redfish_power.RedfishPower):
    """iDRAC Redfish interface for power-related actions.

    Presently, this class entirely defers to its base class, a generic,
    vendor-independent Redfish interface. Future resolution of Dell EMC-
    specific incompatibilities and introduction of vendor value added
    should be implemented by this class.
    """
    # NOTE(cardoe): deprecated in favor of plain Redfish
    supported = False
