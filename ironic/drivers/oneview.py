# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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
OneView Driver and supporting meta-classes.
"""
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import generic
from ironic.drivers.modules import noop
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy
from ironic.drivers.modules.oneview import inspect
from ironic.drivers.modules.oneview import management
from ironic.drivers.modules.oneview import power
from ironic.drivers.modules import pxe


class OneViewHardware(generic.GenericHardware):
    """OneView hardware type.

    OneView hardware type is targeted for OneView
    """

    @property
    def supported_deploy_interfaces(self):
        """List of supported deploy interfaces."""
        return [deploy.OneViewIscsiDeploy, deploy.OneViewAgentDeploy]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [inspect.OneViewInspect, noop.NoInspect]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [management.OneViewManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [power.OneViewPower]


class AgentPXEOneViewDriver(base.BaseDriver):
    """OneViewDriver using OneViewClient interface.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.oneview.power.OneViewPower for power
    management. And
    :class:ironic.drivers.modules.oneview.deploy.OneViewAgentDeploy for deploy.
    """

    def __init__(self):
        if not importutils.try_import('oneview_client.client'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-oneviewclient library"))

        # Checks connectivity to OneView and version compatibility on driver
        # initialization
        oneview_client = common.get_oneview_client()
        oneview_client.verify_oneview_version()
        oneview_client.verify_credentials()
        self.power = power.OneViewPower()
        self.management = management.OneViewManagement()
        self.boot = pxe.PXEBoot()
        self.deploy = deploy.OneViewAgentDeploy()
        self.inspect = inspect.OneViewInspect.create_if_enabled(
            'AgentPXEOneViewDriver')


class ISCSIPXEOneViewDriver(base.BaseDriver):
    """OneViewDriver using OneViewClient interface.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.oneview.power.OneViewPower for power
    management. And
    :class:ironic.drivers.modules.oneview.deploy.OneViewIscsiDeploy for deploy.
    """

    def __init__(self):
        if not importutils.try_import('oneview_client.client'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-oneviewclient library"))

        # Checks connectivity to OneView and version compatibility on driver
        # initialization
        oneview_client = common.get_oneview_client()
        oneview_client.verify_oneview_version()
        oneview_client.verify_credentials()
        self.power = power.OneViewPower()
        self.management = management.OneViewManagement()
        self.boot = pxe.PXEBoot()
        self.deploy = deploy.OneViewIscsiDeploy()
        self.inspect = inspect.OneViewInspect.create_if_enabled(
            'ISCSIPXEOneViewDriver')
