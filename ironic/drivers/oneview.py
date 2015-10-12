#
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
from ironic.drivers.modules import agent
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import management
from ironic.drivers.modules.oneview import power
from ironic.drivers.modules.oneview import vendor
from ironic.drivers.modules import pxe


class AgentPXEOneViewDriver(base.BaseDriver):
    """Agent + OneView driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.ov.OVPower` for power on/off and reboot of virtual
    machines, with :class:`ironic.driver.pxe.PXEBoot` for booting deploy kernel
    and ramdisk and :class:`ironic.driver.iscsi_deploy.ISCSIDeploy` for image
    deployment. Implementations are in those respective classes; this class is
    merely the glue between them.
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
        self.deploy = agent.AgentDeploy()
        self.vendor = vendor.AgentVendorInterface()


class ISCSIPXEOneViewDriver(base.BaseDriver):
    """PXE + OneView driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.ov.OVPower` for power on/off and reboot of virtual
    machines, with :class:`ironic.driver.pxe.PXEBoot` for booting deploy kernel
    and ramdisk and :class:`ironic.driver.iscsi_deploy.ISCSIDeploy` for image
    deployment. Implementations are in those respective classes; this class is
    merely the glue between them.
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
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.vendor = iscsi_deploy.VendorPassthru()
