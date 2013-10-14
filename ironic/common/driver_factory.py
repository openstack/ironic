#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


from ironic.openstack.common import lockutils
from ironic.openstack.common import log
from stevedore import dispatch


LOG = log.getLogger(__name__)

EM_SEMAPHORE = 'extension_manager'


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
        if not cls._extension_manager:
            cls._extension_manager = \
                    dispatch.NameDispatchExtensionManager('ironic.drivers',
                                                          lambda x: True,
                                                          invoke_on_load=True)

    @property
    def names(self):
        """The list of driver names available."""
        return self._extension_manager.names()
