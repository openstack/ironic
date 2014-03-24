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

import six


@six.add_metaclass(abc.ABCMeta)
class BaseDriver(object):
    """Base class for all drivers.

    Defines the `core`, `standardized`, and `vendor-specific` interfaces for
    drivers. Any loadable driver must implement all `core` interfaces.
    Actual implementation may instantiate one or more classes, as long as
    the interfaces are appropriate.
    """

    core_interfaces = []
    standard_interfaces = []

    power = None
    core_interfaces.append('power')
    """`Core` attribute for managing power state.

    A reference to an instance of :class:PowerInterface.
    """

    deploy = None
    core_interfaces.append('deploy')
    """`Core` attribute for managing deployments.

    A reference to an instance of :class:DeployInterface.
    """

    console = None
    standard_interfaces.append('console')
    """`Standard` attribute for managing console access.

    A reference to an instance of :class:ConsoleInterface.
    May be None, if unsupported by a driver.
    """

    rescue = None
    # NOTE(deva): hide rescue from the interface list in Icehouse
    #             because the API for this has not been created yet.
    # standard_interfaces.append('rescue')
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


@six.add_metaclass(abc.ABCMeta)
class DeployInterface(object):
    """Interface for deploy-related actions."""

    @abc.abstractmethod
    def validate(self, task, node):
        """Validate the driver-specific Node deployment info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        deploy images to the node.

        :param task: a task from TaskManager.
        :param node: a single Node to validate.
        :raises: InvalidParameterValue
        """

    @abc.abstractmethod
    def deploy(self, task, node):
        """Perform a deployment to a node.

        Perform the necessary work to deploy an image onto the specified node.
        This method will be called after prepare(), which may have already
        performed any preparatory steps, such as pre-caching some data for the
        node.

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

    @abc.abstractmethod
    def prepare(self, task, node):
        """Prepare the deployment environment for this node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `deploy`.

        :param task: a TaskManager instance.
        :param node: the Node for which to prepare a deployment environment
                     on this Conductor.
        """

    @abc.abstractmethod
    def clean_up(self, task, node):
        """Clean up the deployment environment for this node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver. It should erase
        anything cached by the `prepare` method.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `tear_down`.

        :param task: a TaskManager instance.
        :param node: the Node whose deployment environment should be cleaned up
                     on this Conductor.
        """

    @abc.abstractmethod
    def take_over(self, task, node):
        """Take over management of this node from a dead conductor.

        If conductors' hosts maintain a static relationship to nodes, this
        method should be implemented by the driver to allow conductors to
        perform the necessary work during the remapping of nodes to conductors
        when a conductor joins or leaves the cluster.

        For example, the PXE driver has an external dependency:
            Neutron must forward DHCP BOOT requests to a conductor which has
            prepared the tftpboot environment for the given node. When a
            conductor goes offline, another conductor must change this setting
            in Neutron as part of remapping that node's control to itself.
            This is performed within the `takeover` method.

        :param task: a TaskManager instance.
        :param node: the Node which is now being managed by this Conductor.
        """


@six.add_metaclass(abc.ABCMeta)
class PowerInterface(object):
    """Interface for power-related actions."""

    @abc.abstractmethod
    def validate(self, task, node):
        """Validate the driver-specific Node power info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node.

        :param task: a task from TaskManager.
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


@six.add_metaclass(abc.ABCMeta)
class ConsoleInterface(object):
    """Interface for console-related actions."""

    @abc.abstractmethod
    def validate(self, task, node):
        """Validate the driver-specific Node console info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        provide console access to the Node.

        :param task: a task from TaskManager.
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

    @abc.abstractmethod
    def get_console(self, task, node):
        """Get connection information about the console.

        This method should return the necessary information for the
        client to access the console.

        :param task: a task from TaskManager.
        :param node: a single Node.
        :returns: the console connection information.
        """


@six.add_metaclass(abc.ABCMeta)
class RescueInterface(object):
    """Interface for rescue-related actions."""

    @abc.abstractmethod
    def validate(self, task, node):
        """Validate the rescue info stored in the node' properties.

        :param task: a task from TaskManager.
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


@six.add_metaclass(abc.ABCMeta)
class VendorInterface(object):
    """Interface for all vendor passthru functionality.

    Additional vendor- or driver-specific capabilities should be implemented as
    private methods and invoked from vendor_passthru().
    """

    @abc.abstractmethod
    def validate(self, task, node, **kwargs):
        """Validate vendor-specific actions.

        :param task: a task from TaskManager.
        :param node: a single Node.
        :param kwargs: info for action.
        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if **kwargs does not contain 'method'.
        """

    @abc.abstractmethod
    def vendor_passthru(self, task, node, **kwargs):
        """Receive requests for vendor-specific actions.

        :param task: a task from TaskManager.
        :param node: a single Node.
        :param kwargs: info for action.

        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if **kwargs does not contain 'method'.
        """
