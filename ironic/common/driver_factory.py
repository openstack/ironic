# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import collections

from oslo_concurrency import lockutils
from oslo_log import log
from stevedore import dispatch

from ironic.common import exception
from ironic.common.i18n import _LI, _LW
from ironic.conf import CONF
from ironic.drivers import base as driver_base
from ironic.drivers import fake_hardware
from ironic.drivers import hardware_type


LOG = log.getLogger(__name__)

EM_SEMAPHORE = 'extension_manager'


def build_driver_for_task(task, driver_name=None):
    """Builds a composable driver for a given task.

    Starts with a `BareDriver` object, and attaches implementations of the
    various driver interfaces to it. For classic drivers these all come from
    the monolithic driver singleton, for hardware types - from separate
    driver factories and are configurable via the database.

    :param task: The task containing the node to build a driver for.
    :param driver_name: The name of the classic driver or hardware type to use
                        as a base, if different than task.node.driver.
    :returns: A driver object for the task.
    :raises: DriverNotFound if node.driver could not be found in either
             "ironic.drivers" or "ironic.hardware.types" namespaces.
    :raises: InterfaceNotFoundInEntrypoint if some node interfaces are set
             to invalid or unsupported values.
    :raises: IncompatibleInterface if driver is a hardware type and
             the requested implementation is not compatible with it.
    """
    node = task.node
    driver_name = driver_name or node.driver

    driver_or_hw_type = get_driver_or_hardware_type(driver_name)
    check_and_update_node_interfaces(node, driver_or_hw_type=driver_or_hw_type)

    bare_driver = driver_base.BareDriver()
    _attach_interfaces_to_driver(bare_driver, node, driver_or_hw_type)

    return bare_driver


def _attach_interfaces_to_driver(bare_driver, node, driver_or_hw_type):
    """Attach interface implementations to a bare driver object.

    For classic drivers, copies implementations from the singleton driver
    object, then attaches the dynamic interfaces (network and storage
    interfaces for classic drivers, all interfaces for dynamic drivers
    made of hardware types).

    For hardware types, load all interface implementations dynamically.

    :param bare_driver: BareDriver instance to attach interfaces to
    :param node: Node object
    :param driver_or_hw_type: classic driver or hardware type instance
    :raises: InterfaceNotFoundInEntrypoint if the entry point was not found.
    :raises: IncompatibleInterface if driver is a hardware type and
             the requested implementation is not compatible with it.
    """
    if isinstance(driver_or_hw_type, hardware_type.AbstractHardwareType):
        # For hardware types all interfaces are dynamic
        dynamic_interfaces = _INTERFACE_LOADERS
    else:
        # Copy implementations from the classic driver singleton
        for iface in driver_or_hw_type.all_interfaces:
            impl = getattr(driver_or_hw_type, iface, None)
            setattr(bare_driver, iface, impl)

        # NOTE(TheJulia): This list of interfaces to be applied
        # to classic drivers, thus requiring separate treatment.
        dynamic_interfaces = ['network', 'storage']

    for iface in dynamic_interfaces:
        impl_name = getattr(node, '%s_interface' % iface)
        impl = _get_interface(driver_or_hw_type, iface, impl_name)
        setattr(bare_driver, iface, impl)


def _get_interface(driver_or_hw_type, interface_type, interface_name):
    """Get interface implementation instance.

    For hardware types also validates compatibility.

    :param driver_or_hw_type: a hardware type or classic driver instance.
    :param interface_type: name of the interface type (e.g. 'boot').
    :param interface_name: name of the interface implementation from an
                           appropriate entry point
                           (ironic.hardware.interfaces.<interface type>).
    :returns: instance of the requested interface implementation.
    :raises: InterfaceNotFoundInEntrypoint if the entry point was not found.
    :raises: IncompatibleInterface if driver_or_hw_type is a hardware type and
             the requested implementation is not compatible with it.
    """
    factory = _INTERFACE_LOADERS[interface_type]()
    try:
        impl_instance = factory.get_driver(interface_name)
    except KeyError:
        raise exception.InterfaceNotFoundInEntrypoint(
            iface=interface_name,
            entrypoint=factory._entrypoint_name,
            valid=factory.names)

    if not isinstance(driver_or_hw_type, hardware_type.AbstractHardwareType):
        # NOTE(dtantsur): classic drivers do not have notion of compatibility
        return impl_instance

    if isinstance(driver_or_hw_type, fake_hardware.FakeHardware):
        # NOTE(dtantsur): special-case fake hardware type to allow testing with
        # any combinations of interface implementations.
        return impl_instance

    supported_impls = getattr(driver_or_hw_type,
                              'supported_%s_interfaces' % interface_type)
    if type(impl_instance) not in supported_impls:
        raise exception.IncompatibleInterface(
            interface_type=interface_type, interface_impl=impl_instance,
            hardware_type=driver_or_hw_type.__class__.__name__)

    return impl_instance


def _default_interface(hardware_type, interface_type, factory):
    """Calculate and return the default interface implementation.

    Finds the first implementation that is supported by the hardware type
    and is enabled in the configuration.

    :param hardware_type: hardware type instance.
    :param interface_type: type of the interface (e.g. 'boot').
    :param factory: interface factory class to use for loading implementations.
    :returns: an entrypoint name of the calculated default implementation
              or None if no default implementation can be found.
    :raises: InterfaceNotFoundInEntrypoint if the entry point was not found.
    """
    supported = getattr(hardware_type,
                        'supported_%s_interfaces' % interface_type)
    # Mapping of classes to entry points
    enabled = {obj.__class__: name for (name, obj) in factory().items()}

    # Order of the supported list matters
    for impl_class in supported:
        try:
            return enabled[impl_class]
        except KeyError:
            pass


def check_and_update_node_interfaces(node, driver_or_hw_type=None):
    """Ensure that node interfaces (e.g. for creation or updating) are valid.

    Updates (but doesn't save to the database) hardware interfaces with
    calculated defaults, if they are not provided.

    This function is run on node updating and creation, as well as each time
    a driver instance is built for a node.

    :param node: node object to check and potentially update
    :param driver_or_hw_type: classic driver or hardware type instance object;
                              will be detected from node.driver if missing
    :returns: True if any changes were made to the node, otherwise False
    :raises: InterfaceNotFoundInEntrypoint on validation failure
    :raises: NoValidDefaultForInterface if the default value cannot be
             calculated and is not provided in the configuration
    :raises: DriverNotFound if the node's driver or hardware type is not found
    """
    if driver_or_hw_type is None:
        driver_or_hw_type = get_driver_or_hardware_type(node.driver)
    is_hardware_type = isinstance(driver_or_hw_type,
                                  hardware_type.AbstractHardwareType)

    # Explicit interface defaults
    additional_defaults = {
        'network': 'flat' if CONF.dhcp.dhcp_provider == 'neutron' else 'noop',
        'storage': 'noop'
    }

    if is_hardware_type:
        factories = _INTERFACE_LOADERS
    else:
        # Only network and storage interfaces are dynamic for classic drivers
        factories = {'network': _INTERFACE_LOADERS['network'],
                     'storage': _INTERFACE_LOADERS['storage']}

    # Result - whether the node object was modified
    result = False

    # Walk through all dynamic interfaces and check/update them
    for iface, factory in factories.items():
        field_name = '%s_interface' % iface
        # NOTE(dtantsur): objects raise NotImplementedError on accessing fields
        # that are known, but missing from an object. Thus, we cannot just use
        # getattr(node, field_name, None) here.
        if field_name in node:
            impl_name = getattr(node, field_name)
            if impl_name is not None:
                # Check that the provided value is correct for this type
                _get_interface(driver_or_hw_type, iface, impl_name)
                # Not changing the result, proceeding with the next interface
                continue

        # The fallback default from the configuration
        impl_name = getattr(CONF, 'default_%s_interface' % iface)
        if impl_name is None:
            impl_name = additional_defaults.get(iface)

        if impl_name is not None:
            # Check that the default is correct for this type
            _get_interface(driver_or_hw_type, iface, impl_name)
        elif is_hardware_type:
            impl_name = _default_interface(driver_or_hw_type, iface, factory)

        if impl_name is None:
            raise exception.NoValidDefaultForInterface(
                interface_type=iface, node=node.uuid, driver=node.driver)

        # Set the calculated default and set result to True
        setattr(node, field_name, impl_name)
        result = True

    return result


def get_driver_or_hardware_type(name):
    """Get driver or hardware type by its entry point name.

    First, checks the hardware types namespace, then checks the classic
    drivers namespace. The first object found is returned.

    :param name: entry point name.
    :returns: An instance of a hardware type or a classic driver.
    :raises: DriverNotFound if neither hardware type nor classic driver found.
    """
    try:
        return get_hardware_type(name)
    except exception.DriverNotFound:
        return get_driver(name)


def get_hardware_type(hardware_type):
    """Get a hardware type instance by name.

    :param hardware_type: the name of the hardware type to find
    :returns: An instance of ironic.drivers.hardware_type.AbstractHardwareType
    :raises: DriverNotFound if requested hardware type cannot be found
    """
    try:
        return HardwareTypesFactory().get_driver(hardware_type)
    except KeyError:
        raise exception.DriverNotFound(driver_name=hardware_type)


# TODO(dtantsur): rename to get_classic_driver
def get_driver(driver_name):
    """Simple method to get a ref to an instance of a driver.

    Driver loading is handled by the DriverFactory class. This method
    conveniently wraps that class and returns the actual driver object.

    :param driver_name: the name of the driver class to load
    :returns: An instance of a class which implements
              ironic.drivers.base.BaseDriver
    :raises: DriverNotFound if the requested driver_name could not be
             found in the "ironic.drivers" namespace.

    """

    try:
        factory = DriverFactory()
        return factory.get_driver(driver_name)
    except KeyError:
        raise exception.DriverNotFound(driver_name=driver_name)


def drivers():
    """Get all drivers as a dict name -> driver object."""
    factory = DriverFactory()
    # NOTE(jroll) I don't think this needs to be ordered, but
    # ConductorManager.init_host seems to depend on this behavior (or at
    # least the unit tests for it do), and it can't hurt much to keep it
    # that way.
    return collections.OrderedDict((name, factory[name].obj)
                                   for name in factory.names)


class BaseDriverFactory(object):
    """Discover, load and manage the drivers available.

    This is subclassed to load both main drivers and extra interfaces.
    """

    # NOTE(deva): loading the _extension_manager as a class member will break
    #             stevedore when it loads a driver, because the driver will
    #             import this file (and thus instantiate another factory).
    #             Instead, we instantiate a NameDispatchExtensionManager only
    #             once, the first time DriverFactory.__init__ is called.
    _extension_manager = None

    # Entrypoint name containing the list of all available drivers/interfaces
    _entrypoint_name = None
    # Name of the [DEFAULT] section config option containing a list of enabled
    # drivers/interfaces
    _enabled_driver_list_config_option = ''
    # This field will contain the list of the enabled drivers/interfaces names
    # without duplicates
    _enabled_driver_list = None

    def __init__(self):
        if not self.__class__._extension_manager:
            self.__class__._init_extension_manager()

    def __getitem__(self, name):
        return self._extension_manager[name]

    def get_driver(self, name):
        return self[name].obj

    # NOTE(deva): Use lockutils to avoid a potential race in eventlet
    #             that might try to create two driver factories.
    @classmethod
    @lockutils.synchronized(EM_SEMAPHORE)
    def _init_extension_manager(cls):
        # NOTE(deva): In case multiple greenthreads queue up on this lock
        #             before _extension_manager is initialized, prevent
        #             creation of multiple NameDispatchExtensionManagers.
        if cls._extension_manager:
            return
        enabled_drivers = getattr(CONF, cls._enabled_driver_list_config_option,
                                  [])

        # Check for duplicated driver entries and warn the operator
        # about them
        counter = collections.Counter(enabled_drivers).items()
        duplicated_drivers = []
        cls._enabled_driver_list = []
        for item, cnt in counter:
            if not item:
                LOG.warning(
                    _LW('An empty driver was specified in the "%s" '
                        'configuration option and will be ignored. Please '
                        'fix your ironic.conf file to avoid this warning '
                        'message.'), cls._enabled_driver_list_config_option)
                continue
            if cnt > 1:
                duplicated_drivers.append(item)
            cls._enabled_driver_list.append(item)
        if duplicated_drivers:
            LOG.warning(_LW('The driver(s) "%s" is/are duplicated in the '
                            'list of enabled_drivers. Please check your '
                            'configuration file.'),
                        ', '.join(duplicated_drivers))

        # NOTE(deva): Drivers raise "DriverLoadError" if they are unable to be
        #             loaded, eg. due to missing external dependencies.
        #             We capture that exception, and, only if it is for an
        #             enabled driver, raise it from here. If enabled driver
        #             raises other exception type, it is wrapped in
        #             "DriverLoadError", providing the name of the driver that
        #             caused it, and raised. If the exception is for a
        #             non-enabled driver, we suppress it.
        def _catch_driver_not_found(mgr, ep, exc):
            # NOTE(deva): stevedore loads plugins *before* evaluating
            #             _check_func, so we need to check here, too.
            if ep.name in cls._enabled_driver_list:
                if not isinstance(exc, exception.DriverLoadError):
                    raise exception.DriverLoadError(driver=ep.name, reason=exc)
                raise exc

        def _check_func(ext):
            return ext.name in cls._enabled_driver_list

        cls._extension_manager = (
            dispatch.NameDispatchExtensionManager(
                cls._entrypoint_name,
                _check_func,
                invoke_on_load=True,
                on_load_failure_callback=_catch_driver_not_found,
                propagate_map_exceptions=True))

        # NOTE(deva): if we were unable to load any configured driver, perhaps
        #             because it is not present on the system, raise an error.
        if (sorted(cls._enabled_driver_list) !=
                sorted(cls._extension_manager.names())):
            found = cls._extension_manager.names()
            names = [n for n in cls._enabled_driver_list if n not in found]
            # just in case more than one could not be found ...
            names = ', '.join(names)
            raise exception.DriverNotFoundInEntrypoint(
                names=names, entrypoint=cls._entrypoint_name)

        # warn for any untested/unsupported/deprecated drivers or interfaces
        cls._extension_manager.map(cls._extension_manager.names(),
                                   _warn_if_unsupported)

        LOG.info(_LI("Loaded the following drivers: %s"),
                 cls._extension_manager.names())

    @property
    def names(self):
        """The list of driver names available."""
        return self._extension_manager.names()

    def items(self):
        """Iterator over pairs (name, instance)."""
        return ((ext.name, ext.obj) for ext in self._extension_manager)


def _warn_if_unsupported(ext):
    if not ext.obj.supported:
        LOG.warning(_LW('Driver "%s" is UNSUPPORTED. It has been deprecated '
                        'and may be removed in a future release.'), ext.name)


class DriverFactory(BaseDriverFactory):
    _entrypoint_name = 'ironic.drivers'
    _enabled_driver_list_config_option = 'enabled_drivers'


class HardwareTypesFactory(BaseDriverFactory):
    _entrypoint_name = 'ironic.hardware.types'
    _enabled_driver_list_config_option = 'enabled_hardware_types'


_INTERFACE_LOADERS = {
    name: type('%sInterfaceFactory' % name.capitalize(),
               (BaseDriverFactory,),
               {'_entrypoint_name': 'ironic.hardware.interfaces.%s' % name,
                '_enabled_driver_list_config_option':
                'enabled_%s_interfaces' % name})
    for name in driver_base.ALL_INTERFACES
}


# TODO(dtantsur): This factory is still used explicitly in many places,
# refactor them later to use _INTERFACE_LOADERS.
NetworkInterfaceFactory = _INTERFACE_LOADERS['network']
StorageInterfaceFactory = _INTERFACE_LOADERS['storage']
