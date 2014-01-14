# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from ironic.drivers import base
from ironic.drivers.modules import ipminative
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import pxe
from ironic.drivers.modules import ssh


class PXEAndIPMIToolDriver(base.BaseDriver):
    """PXE + IPMITool driver.

    This driver implements the `core` functionality, combinding
    :class:ironic.drivers.ipmi.IPMI for power on/off and reboot with
    :class:ironic.driver.pxe.PXE for image deployment. Implementations are in
    those respective classes; this class is merely the glue between them.
    """

    def __init__(self):
        self.power = ipmitool.IPMIPower()
        self.deploy = pxe.PXEDeploy()
        self.rescue = self.deploy
        self.vendor = pxe.VendorPassthru()


class PXEAndSSHDriver(base.BaseDriver):
    """PXE + SSH driver.

    NOTE: This driver is meant only for testing environments.

    This driver implements the `core` functionality, combinding
    :class:ironic.drivers.ssh.SSH for power on/off and reboot of virtual
    machines tunneled over SSH, with :class:ironic.driver.pxe.PXE for image
    deployment. Implementations are in those respective classes; this class is
    merely the glue between them.
    """

    def __init__(self):
        self.power = ssh.SSHPower()
        self.deploy = pxe.PXEDeploy()
        self.rescue = self.deploy
        self.vendor = pxe.VendorPassthru()


class PXEAndIPMINativeDriver(base.BaseDriver):
    """PXE + Native IPMI driver.

    This driver implements the `core` functionality, combining
    :class:ironic.drivers.modules.ipminative.NativeIPMIPower for power
    on/off and reboot with
    :class:ironic.driver.modules.pxe.PXE for image deployment.
    Implementations are in those respective classes;
    this class is merely the glue between them.
    """

    def __init__(self):
        self.power = ipminative.NativeIPMIPower()
        self.deploy = pxe.PXEDeploy()
        self.rescue = self.deploy
        self.vendor = pxe.VendorPassthru()
