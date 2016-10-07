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
from oslo_config import cfg
from oslo_log import log
from stevedore import dispatch

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.drivers import base as driver_base


LOG = log.getLogger(__name__)

driver_opts = [
    cfg.ListOpt('enabled_drivers',
                default=['pxe_ipmitool'],
                help=_('Specify the list of drivers to load during service '
                       'initialization. Missing drivers, or drivers which '
                       'fail to initialize, will prevent the conductor '
                       'service from starting. The option default is a '
                       'recommended set of production-oriented drivers. A '
                       'complete list of drivers present on your system may '
                       'be found by enumerating the "ironic.drivers" '
                       'entrypoint. An example may be found in the '
                       'developer documentation online.')),
]

CONF = cfg.CONF
CONF.register_opts(driver_opts)

EM_SEMAPHORE = 'extension_manager'


def build_driver_for_task(task, driver_name=None):
    """Builds a composable driver for a given task.

    Starts with a `BareDriver` object, and attaches implementations of the
    various driver interfaces to it. Currently these all come from the
    monolithic driver singleton, but later will come from separate
    driver factories and configurable via the database.

    :param task: The task containing the node to build a driver for.
    :param driver_name: The name of the monolithic driver to use as a base,
                        if different than task.node.driver.
    :returns: A driver object for the task.
    :raises: DriverNotFound if node.driver could not be
             found in the "ironic.drivers" namespace.
    """
    node = task.node
    driver = driver_base.BareDriver()
    _attach_interfaces_to_driver(driver, node, driver_name=driver_name)
    return driver


def _attach_interfaces_to_driver(driver, node, driver_name=None):
    driver_singleton = get_driver(driver_name or node.driver)
    for iface in driver_singleton.all_interfaces:
        impl = getattr(driver_singleton, iface, None)
        setattr(driver, iface, impl)


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
        return factory[driver_name].obj
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


class DriverFactory(object):
    """Discover, load and manage the drivers available."""

    # NOTE(deva): loading the _extension_manager as a class member will break
    #             stevedore when it loads a driver, because the driver will
    #             import this file (and thus instantiate another factory).
    #             Instead, we instantiate a NameDispatchExtensionManager only
    #             once, the first time DriverFactory.__init__ is called.
    _extension_manager = None

    def __init__(self):
        if not DriverFactory._extension_manager:
            DriverFactory._init_extension_manager()

    def __getitem__(self, name):
        return self._extension_manager[name]

    # NOTE(deva): Use lockutils to avoid a potential race in eventlet
    #             that might try to create two driver factories.
    @classmethod
    @lockutils.synchronized(EM_SEMAPHORE, 'ironic-')
    def _init_extension_manager(cls):
        # NOTE(deva): In case multiple greenthreads queue up on this lock
        #             before _extension_manager is initialized, prevent
        #             creation of multiple NameDispatchExtensionManagers.
        if cls._extension_manager:
            return

        # Check for duplicated driver entries and warn the operator
        # about them
        counter = collections.Counter(CONF.enabled_drivers).items()
        duplicated_drivers = list(dup for (dup, i) in counter if i > 1)
        if duplicated_drivers:
            LOG.warning(_LW('The driver(s) "%s" is/are duplicated in the '
                            'list of enabled_drivers. Please check your '
                            'configuration file.'),
                        ', '.join(duplicated_drivers))

        enabled_drivers = set(CONF.enabled_drivers)

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
            if ep.name in enabled_drivers:
                if not isinstance(exc, exception.DriverLoadError):
                    raise exception.DriverLoadError(driver=ep.name, reason=exc)
                raise exc

        def _check_func(ext):
            return ext.name in enabled_drivers

        cls._extension_manager = (
            dispatch.NameDispatchExtensionManager(
                'ironic.drivers',
                _check_func,
                invoke_on_load=True,
                on_load_failure_callback=_catch_driver_not_found))

        # NOTE(deva): if we were unable to load any configured driver, perhaps
        #             because it is not present on the system, raise an error.
        if (sorted(enabled_drivers) !=
                sorted(cls._extension_manager.names())):
            found = cls._extension_manager.names()
            names = [n for n in enabled_drivers if n not in found]
            # just in case more than one could not be found ...
            names = ', '.join(names)
            raise exception.DriverNotFound(driver_name=names)

        LOG.info(_LI("Loaded the following drivers: %s"),
                 cls._extension_manager.names())

    @property
    def names(self):
        """The list of driver names available."""
        return self._extension_manager.names()
