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


class PXEDeploy(base.DeployInterface):
    """PXE Deploy Interface: just a stub until the real driver is ported."""

    def validate(self, nodes):
        pass

    def deploy(self, task, nodes):
        pass

    def tear_down(self, task, nodes):
        pass


class PXERescue(base.RescueInterface):
    """PXE Rescue Interface: just a stub until the real driver is ported."""

    def validate(self, nodes):
        pass

    def rescue(self, task, nodes):
        pass

    def unrescue(self, task, nodes):
        pass


class IPMIVendorPassthru(base.VendorInterface):
    """Interface to mix IPMI and PXE vendor-specific interfaces."""

    def validate(self, node):
        pass

    def vendor_passthru(self, task, node, *args, **kwargs):
        method = kwargs.get('method')
        if method == 'set_boot_device':
            return node.driver.vendor._set_boot_device(
                        task, node,
                        args.get('device'),
                        args.get('persistent'))
        else:
            return
