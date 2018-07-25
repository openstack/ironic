#    Copyright 2017 Lenovo, Inc.
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

"""
XClarity Driver and supporting meta-classes.
"""

from ironic.drivers import generic
from ironic.drivers.modules.xclarity import management
from ironic.drivers.modules.xclarity import power


class XClarityHardware(generic.GenericHardware):
    """XClarity hardware type. """

    # NOTE(TheJulia): Marking as unsupported as 3rd Party CI for this
    # hardware type was not established before Rocky cycle feature freeze.
    # Lenovo is continuing to work on establishing their Third Party CI,
    # and upon establishment and verification of Thid Party CI, this
    # unsupported flag shall be removed.
    # TODO(TheJulia): If Third Party CI is not online prior to the
    # Stein Feature Freeze, this hardware type should be removed.
    supported = False

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.XClarityManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.XClarityPower]
