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

from oslo.utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers.modules import iboot
from ironic.drivers.modules.ilo import deploy as ilo_deploy
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules import ipminative
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import pxe
from ironic.drivers.modules import seamicro
from ironic.drivers.modules import snmp
from ironic.drivers.modules import ssh
from ironic.drivers import utils


class PXEAndIPMIToolDriver(base.BaseDriver):
    """PXE + IPMITool driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.ipmi.IPMI` for power on/off and reboot with
    :class:`ironic.driver.pxe.PXE` for image deployment. Implementations are in
    those respective classes; this class is merely the glue between them.
    """

    def __init__(self):
        self.power = ipmitool.IPMIPower()
        self.console = ipmitool.IPMIShellinaboxConsole()
        self.deploy = pxe.PXEDeploy()
        self.management = ipmitool.IPMIManagement()
        self.vendor = pxe.VendorPassthru()


class PXEAndSSHDriver(base.BaseDriver):
    """PXE + SSH driver.

    NOTE: This driver is meant only for testing environments.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.ssh.SSH` for power on/off and reboot of virtual
    machines tunneled over SSH, with :class:`ironic.driver.pxe.PXE` for image
    deployment. Implementations are in those respective classes; this class is
    merely the glue between them.
    """

    def __init__(self):
        self.power = ssh.SSHPower()
        self.deploy = pxe.PXEDeploy()
        self.management = ssh.SSHManagement()
        self.vendor = pxe.VendorPassthru()


class PXEAndIPMINativeDriver(base.BaseDriver):
    """PXE + Native IPMI driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.ipminative.NativeIPMIPower` for power
    on/off and reboot with
    :class:`ironic.driver.modules.pxe.PXE` for image deployment.
    Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    def __init__(self):
        if not importutils.try_import('pyghmi'):
            raise exception.DriverLoadError(
                    driver=self.__class__.__name__,
                    reason=_("Unable to import pyghmi library"))
        self.power = ipminative.NativeIPMIPower()
        self.console = ipminative.NativeIPMIShellinaboxConsole()
        self.deploy = pxe.PXEDeploy()
        self.management = ipminative.NativeIPMIManagement()
        self.vendor = pxe.VendorPassthru()


class PXEAndSeaMicroDriver(base.BaseDriver):
    """PXE + SeaMicro driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.seamicro.Power` for power
    on/off and reboot with
    :class:`ironic.driver.modules.pxe.PXE` for image deployment.
    Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    def __init__(self):
        if not importutils.try_import('seamicroclient'):
            raise exception.DriverLoadError(
                    driver=self.__class__.__name__,
                    reason=_("Unable to import seamicroclient library"))
        self.power = seamicro.Power()
        self.deploy = pxe.PXEDeploy()
        self.management = seamicro.Management()
        self.seamicro_vendor = seamicro.VendorPassthru()
        self.pxe_vendor = pxe.VendorPassthru()
        self.mapping = {'pass_deploy_info': self.pxe_vendor,
                        'attach_volume': self.seamicro_vendor,
                        'set_node_vlan_id': self.seamicro_vendor}
        self.vendor = utils.MixinVendorInterface(self.mapping)
        self.console = seamicro.ShellinaboxConsole()


class PXEAndIBootDriver(base.BaseDriver):
    """PXE + IBoot PDU driver.

    This driver implements the `core` functionality, combining
    :class:`ironic.drivers.modules.iboot.IBootPower` for power
    on/off and reboot with
    :class:`ironic.driver.modules.pxe.PXE` for image deployment.
    Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    def __init__(self):
        if not importutils.try_import('iboot'):
            raise exception.DriverLoadError(
                    driver=self.__class__.__name__,
                    reason=_("Unable to import iboot library"))
        self.power = iboot.IBootPower()
        self.deploy = pxe.PXEDeploy()
        self.vendor = pxe.VendorPassthru()


class PXEAndIloDriver(base.BaseDriver):
    """PXE + Ilo Driver using IloClient interface.

    This driver implements the `core` functionality using
    :class:`ironic.drivers.modules.ilo.power.IloPower` for power management
    :class:`ironic.drivers.modules.ilo.deploy.IloPXEDeploy` for image
    deployment.

    """

    def __init__(self):
        if not importutils.try_import('proliantutils'):
            raise exception.DriverLoadError(
                    driver=self.__class__.__name__,
                    reason=_("Unable to import proliantutils library"))
        self.power = ilo_power.IloPower()
        self.deploy = ilo_deploy.IloPXEDeploy()
        self.vendor = ilo_deploy.IloPXEVendorPassthru()
        self.console = ilo_deploy.IloConsoleInterface()
        self.management = ilo_management.IloManagement()


class PXEAndSNMPDriver(base.BaseDriver):
    """PXE + SNMP driver.

    This driver implements the 'core' functionality, combining
    :class:`ironic.drivers.snmp.SNMP` for power on/off and reboot with
    :class:`ironic.drivers.pxe.PXE` for image deployment. Implentations are in
    those respective classes; this class is merely the glue between them.
    """

    def __init__(self):
        # Driver has a runtime dependency on PySNMP, abort load if it is absent
        if not importutils.try_import('pysnmp'):
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=_("Unable to import pysnmp library"))
        self.power = snmp.SNMPPower()
        self.deploy = pxe.PXEDeploy()
        self.vendor = pxe.VendorPassthru()

        # PDUs have no boot device management capability.
        # Only PXE as a boot device is supported.
        self.management = None
