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

from oslo_config import cfg
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers import base
from ironic.drivers import ipmi
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.drivers.modules.irmc import inspect as irmc_inspect
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.drivers.modules import snmp


CONF = cfg.CONF


# For backward compatibility
PXEAndIPMIToolDriver = ipmi.PXEAndIPMIToolDriver
PXEAndIPMIToolAndSocatDriver = ipmi.PXEAndIPMIToolAndSocatDriver


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

    @classmethod
    def to_hardware_type(cls):
        return 'snmp', {
            'boot': 'pxe',
            'deploy': 'iscsi',
            'management': 'fake',
            'power': 'snmp',
        }


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

    @classmethod
    def to_hardware_type(cls):
        return 'irmc', {'boot': 'irmc-pxe',
                        'console': 'ipmitool-shellinabox',
                        'deploy': 'iscsi',
                        'inspect': 'irmc',
                        'management': 'irmc',
                        'power': 'irmc'}
