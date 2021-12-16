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
from stevedore import named

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF
from ironic.drivers import base as driver_base


LOG = log.getLogger(__name__)

EM_SEMAPHORE = 'extension_manager'


def build_driver_for_task(task):
    """Builds a composable driver for a given task.

    Starts with a `BareDriver` object, and attaches implementations of the
    various driver interfaces to it. They come from separate
    driver factories and are configurable via the database.

    :param task: The task containing the node to build a driver for.
    :returns: A driver object for the task.
    :raises: DriverNotFound if node.driver could not be found in the
             "ironic.hardware.types" namespaces.
    :raises: InterfaceNotFoundInEntrypoint if some node interfaces are set
             to invalid or unsupported values.
    :raises: IncompatibleInterface the requested implementation is not
             compatible with it with the hardware type.
    """
    node = task.node

    hw_type = get_hardware_type(node.driver)
    check_and_update_node_interfaces(node, hw_type=hw_type)

    bare_driver = driver_base.BareDriver()
    _attach_interfaces_to_driver(bare_driver, node, hw_type)

    return bare_driver


def _attach_interfaces_to_driver(bare_driver, node, hw_type):
    """Attach interface implementations to a bare driver object.

    :param bare_driver: BareDriver instance to attach interfaces to
    :param node: Node object
    :param hw_type: hardware type instance
    :raises: InterfaceNotFoundInEntrypoint if the entry point was not found.
    :raises: IncompatibleInterface if driver is a hardware type and
             the requested implementation is not compatible with it.
    """
    for iface in _INTERFACE_LOADERS:
        impl_name = node.get_interface(iface)
        impl = get_interface(hw_type, iface, impl_name)
        setattr(bare_driver, iface, impl)


def get_interface(hw_type, interface_type, interface_name):
    """Get interface implementation instance.

    For hardware types also validates compatibility.

    :param hw_type: a hardware type instance.
    :param interface_type: name of the interface type (e.g. 'boot').
    :param interface_name: name of the interface implementation from an
                           appropriate entry point
                           (ironic.hardware.interfaces.<interface type>).
    :returns: instance of the requested interface implementation.
    :raises: InterfaceNotFoundInEntrypoint if the entry point was not found.
    :raises: IncompatibleInterface if hw_type is a hardware type and
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

    from ironic.drivers import fake_hardware  # avoid circular import
    if isinstance(hw_type, fake_hardware.FakeHardware):
        # NOTE(dtantsur): special-case fake hardware type to allow testing with
        # any combinations of interface implementations.
        return impl_instance

    supported_impls = getattr(hw_type,
                              'supported_%s_interfaces' % interface_type)
    if type(impl_instance) not in supported_impls:
        raise exception.IncompatibleInterface(
            interface_type=interface_type, interface_impl=impl_instance,
            hardware_type=hw_type.__class__.__name__)

    return impl_instance


def default_interface(hw_type, interface_type,
                      driver_name=None, node=None):
    """Calculate and return the default interface implementation.

    Finds the first implementation that is supported by the hardware type
    and is enabled in the configuration.

    :param hw_type: hardware type instance object.
    :param interface_type: type of the interface (e.g. 'boot').
    :param driver_name: entrypoint name of the hw_type object. Is
                        used for exception message.
    :param node: the identifier of a node. If specified, is used for exception
                 message.
    :returns: an entrypoint name of the calculated default implementation.
    :raises: InterfaceNotFoundInEntrypoint if the entry point was not found.
    :raises: NoValidDefaultForInterface if no default interface can be found.
    """

    factory = _INTERFACE_LOADERS[interface_type]

    # The fallback default from the configuration
    impl_name = getattr(CONF, 'default_%s_interface' % interface_type)

    if impl_name is not None:
        try:
            # Check that the default is correct for this type
            get_interface(hw_type, interface_type, impl_name)
        except exception.IncompatibleInterface:
            node_info = ""
            if node is not None:
                node_info = _(' node %s with') % node
            raise exception.NoValidDefaultForInterface(
                interface_type=interface_type, driver=driver_name,
                node_info=node_info)

    else:
        supported = getattr(hw_type,
                            'supported_%s_interfaces' % interface_type)
        # Mapping of classes to entry points
        enabled = {obj.__class__: name for (name, obj) in factory().items()}

        # Order of the supported list matters
        for impl_class in supported:
            try:
                impl_name = enabled[impl_class]
                break
            except KeyError:
                continue

    if impl_name is None:
        # NOTE(rloo). No i18n on driver_type_str because translating substrings
        #             on their own may cause the final string to look odd.
        driver_name = driver_name or hw_type.__class__.__name__
        node_info = ""
        if node is not None:
            node_info = _(' node %s with') % node
        raise exception.NoValidDefaultForInterface(
            interface_type=interface_type, driver=driver_name,
            node_info=node_info)

    return impl_name


def check_and_update_node_interfaces(node, hw_type=None):
    """Ensure that node interfaces (e.g. for creation or updating) are valid.

    Updates (but doesn't save to the database) hardware interfaces with
    calculated defaults, if they are not provided.

    This function is run on node updating and creation, as well as each time
    a driver instance is built for a node.

    :param node: node object to check and potentially update
    :param hw_type: hardware type instance object; will be detected from
                    node.driver if missing
    :returns: True if any changes were made to the node, otherwise False
    :raises: InterfaceNotFoundInEntrypoint on validation failure
    :raises: NoValidDefaultForInterface if the default value cannot be
             calculated and is not provided in the configuration
    :raises: DriverNotFound if the node's hardware type is not found
    """
    if hw_type is None:
        hw_type = get_hardware_type(node.driver)

    factories = list(_INTERFACE_LOADERS)

    # Result - whether the node object was modified
    result = False

    # Walk through all dynamic interfaces and check/update them
    for iface in factories:
        field_name = '%s_interface' % iface
        # NOTE(dtantsur): objects raise NotImplementedError on accessing fields
        # that are known, but missing from an object. Thus, we cannot just use
        # getattr(node, field_name, None) here.
        set_default = True
        if 'instance_info' in node and field_name in node.instance_info:
            impl_name = node.instance_info.get(field_name)
            if impl_name is not None:
                # Check that the provided value is correct for this type
                get_interface(hw_type, iface, impl_name)
                set_default = False

        if field_name in node:
            impl_name = getattr(node, field_name)
            if impl_name is not None:
                # Check that the provided value is correct for this type
                get_interface(hw_type, iface, impl_name)
                set_default = False

        if set_default:
            impl_name = default_interface(hw_type, iface,
                                          driver_name=node.driver,
                                          node=node.uuid)

            # Set the calculated default and set result to True
            setattr(node, field_name, impl_name)
            result = True

    return result


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


def _get_all_drivers(factory):
    """Get all drivers for `factory` as a dict name -> driver object."""
    # NOTE(jroll) I don't think this needs to be ordered, but
    # ConductorManager.init_host seems to depend on this behavior (or at
    # least the unit tests for it do), and it can't hurt much to keep it
    # that way.
    return collections.OrderedDict((name, factory[name].obj)
                                   for name in factory.names)


def hardware_types():
    """Get all hardware types.

    :returns: Dictionary mapping hardware type name to hardware type object.
    """
    return _get_all_drivers(HardwareTypesFactory())


def interfaces(interface_type):
    """Get all interfaces for a given interface type.

    :param interface_type: String, type of interface to fetch for.
    :returns: Dictionary mapping interface name to interface object.
    """
    return _get_all_drivers(_INTERFACE_LOADERS[interface_type]())


def all_interfaces():
    """Get all interfaces for all interface types.

    :returns: Dictionary mapping interface type to dictionary mapping
        interface name to interface object.
    """
    return {iface: interfaces(iface) for iface in _INTERFACE_LOADERS}


def enabled_supported_interfaces(hardware_type):
    """Get usable interfaces for a given hardware type.

    For a given hardware type, find the intersection of enabled and supported
    interfaces for each interface type. This is the set of interfaces that are
    usable for this hardware type.

    :param hardware_type: The hardware type object to search.
    :returns: a dict mapping interface types to a list of enabled and supported
              interface names.
    """
    mapping = dict()
    for interface_type in driver_base.ALL_INTERFACES:
        supported = set()
        supported_ifaces = getattr(hardware_type,
                                   'supported_%s_interfaces' % interface_type)
        for name, iface in interfaces(interface_type).items():
            if iface.__class__ in supported_ifaces:
                supported.add(name)
        mapping[interface_type] = supported
    return mapping


class BaseDriverFactory(object):
    """Discover, load and manage the drivers available.

    This is subclassed to load both main drivers and extra interfaces.
    """

    # NOTE(tenbrae): loading the _extension_manager as a class member will
    #             break stevedore when it loads a driver, because the driver
    #             will import this file (and thus instantiate another factory).
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
    # Template for logging loaded drivers
    _logging_template = "Loaded the following drivers: %s"

    def __init__(self):
        if not self.__class__._extension_manager:
            self.__class__._init_extension_manager()

    def __getitem__(self, name):
        return self._extension_manager[name]

    def get_driver(self, name):
        return self[name].obj

    # NOTE(tenbrae): Drivers raise "DriverLoadError" if they are unable to
    #             be loaded, eg. due to missing external dependencies.
    #             We capture that exception, and, only if it is for an
    #             enabled driver, raise it from here. If enabled driver
    #             raises other exception type, it is wrapped in
    #             "DriverLoadError", providing the name of the driver that
    #             caused it, and raised. If the exception is for a
    #             non-enabled driver, we suppress it.
    @classmethod
    def _catch_driver_not_found(cls, mgr, ep, exc):
        # NOTE(tenbrae): stevedore loads plugins *before* evaluating
        #             _check_func, so we need to check here, too.
        if ep.name in cls._enabled_driver_list:
            if not isinstance(exc, exception.DriverLoadError):
                raise exception.DriverLoadError(driver=ep.name, reason=exc)
            raise exc

    @classmethod
    def _missing_callback(cls, names):
        names = ', '.join(names)
        raise exception.DriverNotFoundInEntrypoint(
            names=names, entrypoint=cls._entrypoint_name)

    @classmethod
    def _set_enabled_drivers(cls):
        enabled_drivers = getattr(CONF, cls._enabled_driver_list_config_option,
                                  [])

        # Check for duplicated driver entries and warn the operator
        # about them
        counter = collections.Counter(enabled_drivers).items()
        duplicated_drivers = []
        cls._enabled_driver_list = []
        for item, cnt in counter:
            if not item:
                LOG.warning('An empty driver was specified in the "%s" '
                            'configuration option and will be ignored. Please '
                            'fix your ironic.conf file to avoid this warning '
                            'message.', cls._enabled_driver_list_config_option)
                continue
            if cnt > 1:
                duplicated_drivers.append(item)
            cls._enabled_driver_list.append(item)
        if duplicated_drivers:
            LOG.warning('The driver(s) "%s" is/are duplicated in the '
                        'list of enabled_drivers. Please check your '
                        'configuration file.',
                        ', '.join(duplicated_drivers))

    @classmethod
    def _init_extension_manager(cls):
        # NOTE(tenbrae): Use lockutils to avoid a potential race in eventlet
        #             that might try to create two driver factories.
        with lockutils.lock(cls._entrypoint_name, do_log=False):
            # NOTE(tenbrae): In case multiple greenthreads queue up on this
            # lock before _extension_manager is initialized, prevent
            # creation of multiple NameDispatchExtensionManagers.
            if cls._extension_manager:
                return

            cls._set_enabled_drivers()

            cls._extension_manager = (
                named.NamedExtensionManager(
                    cls._entrypoint_name,
                    cls._enabled_driver_list,
                    invoke_on_load=True,
                    on_load_failure_callback=cls._catch_driver_not_found,
                    propagate_map_exceptions=True,
                    on_missing_entrypoints_callback=cls._missing_callback))

            # warn for any untested/unsupported/deprecated drivers or
            # interfaces
            if cls._enabled_driver_list:
                cls._extension_manager.map(_warn_if_unsupported)

        LOG.info(cls._logging_template, cls._extension_manager.names())

    @property
    def names(self):
        """The list of driver names available."""
        return self._extension_manager.names()

    def items(self):
        """Iterator over pairs (name, instance)."""
        return ((ext.name, ext.obj) for ext in self._extension_manager)


def _warn_if_unsupported(ext):
    if not ext.obj.supported:
        LOG.warning('Driver "%s" is UNSUPPORTED. It has been deprecated '
                    'and may be removed in a future release.', ext.name)


class HardwareTypesFactory(BaseDriverFactory):
    _entrypoint_name = 'ironic.hardware.types'
    _enabled_driver_list_config_option = 'enabled_hardware_types'
    _logging_template = "Loaded the following hardware types: %s"


_INTERFACE_LOADERS = {
    name: type('%sInterfaceFactory' % name.capitalize(),
               (BaseDriverFactory,),
               {'_entrypoint_name': 'ironic.hardware.interfaces.%s' % name,
                '_enabled_driver_list_config_option':
                'enabled_%s_interfaces' % name,
                '_logging_template':
                "Loaded the following %s interfaces: %%s" % name})
    for name in driver_base.ALL_INTERFACES
}


# TODO(dtantsur): This factory is still used explicitly in many places,
# refactor them later to use _INTERFACE_LOADERS.
NetworkInterfaceFactory = _INTERFACE_LOADERS['network']
StorageInterfaceFactory = _INTERFACE_LOADERS['storage']
