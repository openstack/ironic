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
import collections
import functools
import inspect

from oslo.utils import excutils
import six

from ironic.common import exception
from ironic.common.i18n import _LE
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)


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

    management = None
    """`Standard` attribute for management related features.

    A reference to an instance of :class:ManagementInterface.
    May be None, if unsupported by a driver.
    """
    standard_interfaces.append('management')

    vendor = None
    """Attribute for accessing any vendor-specific extensions.

    A reference to an instance of :class:VendorInterface.
    May be None, if the driver does not implement any vendor extensions.
    """

    @abc.abstractmethod
    def __init__(self):
        pass

    def get_properties(self):
        """Get the properties of the driver.

        :returns: dictionary of <property name>:<property description> entries.
        """

        properties = {}
        for iface_name in (self.core_interfaces +
                           self.standard_interfaces +
                           ['vendor']):
            iface = getattr(self, iface_name, None)
            if iface:
                properties.update(iface.get_properties())
        return properties


@six.add_metaclass(abc.ABCMeta)
class DeployInterface(object):
    """Interface for deploy-related actions."""

    @abc.abstractmethod
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """

    @abc.abstractmethod
    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the 'driver_info' property of the
        task's node contains the required information for this driver to
        deploy images to the node. If invalid, raises an exception; otherwise
        returns None.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue
        """

    @abc.abstractmethod
    def deploy(self, task):
        """Perform a deployment to the task's node.

        Perform the necessary work to deploy an image onto the specified node.
        This method will be called after prepare(), which may have already
        performed any preparatory steps, such as pre-caching some data for the
        node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: status of the deploy. One of ironic.common.states.
        """

    @abc.abstractmethod
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Given a node that has been previously deployed to,
        do all cleanup and tear down necessary to "un-deploy" that node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: status of the deploy. One of ironic.common.states.
        """

    @abc.abstractmethod
    def prepare(self, task):
        """Prepare the deployment environment for the task's node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `deploy`.

        :param task: a TaskManager instance containing the node to act on.
        """

    @abc.abstractmethod
    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver. It should erase
        anything cached by the `prepare` method.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `tear_down`.

        :param task: a TaskManager instance containing the node to act on.
        """

    @abc.abstractmethod
    def take_over(self, task):
        """Take over management of this task's node from a dead conductor.

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

        :param task: a TaskManager instance containing the node to act on.
        """


@six.add_metaclass(abc.ABCMeta)
class PowerInterface(object):
    """Interface for power-related actions."""

    @abc.abstractmethod
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """

    @abc.abstractmethod
    def validate(self, task):
        """Validate the driver-specific Node power info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the power state of the node. If invalid, raises an exception;
        otherwise, returns None.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue
        """

    @abc.abstractmethod
    def get_power_state(self, task):
        """Return the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if a required parameter is missing.
        :returns: a power state. One of :mod:`ironic.common.states`.
        """

    @abc.abstractmethod
    def set_power_state(self, task, power_state):
        """Set the power state of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :param power_state: Any power state from :mod:`ironic.common.states`.
        :raises: MissingParameterValue if a required parameter is missing.
        """

    @abc.abstractmethod
    def reboot(self, task):
        """Perform a hard reboot of the task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if a required parameter is missing.
        """


@six.add_metaclass(abc.ABCMeta)
class ConsoleInterface(object):
    """Interface for console-related actions."""

    @abc.abstractmethod
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """

    @abc.abstractmethod
    def validate(self, task):
        """Validate the driver-specific Node console info.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        provide console access to the Node. If invalid, raises an exception;
        otherwise returns None.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue
        """

    @abc.abstractmethod
    def start_console(self, task):
        """Start a remote console for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        """

    @abc.abstractmethod
    def stop_console(self, task):
        """Stop the remote console session for the task's node.

        :param task: a TaskManager instance containing the node to act on.
        """

    @abc.abstractmethod
    def get_console(self, task):
        """Get connection information about the console.

        This method should return the necessary information for the
        client to access the console.

        :param task: a TaskManager instance containing the node to act on.
        :returns: the console connection information.
        """


@six.add_metaclass(abc.ABCMeta)
class RescueInterface(object):
    """Interface for rescue-related actions."""

    @abc.abstractmethod
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """

    @abc.abstractmethod
    def validate(self, task):
        """Validate the rescue info stored in the node' properties.

        If invalid, raises an exception; otherwise returns None.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue
        """

    @abc.abstractmethod
    def rescue(self, task):
        """Boot the task's node into a rescue environment.

        :param task: a TaskManager instance containing the node to act on.
        """

    @abc.abstractmethod
    def unrescue(self, task):
        """Tear down the rescue environment, and return to normal.

        :param task: a TaskManager instance containing the node to act on.
        """


# Representation of a single vendor method metadata
VendorMetadata = collections.namedtuple('VendorMetadata', ['method',
                                                           'metadata'])


def _passthru(http_methods, method=None, async=True, driver_passthru=False,
              description=None):
    """A decorator for registering a function as a passthru function.

    Decorator ensures function is ready to catch any ironic exceptions
    and reraise them after logging the issue. It also catches non-ironic
    exceptions reraising them as a VendorPassthruException after writing
    a log.

    Logs need to be added because even though the exception is being
    reraised, it won't be handled if it is an async. call.

    :param http_methods: A list of supported HTTP methods by the vendor
                         function.
    :param method: an arbitrary string describing the action to be taken.
    :param async: Boolean value. If True invoke the passthru function
                  asynchronously; if False, synchronously. If a passthru
                  function touches the BMC we strongly recommend it to
                  run asynchronously. Defaults to True.
    :param driver_passthru: Boolean value. True if this is a driver vendor
                            passthru method, and False if it is a node
                            vendor passthru method.
    :param description: a string shortly describing what the method does.

    """
    def handle_passthru(func):
        api_method = method
        if api_method is None:
            api_method = func.__name__

        supported_ = [i.upper() for i in http_methods]
        description_ = description or ''
        metadata = VendorMetadata(api_method, {'http_methods': supported_,
                                               'async': async,
                                               'description': description_})
        if driver_passthru:
            func._driver_metadata = metadata
        else:
            func._vendor_metadata = metadata

        passthru_logmessage = _LE('vendor_passthru failed with method %s')

        @functools.wraps(func)
        def passthru_handler(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exception.IronicException as e:
                with excutils.save_and_reraise_exception():
                    LOG.exception(passthru_logmessage, api_method)
            except Exception as e:
                # catch-all in case something bubbles up here
                LOG.exception(passthru_logmessage, api_method)
                raise exception.VendorPassthruException(message=e)
        return passthru_handler
    return handle_passthru


def passthru(http_methods, method=None, async=True, description=None):
    return _passthru(http_methods, method, async, driver_passthru=False,
                     description=description)


def driver_passthru(http_methods, method=None, async=True, description=None):
    return _passthru(http_methods, method, async, driver_passthru=True,
                     description=description)


@six.add_metaclass(abc.ABCMeta)
class VendorInterface(object):
    """Interface for all vendor passthru functionality.

    Additional vendor- or driver-specific capabilities should be
    implemented as a method in the class inheriting from this class and
    use the @passthru or @driver_passthru decorators.

    Methods decorated with @driver_passthru should be short-lived because
    it is a blocking call.
    """

    def __new__(cls, *args, **kwargs):
        inst = super(VendorInterface, cls).__new__(cls, *args, **kwargs)

        inst.vendor_routes = {}
        inst.driver_routes = {}

        for name, ref in inspect.getmembers(inst, predicate=inspect.ismethod):
            vmeta = getattr(ref, '_vendor_metadata', None)
            dmeta = getattr(ref, '_driver_metadata', None)

            if vmeta is not None:
                vmeta.metadata['func'] = ref
                inst.vendor_routes.update({vmeta.method: vmeta.metadata})

            if dmeta is not None:
                dmeta.metadata['func'] = ref
                inst.driver_routes.update({dmeta.method: dmeta.metadata})

        return inst

    @abc.abstractmethod
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """

    @abc.abstractmethod
    def validate(self, task, **kwargs):
        """Validate vendor-specific actions.

        If invalid, raises an exception; otherwise returns None.

        :param task: a task from TaskManager.
        :param kwargs: info for action.
        :raises: UnsupportedDriverExtension if 'method' can not be mapped to
                 the supported interfaces.
        :raises: InvalidParameterValue if kwargs does not contain 'method'.
        :raises: MissingParameterValue
        """

    def driver_validate(self, method, **kwargs):
        """Validate driver-vendor-passthru actions.

        If invalid, raises an exception; otherwise returns None.

        :param method: method to be validated
        :param kwargs: info for action.
        :raises: MissingParameterValue if kwargs does not contain
                 certain parameter.
        :raises: InvalidParameterValue if parameter does not match.
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class ManagementInterface(object):
    """Interface for management related actions."""

    @abc.abstractmethod
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """

    @abc.abstractmethod
    def validate(self, task):
        """Validate the driver-specific management information.

        If invalid, raises an exception; otherwise returns None.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue
        """

    @abc.abstractmethod
    def get_supported_boot_devices(self):
        """Get a list of the supported boot devices.

        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.
        """

    @abc.abstractmethod
    def set_boot_device(self, task, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param task: a task from TaskManager.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.
        :raises: InvalidParameterValue if an invalid boot device is
                 specified.
        :raises: MissingParameterValue if a required parameter is missing
        """

    @abc.abstractmethod
    def get_boot_device(self, task):
        """Get the current boot device for a node.

        Provides the current boot device of the node. Be aware that not
        all drivers support this.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing
        :returns: a dictionary containing:

            :boot_device:
                the boot device, one of :mod:`ironic.common.boot_devices` or
                None if it is unknown.
            :persistent:
                Whether the boot device will persist to all future boots or
                not, None if it is unknown.

        """

    @abc.abstractmethod
    def get_sensors_data(self, task):
        """Get sensors data method.

        :param task: a TaskManager instance.
        :raises: FailedToGetSensorData when getting the sensor data fails.
        :raises: FailedToParseSensorData when parsing sensor data fails.
        :returns: returns a consistent format dict of sensor data grouped by
                  sensor type, which can be processed by Ceilometer.
                  eg,

                  ::

                      {
                        'Sensor Type 1': {
                          'Sensor ID 1': {
                            'Sensor Reading': 'current value',
                            'key1': 'value1',
                            'key2': 'value2'
                          },
                          'Sensor ID 2': {
                            'Sensor Reading': 'current value',
                            'key1': 'value1',
                            'key2': 'value2'
                          }
                        },
                        'Sensor Type 2': {
                          'Sensor ID 3': {
                            'Sensor Reading': 'current value',
                            'key1': 'value1',
                            'key2': 'value2'
                          },
                          'Sensor ID 4': {
                            'Sensor Reading': 'current value',
                            'key1': 'value1',
                            'key2': 'value2'
                          }
                        }
                      }
        """
