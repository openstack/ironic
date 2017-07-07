# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import ipmi
from ironic.drivers.modules import agent
from ironic.drivers.modules.cimc import management as cimc_mgmt
from ironic.drivers.modules.cimc import power as cimc_power
from ironic.drivers.modules import inspector
from ironic.drivers.modules import pxe
from ironic.drivers.modules.ucs import management as ucs_mgmt
from ironic.drivers.modules.ucs import power as ucs_power


# For backward compatibility
AgentAndIPMIToolDriver = ipmi.AgentAndIPMIToolDriver
AgentAndIPMIToolAndSocatDriver = ipmi.AgentAndIPMIToolAndSocatDriver


class AgentAndUcsDriver(base.BaseDriver):
    """Agent + Cisco UCSM driver.

    This driver implements the `core` functionality, combining
    :class:ironic.drivers.modules.ucs.power.Power for power
    on/off and reboot with
    :class:'ironic.driver.modules.agent.AgentDeploy' (for image deployment.)
    Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    def __init__(self):
        if not importutils.try_import('UcsSdk'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import UcsSdk library"))
        self.power = ucs_power.Power()
        self.boot = pxe.PXEBoot()
        self.deploy = agent.AgentDeploy()
        self.management = ucs_mgmt.UcsManagement()
        self.inspect = inspector.Inspector.create_if_enabled(
            'AgentAndUcsDriver')


class AgentAndCIMCDriver(base.BaseDriver):
    """Agent + Cisco CIMC driver.

    This driver implements the `core` functionality, combining
    :class:ironic.drivers.modules.cimc.power.Power for power
    on/off and reboot with
    :class:'ironic.driver.modules.agent.AgentDeploy' (for image deployment.)
    Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    def __init__(self):
        if not importutils.try_import('ImcSdk'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import ImcSdk library"))
        self.power = cimc_power.Power()
        self.boot = pxe.PXEBoot()
        self.deploy = agent.AgentDeploy()
        self.management = cimc_mgmt.CIMCManagement()
        self.inspect = inspector.Inspector.create_if_enabled(
            'AgentAndCIMCDriver')
