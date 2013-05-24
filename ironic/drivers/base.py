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
Base classes for drivers.

All methods take, at minimum, a TaskManager resource and a single Node.
"""

import abc


class DeployDriver(object):
    """Base class for image deployment drivers."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @abc.abstractmethod
    def validate_driver_info(cls, node):
        """Validate the driver-specific Node info.

        This method validates whether the 'deploy_info' property of the
        supplied nodes contains the required information for this driver to
        manage the nodes.

        :returns: True or False, depending on capabilities.
        """

    @abc.abstractmethod
    def activate_bootloader(self, task, node):
        """Prepare the bootloader for this deployment."""

    @abc.abstractmethod
    def deactivate_bootloader(self, task, node):
        """Tear down the bootloader for this deployment."""

    @abc.abstractmethod
    def activate_node(self, task, node):
        """Perform post-power-on operations for this deployment."""

    @abc.abstractmethod
    def deactivate_node(self, task, node):
        """Perform pre-power-off operations for this deployment."""


class ControlDriver(object):
    """Base class for node control drivers."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @abc.abstractmethod
    def validate_driver_info(cls, node):
        """Validate the driver-specific Node info.

        This method validates whether the 'control_info' property of the
        supplied nodes contains the required information for this driver to
        manage the nodes.

        :returns: True or False, depending on capabilities.
        """

    @abc.abstractmethod
    def start_console(self, task, node):
        """Start a remote console for the nodes."""

    @abc.abstractmethod
    def stop_console(self, task, node):
        """Stop the remote console session for the nodes."""

    @abc.abstractmethod
    def get_power_state(self, task, node):
        """Return the power state of the nodes."""

    @abc.abstractmethod
    def set_power_state(self, task, node):
        """Set the power state of the nodes."""

    @abc.abstractmethod
    def reboot(self, task, node):
        """Perform a hard reboot of the nodes."""
