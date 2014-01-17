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
Fake drivers used in testing.
"""

from ironic.drivers import base
from ironic.drivers.modules import fake
from ironic.drivers.modules import ipminative
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import pxe
from ironic.drivers.modules import seamicro
from ironic.drivers.modules import ssh


class FakeDriver(base.BaseDriver):
    """Example implementation of a Driver."""

    def __init__(self):
        self.power = fake.FakePower()
        self.deploy = fake.FakeDeploy()

        a = fake.FakeVendorA()
        b = fake.FakeVendorB()
        self.vendor = fake.MultipleVendorInterface(a, b)
        self.console = fake.FakeConsole()


class FakeIPMIToolDriver(base.BaseDriver):
    """Example implementation of a Driver."""

    def __init__(self):
        self.power = ipmitool.IPMIPower()
        self.deploy = fake.FakeDeploy()
        self.vendor = ipmitool.VendorPassthru()


class FakePXEDriver(base.BaseDriver):
    """Example implementation of a Driver."""

    def __init__(self):
        self.power = fake.FakePower()
        self.deploy = pxe.PXEDeploy()
        self.rescue = self.deploy
        self.vendor = pxe.VendorPassthru()


class FakeSSHDriver(base.BaseDriver):
    """Example implementation of a Driver."""

    def __init__(self):
        self.power = ssh.SSHPower()
        self.deploy = fake.FakeDeploy()


class FakeIPMINativeDriver(base.BaseDriver):
    """Example implementation of a Driver."""

    def __init__(self):
        self.power = ipminative.NativeIPMIPower()
        self.deploy = fake.FakeDeploy()
        self.vendor = ipminative.VendorPassthru()


class FakeSeaMicroDriver(base.BaseDriver):
    """Fake SeaMicro driver."""

    def __init__(self):
        self.power = seamicro.Power()
        self.deploy = fake.FakeDeploy()
        self.rescue = self.deploy
        self.seamicro_vendor = seamicro.VendorPassthru()
        self.pxe_vendor = pxe.VendorPassthru()
        self.vendor = seamicro.SeaMicroPXEMultipleVendorInterface(
            self.seamicro_vendor, self.pxe_vendor)
