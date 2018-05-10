# Copyright 2016 Red Hat, Inc.
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
Fake hardware type.
"""

from ironic.drivers import hardware_type
from ironic.drivers.modules import fake
from ironic.drivers.modules import noop
from ironic.drivers.modules.storage import noop as noop_storage


class FakeHardware(hardware_type.AbstractHardwareType):
    """Fake hardware type.

    This hardware type is special-cased in the driver factory to bypass
    compatibility verification. Thus, supported_* methods here are only
    for calculating the defaults, not for actual check.

    All fake implementations are still expected to be enabled in the
    configuration.
    """
    @property
    def supported_bios_interfaces(self):
        """List of classes of supported bios interfaces."""
        return [fake.FakeBIOS, noop.NoBIOS]

    @property
    def supported_boot_interfaces(self):
        """List of classes of supported boot interfaces."""
        return [fake.FakeBoot]

    @property
    def supported_console_interfaces(self):
        """List of classes of supported console interfaces."""
        return [fake.FakeConsole, noop.NoConsole]

    @property
    def supported_deploy_interfaces(self):
        """List of classes of supported deploy interfaces."""
        return [fake.FakeDeploy]

    @property
    def supported_inspect_interfaces(self):
        """List of classes of supported inspect interfaces."""
        return [fake.FakeInspect, noop.NoInspect]

    @property
    def supported_management_interfaces(self):
        """List of classes of supported management interfaces."""
        return [fake.FakeManagement]

    @property
    def supported_power_interfaces(self):
        """List of classes of supported power interfaces."""
        return [fake.FakePower]

    @property
    def supported_raid_interfaces(self):
        """List of classes of supported raid interfaces."""
        return [fake.FakeRAID, noop.NoRAID]

    @property
    def supported_rescue_interfaces(self):
        """List of classes of supported rescue interfaces."""
        return [fake.FakeRescue, noop.NoRescue]

    @property
    def supported_storage_interfaces(self):
        """List of classes of supported storage interfaces."""
        return [fake.FakeStorage, noop_storage.NoopStorage]

    @property
    def supported_vendor_interfaces(self):
        """List of classes of supported rescue interfaces."""
        return [fake.FakeVendorB, fake.FakeVendorA, noop.NoVendor]

    @property
    def supported_network_interfaces(self):
        # import late to avoid circular imports
        from ironic.drivers.modules.network import flat
        from ironic.drivers.modules.network import noop
        return [flat.FlatNetwork, noop.NoopNetwork]
