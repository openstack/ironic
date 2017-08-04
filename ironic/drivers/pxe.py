# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
PXE Driver and supporting meta-classes.
"""

from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import ipmi
from ironic.drivers.modules import agent
from ironic.drivers.modules.cimc import management as cimc_mgmt
from ironic.drivers.modules.cimc import power as cimc_power
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import console as ilo_console
from ironic.drivers.modules.ilo import inspect as ilo_inspect
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules.ilo import vendor as ilo_vendor
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.drivers.modules.irmc import inspect as irmc_inspect
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.drivers.modules import snmp
from ironic.drivers.modules.ucs import management as ucs_mgmt
from ironic.drivers.modules.ucs import power as ucs_power


# For backward compatibility
PXEAndIPMIToolDriver = ipmi.PXEAndIPMIToolDriver
PXEAndIPMIToolAndSocatDriver = ipmi.PXEAndIPMIToolAndSocatDriver


class PXEAndIloDriver(base.BaseDriver):
    """PXE + Ilo Driver using IloClient interface.

    This driver implements the `core` functionality using
    :class:`ironic.drivers.modules.ilo.power.IloPower` for
    power management
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for
    image deployment.
    :class:`ironic.drivers.modules.ilo.boot.IloPXEBoot` for boot
    related actions.
    """
    def __init__(self):
        if not importutils.try_import('proliantutils'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import proliantutils library"))
        self.power = ilo_power.IloPower()
        self.boot = ilo_boot.IloPXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.vendor = ilo_vendor.VendorPassthru()
        self.console = ilo_console.IloConsoleInterface()
        self.management = ilo_management.IloManagement()
        self.inspect = ilo_inspect.IloInspect()
        self.raid = agent.AgentRAID()


class PXEAndSNMPDriver(base.BaseDriver):
    """PXE + SNMP driver.

    This driver implements the 'core' functionality, combining
    :class:`ironic.drivers.snmp.SNMP` for power on/off and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for image
    deployment. Implentations are in those respective classes; this
    class is merely the glue between them.
    """

    def __init__(self):
        # Driver has a runtime dependency on PySNMP, abort load if it is absent
        if not importutils.try_import('pysnmp'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import pysnmp library"))
        self.power = snmp.SNMPPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()

        # PDUs have no boot device management capability.
        # Only PXE as a boot device is supported.
        self.management = None


class PXEAndIRMCDriver(base.BaseDriver):
    """PXE + iRMC driver using SCCI.

    This driver implements the `core` functionality using
    :class:`ironic.drivers.modules.irmc.power.IRMCPower` for
    power management :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy`
    for image deployment.
    """
    def __init__(self):
        if not importutils.try_import('scciclient'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import python-scciclient library"))
        self.power = irmc_power.IRMCPower()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.boot = irmc_boot.IRMCPXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = irmc_management.IRMCManagement()
        self.inspect = irmc_inspect.IRMCInspect()


class PXEAndUcsDriver(base.BaseDriver):
    """PXE + Cisco UCSM driver.

    This driver implements the `core` functionality, combining
    :class:ironic.drivers.modules.ucs.power.Power for power
    on/off and reboot with
    :class:ironic.drivers.modules.iscsi_deploy.ISCSIDeploy for image
    deployment.  Implementations are in those respective classes;
    this class is merely the glue between them.
    """
    def __init__(self):
        if not importutils.try_import('UcsSdk'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import UcsSdk library"))
        self.power = ucs_power.Power()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = ucs_mgmt.UcsManagement()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndUcsDriver')


class PXEAndCIMCDriver(base.BaseDriver):
    """PXE + Cisco IMC driver.

    This driver implements the 'core' functionality, combining
    :class:`ironic.drivers.modules.cimc.Power` for power on/off and reboot with
    :class:`ironic.drivers.modules.pxe.PXEBoot` for booting the node and
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for image
    deployment. Implentations are in those respective classes; this
    class is merely the glue between them.
    """
    def __init__(self):
        if not importutils.try_import('ImcSdk'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import ImcSdk library"))
        self.power = cimc_power.Power()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = cimc_mgmt.CIMCManagement()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndCIMCDriver')
