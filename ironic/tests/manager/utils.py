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
    for entry_point in list(pkg_resources.iter_entry_points(namespace)):
        s = "%s" % entry_point
        if s.startswith(driver):
            break
    mock_ext_mgr = dispatch.NameDispatchExtensionManager(
                    'ironic.no-such-namespace',
                    lambda x: True)
    mock_ext = mock_ext_mgr._load_one_plugin(entry_point, True, [], {})
    mock_ext_mgr.extensions = [mock_ext]
    mock_ext_mgr.by_name = dict((e.name, e) for e in [mock_ext])
    return (mock_ext_mgr, mock_ext)


def get_mocked_node_manager(control_driver="fake", deploy_driver="fake"):
    """Get a mockable :class:NodeManager instance.

    To enable testing of NodeManagers, we need to control what plugins
    stevedore loads under the hood. To do that, we fake the plugin loading,
    substitute NodeManager's _control_factory and _deploy_factory with the
    fake managers, and then return handles to the actual objects.

    :returns: A tuple of (control, deploy) drivers.
    """

    (mgr, ext) = get_mockable_extension_manager(control_driver,
                                                'ironic.controllers')
    resource_manager.NodeManager._control_factory = mgr
    c = ext.obj

    (mgr, ext) = get_mockable_extension_manager(deploy_driver,
                                                'ironic.deployers')
    resource_manager.NodeManager._deploy_factory = mgr
    d = ext.obj

    return (c, d)
