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
Base classes for drivers
"""

import abc


class DeploymentDriver(object):
    """Base class for hardware deployment drivers."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @classmethod
    @abc.abstractmethod
    def is_capable(self):
        """Check if this driver is capable of handling the givens."""

    @abc.abstractmethod
    def activate_bootloader(self):
        """Prepare the bootloader for this deployment."""

    @abc.abstractmethod
    def deactivate_bootloader(self):
        """Tear down the bootloader for this deployment."""

    @abc.abstractmethod
    def activate_node(self):
        """Perform post-power-on operations for this deployment."""

    @abc.abstractmethod
    def deactivate_node(self):
        """Perform pre-power-off operations for this deployment."""


class BMCDriver(object):
    """Base class for baseboard management controller drivers."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @classmethod
    @abc.abstractmethod
    def is_capable(self):
        """Check if this driver is capable of handling the givens."""

    @abc.abstractmethod
    def start_console(self):
        """Start a remote console for this BMC."""

    @abc.abstractmethod
    def stop_console(self):
        """Stop the remote console session for this BMC."""

    @abc.abstractmethod
    def get_power_state(self):
        """Return the power state."""

    @abc.abstractmethod
    def set_power_state(self):
        """Set the power state."""

    @abc.abstractmethod
    def reboot(self):
        """Perform a hard reboot."""
