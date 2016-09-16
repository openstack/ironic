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
from ironic.drivers.modules import agent
from ironic.drivers.modules.amt import management as amt_management
from ironic.drivers.modules.amt import power as amt_power
from ironic.drivers.modules.amt import vendor as amt_vendor
from ironic.drivers.modules.cimc import management as cimc_mgmt
from ironic.drivers.modules.cimc import power as cimc_power
from ironic.drivers.modules import iboot
from ironic.drivers.modules.ilo import console as ilo_console
from ironic.drivers.modules.ilo import deploy as ilo_deploy
from ironic.drivers.modules.ilo import inspect as ilo_inspect
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules.ilo import vendor as ilo_vendor
from ironic.drivers.modules import inspector
from ironic.drivers.modules import ipminative
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import inspect as irmc_inspect
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules.msftocs import management as msftocs_management
from ironic.drivers.modules.msftocs import power as msftocs_power
from ironic.drivers.modules import pxe
from ironic.drivers.modules import seamicro
from ironic.drivers.modules import snmp
from ironic.drivers.modules import ssh
from ironic.drivers.modules.ucs import management as ucs_mgmt
from ironic.drivers.modules.ucs import power as ucs_power
from ironic.drivers.modules import virtualbox
from ironic.drivers.modules import wol
from ironic.drivers import utils


class PXEAndIPMIToolDriver(base.BaseDriver):
    """PXE + IPMITool driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipmi.IPMI` for power on/off
    and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for
    image deployment. Implementations are in those respective
    classes; this class is merely the glue between them.
    """
    def __init__(self):
        self.power = ipmitool.IPMIPower()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = ipmitool.IPMIManagement()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndIPMIToolDriver')
        self.iscsi_vendor = iscsi_deploy.VendorPassthru()
        self.ipmi_vendor = ipmitool.VendorPassthru()
        self.mapping = {'send_raw': self.ipmi_vendor,
                        'bmc_reset': self.ipmi_vendor,
                        'heartbeat': self.iscsi_vendor}
        self.driver_passthru_mapping = {'lookup': self.iscsi_vendor}
        self.vendor = utils.MixinVendorInterface(
            self.mapping,
            driver_passthru_mapping=self.driver_passthru_mapping)
        self.raid = agent.AgentRAID()


class PXEAndIPMIToolAndSocatDriver(PXEAndIPMIToolDriver):
    """PXE + IPMITool + socat driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipmi.IPMI` for power on/off
    and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` (for
    image deployment) and with
    :class:`ironic.drivers.modules.ipmitool.IPMISocatConsole`.
    This driver uses the socat console interface instead of the shellinabox
    one.
    Implementations are in those respective
    classes; this class is merely the glue between them.
    """
    def __init__(self):
        PXEAndIPMIToolDriver.__init__(self)
        self.console = ipmitool.IPMISocatConsole()


class PXEAndSSHDriver(base.BaseDriver):
    """PXE + SSH driver.

    NOTE: This driver is meant only for testing environments.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ssh.SSH` for power on/off and
    reboot of virtual machines tunneled over SSH, with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for
    image deployment. Implementations are in those respective
    classes; this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        self.power = ssh.SSHPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = ssh.SSHManagement()
        self.vendor = iscsi_deploy.VendorPassthru()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndSSHDriver')
        self.raid = agent.AgentRAID()
        self.console = ssh.ShellinaboxConsole()


class PXEAndIPMINativeDriver(base.BaseDriver):
    """PXE + Native IPMI driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipminative.NativeIPMIPower`
    for power on/off and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy`
    for image deployment.  Implementations are in those respective
    classes; this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        if not importutils.try_import('pyghmi'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import pyghmi library"))
        self.power = ipminative.NativeIPMIPower()
        self.console = ipminative.NativeIPMIShellinaboxConsole()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = ipminative.NativeIPMIManagement()
        self.iscsi_vendor = iscsi_deploy.VendorPassthru()
        self.ipminative_vendor = ipminative.VendorPassthru()
        self.mapping = {
            'send_raw': self.ipminative_vendor,
            'bmc_reset': self.ipminative_vendor,
            'heartbeat': self.iscsi_vendor,
        }
        self.driver_passthru_mapping = {'lookup': self.iscsi_vendor}
        self.vendor = utils.MixinVendorInterface(self.mapping,
                                                 self.driver_passthru_mapping)
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndIPMINativeDriver')
        self.raid = agent.AgentRAID()


class PXEAndSeaMicroDriver(base.BaseDriver):
    """PXE + SeaMicro driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.seamicro.Power` for power
    on/off and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy`
    for image deployment.  Implementations are in those respective
    classes; this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        if not importutils.try_import('seamicroclient'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import seamicroclient library"))
        self.power = seamicro.Power()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = seamicro.Management()
        self.seamicro_vendor = seamicro.VendorPassthru()
        self.iscsi_vendor = iscsi_deploy.VendorPassthru()
        self.mapping = {'heartbeat': self.iscsi_vendor,
                        'attach_volume': self.seamicro_vendor,
                        'set_node_vlan_id': self.seamicro_vendor}
        self.driver_passthru_mapping = {'lookup': self.iscsi_vendor}
        self.vendor = utils.MixinVendorInterface(self.mapping,
                                                 self.driver_passthru_mapping)
        self.console = seamicro.ShellinaboxConsole()


class PXEAndIBootDriver(base.BaseDriver):
    """PXE + IBoot PDU driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.iboot.IBootPower` for power
    on/off and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for
    image deployment.  Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        if not importutils.try_import('iboot'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import iboot library"))
        self.power = iboot.IBootPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.vendor = iscsi_deploy.VendorPassthru()


class PXEAndIloDriver(base.BaseDriver):
    """PXE + Ilo Driver using IloClient interface.

    This driver implements the `core` functionality using
    :class:`ironic.drivers.modules.ilo.power.IloPower` for
    power management
    :class:`ironic.drivers.modules.ilo.deploy.IloPXEDeploy` for image
    deployment.
    """
    def __init__(self):
        if not importutils.try_import('proliantutils'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import proliantutils library"))
        self.power = ilo_power.IloPower()
        self.boot = pxe.PXEBoot()
        self.deploy = ilo_deploy.IloPXEDeploy()
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

    supported = False

    def __init__(self):
        # Driver has a runtime dependency on PySNMP, abort load if it is absent
        if not importutils.try_import('pysnmp'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import pysnmp library"))
        self.power = snmp.SNMPPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.vendor = iscsi_deploy.VendorPassthru()

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
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = irmc_management.IRMCManagement()
        self.vendor = iscsi_deploy.VendorPassthru()
        self.inspect = irmc_inspect.IRMCInspect()


class PXEAndVirtualBoxDriver(base.BaseDriver):
    """PXE + VirtualBox driver.

    NOTE: This driver is meant only for testing environments.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.virtualbox.VirtualBoxPower` for power on/off and
    reboot of VirtualBox virtual machines, with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for image
    deployment. Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        if not importutils.try_import('pyremotevbox'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import pyremotevbox library"))
        self.power = virtualbox.VirtualBoxPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = virtualbox.VirtualBoxManagement()
        self.vendor = iscsi_deploy.VendorPassthru()
        self.raid = agent.AgentRAID()


class PXEAndAMTDriver(base.BaseDriver):
    """PXE + AMT driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.amt.AMTPower` for power on/off and reboot with
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for image
    deployment. Implementations are in those respective classes; this
    class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        if not importutils.try_import('pywsman'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import pywsman library"))
        self.power = amt_power.AMTPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = amt_management.AMTManagement()
        self.vendor = amt_vendor.AMTPXEVendorPassthru()


class PXEAndMSFTOCSDriver(base.BaseDriver):
    """PXE + MSFT OCS driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.msftocs.power.MSFTOCSPower` for power on/off
    and reboot with :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy`
    for image deployment.  Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        self.power = msftocs_power.MSFTOCSPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.management = msftocs_management.MSFTOCSManagement()
        self.vendor = iscsi_deploy.VendorPassthru()


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
        self.vendor = iscsi_deploy.VendorPassthru()
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
        self.vendor = iscsi_deploy.VendorPassthru()
        self.inspect = inspector.Inspector.create_if_enabled(
            'PXEAndCIMCDriver')


class PXEAndWakeOnLanDriver(base.BaseDriver):
    """PXE + WakeOnLan driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.wol.WakeOnLanPower` for power on
    :class:`ironic.drivers.modules.iscsi_deploy.ISCSIDeploy` for image
    deployment.  Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    supported = False

    def __init__(self):
        self.power = wol.WakeOnLanPower()
        self.boot = pxe.PXEBoot()
        self.deploy = iscsi_deploy.ISCSIDeploy()
        self.vendor = iscsi_deploy.VendorPassthru()
