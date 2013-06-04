# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Test utils for Ironic Managers."""

import pkg_resources
from stevedore import dispatch

from ironic.manager import resource_manager


def get_mockable_extension_manager(driver, namespace):
    """Get a fake stevedore NameDispatchExtensionManager instance.

    :param namespace: A string representing the namespace over which to
                      search for entrypoints.
    :returns mock_ext_mgr: A NameDispatchExtensionManager that has been
                           faked.
    :returns mock_ext: A real plugin loaded by mock_ext_mgr in the specified
                       namespace.

    """
    entry_point = None
    for ep in list(pkg_resources.iter_entry_points(namespace)):
        s = "%s" % ep
        if driver == s[:s.index(' =')]:
            entry_point = ep
            break

    mock_ext_mgr = dispatch.NameDispatchExtensionManager(
                    'ironic.no-such-namespace',
                    lambda x: True)
    mock_ext = mock_ext_mgr._load_one_plugin(entry_point, True, [], {})
    mock_ext_mgr.extensions = [mock_ext]
    mock_ext_mgr.by_name = dict((e.name, e) for e in [mock_ext])
    return (mock_ext_mgr, mock_ext)


def get_mocked_node_manager(driver="fake"):
    """Mock :class:NodeManager and get a ref to the driver inside..

    To enable testing of NodeManagers, we need to control what plugins
    stevedore loads under the hood. To do that, we fake the plugin loading,
    substituting NodeManager's _driver_factory with an instance of the
    specified driver only, and return a reference directly to that driver
    instance.

    :returns: A driver instance.
    """

    (mgr, ext) = get_mockable_extension_manager(driver, 'ironic.drivers')
    resource_manager.NodeManager._driver_factory = mgr
    return ext.obj
