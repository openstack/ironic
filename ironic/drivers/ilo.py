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

from oslo.utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import deploy
from ironic.drivers.modules.ilo import management
from ironic.drivers.modules.ilo import power


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
        self.deploy = deploy.IloVirtualMediaIscsiDeploy()
        self.console = deploy.IloConsoleInterface()
        self.management = management.IloManagement()
        self.vendor = deploy.VendorPassthru()


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
        self.deploy = deploy.IloVirtualMediaAgentDeploy()
        self.console = deploy.IloConsoleInterface()
        self.management = management.IloManagement()
        self.vendor = agent.AgentVendorInterface()
