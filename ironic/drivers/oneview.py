# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

from oslo_config import cfg
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import generic
from ironic.drivers.modules import noop
from ironic.drivers.modules.oneview import deploy
from ironic.drivers.modules.oneview import inspect
from ironic.drivers.modules.oneview import management
from ironic.drivers.modules.oneview import power
from ironic.drivers.modules import pxe


CONF = cfg.CONF


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
        if not importutils.try_import('hpOneView.oneview_client'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import hpOneView library"))

        if not importutils.try_import('redfish'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-ilorest-library"))

        self.power = power.OneViewPower()
        self.management = management.OneViewManagement()
        self.boot = pxe.PXEBoot()
        self.deploy = deploy.OneViewAgentDeploy()
        self.inspect = inspect.OneViewInspect.create_if_enabled(
            'AgentPXEOneViewDriver')

    @classmethod
    def to_hardware_type(cls):
        # NOTE(dtantsur): classic drivers are not affected by the
        # enabled_inspect_interfaces configuration option.
        if CONF.inspector.enabled:
            inspect_interface = 'oneview'
        else:
            inspect_interface = 'no-inspect'

        return 'oneview', {'boot': 'pxe',
                           'deploy': 'oneview-direct',
                           'inspect': inspect_interface,
                           'management': 'oneview',
                           'power': 'oneview'}


class ISCSIPXEOneViewDriver(base.BaseDriver):
    """OneViewDriver using OneViewClient interface.

    This driver implements the `core` functionality using
    :class:ironic.drivers.modules.oneview.power.OneViewPower for power
    management. And
    :class:ironic.drivers.modules.oneview.deploy.OneViewIscsiDeploy for deploy.
    """

    def __init__(self):
        if not importutils.try_import('hpOneView.oneview_client'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import hpOneView library"))

        if not importutils.try_import('redfish'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-ilorest-library"))

        self.power = power.OneViewPower()
        self.management = management.OneViewManagement()
        self.boot = pxe.PXEBoot()
        self.deploy = deploy.OneViewIscsiDeploy()
        self.inspect = inspect.OneViewInspect.create_if_enabled(
            'ISCSIPXEOneViewDriver')

    @classmethod
    def to_hardware_type(cls):
        # NOTE(dtantsur): classic drivers are not affected by the
        # enabled_inspect_interfaces configuration option.
        if CONF.inspector.enabled:
            inspect_interface = 'oneview'
        else:
            inspect_interface = 'no-inspect'

        return 'oneview', {'boot': 'pxe',
                           'deploy': 'oneview-iscsi',
                           'inspect': inspect_interface,
                           'management': 'oneview',
                           'power': 'oneview'}
