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

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import generic
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import boot
from ironic.drivers.modules.ilo import console
from ironic.drivers.modules.ilo import inspect
from ironic.drivers.modules.ilo import management
from ironic.drivers.modules.ilo import power
from ironic.drivers.modules.ilo import vendor
from ironic.drivers.modules import inspector
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import noop


class IloHardware(generic.GenericHardware):
    """iLO hardware type.

    iLO hardware type is targeted for iLO 4 based Proliant Gen8
    and Gen9 servers.
    """

    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        return [boot.IloVirtualMediaBoot, boot.IloPXEBoot]

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [console.IloConsoleInterface, noop.NoConsole]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [inspect.IloInspect, inspector.Inspector,
                noop.NoInspect]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.IloManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.IloPower]


class IloVirtualMediaIscsiDriver(base.BaseDriver):
    """IloDriver using IloClient interface.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.ilo.power.IloPower for power management.
    and
    :class:ironic.drivers.modules.ilo.deploy.IloVirtualMediaIscsiDeploy for
    deploy.
    """

    def __init__(self):
        if not importutils.try_import('proliantutils'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import proliantutils library"))

        self.power = power.IloPower()
        self.boot = boot.IloVirtualMediaBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.console = console.IloConsoleInterface()
        self.management = management.IloManagement()
        self.vendor = vendor.VendorPassthru()
        self.inspect = inspect.IloInspect()
        self.raid = agent.AgentRAID()


class IloVirtualMediaAgentDriver(base.BaseDriver):
    """IloDriver using IloClient interface.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.ilo.power.IloPower for power management
    and
    :class:ironic.drivers.modules.ilo.deploy.IloVirtualMediaAgentDriver for
    deploy.
    """

    def __init__(self):
        if not importutils.try_import('proliantutils'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import proliantutils library"))

        self.power = power.IloPower()
        self.boot = boot.IloVirtualMediaBoot()
        self.deploy = agent.AgentDeploy()
        self.console = console.IloConsoleInterface()
        self.management = management.IloManagement()
        self.inspect = inspect.IloInspect()
        self.raid = agent.AgentRAID()
