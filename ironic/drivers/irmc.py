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

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import boot
from ironic.drivers.modules.irmc import inspect
from ironic.drivers.modules.irmc import management
from ironic.drivers.modules.irmc import power
from ironic.drivers.modules import iscsi_deploy


class IRMCVirtualMediaIscsiDriver(base.BaseDriver):
    """iRMC Driver using SCCI.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.irmc.power.IRMCPower for power management.
    and
    :class:ironic.drivers.modules.iscsi_deploy.ISCSIDeploy for deploy.
    """

    def __init__(self):
        if not importutils.try_import('scciclient.irmc.scci'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-scciclient library"))

        self.power = power.IRMCPower()
        self.boot = boot.IRMCVirtualMediaBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.management = management.IRMCManagement()
        self.vendor = iscsi_deploy.VendorPassthru()
        self.inspect = inspect.IRMCInspect()


class IRMCVirtualMediaAgentDriver(base.BaseDriver):
    """iRMC Driver using SCCI.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.irmc.power.IRMCPower for power management
    and
    :class:ironic.drivers.modules.irmc.deploy.IRMCVirtualMediaAgentDriver for
    deploy.
    """

    def __init__(self):
        if not importutils.try_import('scciclient.irmc.scci'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-scciclient library"))

        self.power = power.IRMCPower()
        self.boot = boot.IRMCVirtualMediaBoot()
        self.deploy = agent.AgentDeploy()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.management = management.IRMCManagement()
        self.vendor = agent.AgentVendorInterface()
        self.inspect = inspect.IRMCInspect()
