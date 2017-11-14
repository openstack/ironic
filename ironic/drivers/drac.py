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

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import generic
from ironic.drivers.modules.drac import inspect as drac_inspect
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import power
from ironic.drivers.modules.drac import raid
from ironic.drivers.modules.drac import vendor_passthru
from ironic.drivers.modules import inspector
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop
from ironic.drivers.modules import pxe


class IDRACHardware(generic.GenericHardware):
    """integrated Dell Remote Access Controller hardware type"""

    # Required hardware interfaces

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.DracManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.DracPower]

    # Optional hardware interfaces

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        # Inspector support should have a higher priority than NoInspect
        # if it is enabled by an operator (implying that the service is
        # installed).
        return [drac_inspect.DracInspect, inspector.Inspector, noop.NoInspect]

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [raid.DracRAID, noop.NoRAID]

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return [vendor_passthru.DracVendorPassthru, noop.NoVendor]


class PXEDracDriver(base.BaseDriver):
    """DRAC driver using PXE for deploy."""

    def __init__(self):
        if not importutils.try_import('dracclient'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_('Unable to import python-dracclient library'))

        self.power = power.DracPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = management.DracManagement()
        self.raid = raid.DracRAID()
        self.vendor = vendor_passthru.DracVendorPassthru()
        self.inspect = drac_inspect.DracInspect()


class PXEDracInspectorDriver(PXEDracDriver):
    """Drac driver using PXE for deploy and OOB inspection interface."""

    def __init__(self):
        super(PXEDracInspectorDriver, self).__init__()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEDracInspectorDriver')
