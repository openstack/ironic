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
Abstract base classes for drivers.
"""

import abc


class BaseDriver(object):
    """Base class for all drivers.

    Defines the `core`, `standardized`, and `vendor-specific` interfaces for
    drivers. Any loadable driver must implement all `core` interfaces.
    Actual implementation may instantiate one or more classes, as long as
    the interfaces are appropriate.
    """

    __metaclass__ = abc.ABCMeta

    power = None
    """`Core` attribute for managing power state.

    A reference to an instance of :class:PowerInterface.
    """

    deploy = None
    """`Core` attribute for managing deployments.

    A reference to an instance of :class:DeployInterface.
    """

    console = None
    """`Standard` attribute for managing console access.

    A reference to an instance of :class:ConsoleInterface.
    May be None, if unsupported by a driver.
    """

    rescue = None
    """`Standard` attribute for accessing rescue features.

    A reference to an instance of :class:RescueInterface.
    May be None, if unsupported by a driver.
    """

    vendor = None
    """Attribute for accessing any vendor-specific extensions.

    A reference to an instance of :class:VendorInterface.
    May be None, if the driver does not implement any vendor extensions.
    """

    @abc.abstractmethod
    def __init__(self):
        pass


class DeployInterface(object):
    """Interface for deploy-related actions."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def validate(self, node):
        """Validate the driver-specific Node deployment info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        deploy images to the node.

        :param node: a single Node to validate.
        :raises: InvalidParameterValue
        """

    @abc.abstractmethod
    def deploy(self, task, node):
        """Perform a deployment to a node.

        Given a node with complete metadata, deploy the indicated image
        to the node.

        :param task: a TaskManager instance.
        :param node: the Node to act upon.
        :returns: status of the deploy. One of ironic.common.states.
        """

    @abc.abstractmethod
    def tear_down(self, task, node):
        """Tear down a previous deployment.

        Given a node that has been previously deployed to,
        do all cleanup and tear down necessary to "un-deploy" that node.

        :param task: a TaskManager instance.
        :param node: the Node to act upon.
        :returns: status of the deploy. One of ironic.common.states.
        """


class PowerInterface(object):
    """Interface for power-related actions."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def validate(self, node):
        """Validate the driver-specific Node power info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node.

        :param node: a single Node to validate.
        :raises: InvalidParameterValue
        """

    @abc.abstractmethod
    def get_power_state(self, task, node):
        """Return the power state of the node.

        TODO
        """

    @abc.abstractmethod
    def set_power_state(self, task, node, power_state):
        """Set the power state of the node.

        TODO
        """

    @abc.abstractmethod
    def reboot(self, task, node):
        """Perform a hard reboot of the node.

        TODO
        """


class ConsoleInterface(object):
    """Interface for console-related actions."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def validate(self, node):
        """Validate the driver-specific Node console info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        provide console access to the Node.

        :param node: a single Node to validate.
        :raises: InvalidParameterValue
        """

    @abc.abstractmethod
    def start_console(self, task, node):
        """Start a remote console for the node.

        TODO
        """

    @abc.abstractmethod
    def stop_console(self, task, node):
        """Stop the remote console session for the node.

        TODO
        """


class RescueInterface(object):
    """Interface for rescue-related actions."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def validate(self, node):
        """Validate the rescue info stored in the node' properties.

        :param node: a single Node to validate.
        :raises: InvalidParameterValue
        """

    @abc.abstractmethod
    def rescue(self, task, node):
        """Boot the node into a rescue environment.

        TODO
        """

    @abc.abstractmethod
    def unrescue(self, task, node):
        """Tear down the rescue environment, and return to normal.

        TODO
        """


class VendorInterface(object):
    """Interface for all vendor passthru functionality.

    Additional vendor- or driver-specific capabilities should be implemented as
    private methods and invoked from vendor_passthru().
    """

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def validate(self, node, **kwargs):
        """Validate vendor-specific actions.

        :param node: a single Node.
        :param kwargs: info for action.
        :raises: InvalidParameterValue
        """

    @abc.abstractmethod
    def vendor_passthru(self, task, node, **kwargs):
        """Receive requests for vendor-specific actions.

        :param task: a task from TaskManager.
        :param node: a single Node.
        :param kwargs: info for action.
        """
