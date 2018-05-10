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
Abstract base class for all hardware types.
"""

import abc

import six

from ironic.common import exception
from ironic.drivers import base as driver_base
from ironic.drivers.modules.network import noop as noop_net
from ironic.drivers.modules import noop
from ironic.drivers.modules.storage import noop as noop_storage


@six.add_metaclass(abc.ABCMeta)
class AbstractHardwareType(object):
    """Abstract base class for all hardware types.

    Hardware type is a family of hardware supporting the same set of interfaces
    from the ironic standpoint. This can be as wide as all hardware supporting
    the IPMI protocol or as narrow as several hardware models supporting some
    specific interfaces.

    A hardware type defines an ordered list of supported implementations for
    each driver interface (power, deploy, etc).
    """

    supported = True
    """Whether hardware is supported by the community."""

    # Required hardware interfaces

    @abc.abstractproperty
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""

    @abc.abstractproperty
    def supported_deploy_interfaces(self):
        """List of supported deploy interfaces."""

    @abc.abstractproperty
    def supported_management_interfaces(self):
        """List of supported management interfaces."""

    @abc.abstractproperty
    def supported_power_interfaces(self):
        """List of supported power interfaces."""

    # Optional hardware interfaces
    @property
    def supported_bios_interfaces(self):
        """List of supported bios interfaces."""
        return [noop.NoBIOS]

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [noop.NoConsole]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [noop.NoInspect]

    @property
    def supported_network_interfaces(self):
        """List of supported network interfaces."""
        return [noop_net.NoopNetwork]

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [noop.NoRAID]

    @property
    def supported_rescue_interfaces(self):
        """List of supported rescue interfaces."""
        return [noop.NoRescue]

    @property
    def supported_storage_interfaces(self):
        """List of supported storage interfaces."""
        return [noop_storage.NoopStorage]

    @property
    def supported_vendor_interfaces(self):
        """List of supported vendor interfaces."""
        return [noop.NoVendor]

    def get_properties(self):
        """Get the properties of the hardware type.

        Note that this returns properties for the default interface of each
        type, for this hardware type. Since this is not node-aware,
        interface overrides can't be detected.

        :returns: dictionary of <property name>:<property description> entries.
        """
        # NOTE(jroll) this avoids a circular import
        from ironic.common import driver_factory

        properties = {}
        for iface_type in driver_base.ALL_INTERFACES:
            try:
                default_iface = driver_factory.default_interface(self,
                                                                 iface_type)
            except (exception.InterfaceNotFoundInEntrypoint,
                    exception.NoValidDefaultForInterface):
                continue

            iface = driver_factory.get_interface(self, iface_type,
                                                 default_iface)
            properties.update(iface.get_properties())
        return properties
