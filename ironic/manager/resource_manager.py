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

"""
A NodeManager instance holds the data and drivers for a distinct node.

Each NodeManager instance is a semi-singleton, keyed by the node id, and
contains references to the TaskManagers which called it. When no more
TaskManagers reference a given NodeManager, it is automatically destroyed.

Do not request a NodeManager directly; instead, you should use a
TaskManager to manage the resource in a given context.
"""

from stevedore import dispatch

from ironic.openstack.common import lockutils
from ironic.openstack.common import log

from ironic.common import exception
from ironic.db import api as dbapi

LOG = log.getLogger(__name__)
RESOURCE_MANAGER_SEMAPHORE = "node_resource"


class NodeManager(object):
    """The data model, state, and drivers to manage a Node."""

    _nodes = {}

    _control_factory = dispatch.NameDispatchExtensionManager(
            namespace='ironic.controllers',
            check_func=lambda x: True,
            invoke_on_load=True)
    _deploy_factory = dispatch.NameDispatchExtensionManager(
            namespace='ironic.deployers',
            check_func=lambda x: True,
            invoke_on_load=True)

    def __init__(self, id, t):
        db = dbapi.get_instance()

        self.id = id
        self.task_refs = [t]
        self.node = db.get_node(id)
        self.ports = db.get_ports_by_node(id)

        def _get_instance(ext, *args, **kwds):
            return ext.obj

        # NOTE(deva): Driver loading here may get refactored, depend on:
        #             https://github.com/dreamhost/stevedore/issues/15
        try:
            ref = NodeManager._control_factory.map(
                    [self.node.get('control_driver')], _get_instance)
            self.controller = ref[0]
        except KeyError:
            raise exception.IronicException(_(
                "Failed to load Control driver %s.") %
                        self.node.get('control_driver'))

        try:
            ref = NodeManager._deploy_factory.map(
                    [self.node.get('deploy_driver')], _get_instance)
            self.deployer = ref[0]
        except KeyError:
            raise exception.IronicException(_(
                "Failed to load Deploy driver %s.") %
                        self.node.get('deploy_driver'))

    @classmethod
    @lockutils.synchronized(RESOURCE_MANAGER_SEMAPHORE, 'ironic-')
    def acquire(cls, id, t):
        """Acquire a NodeManager and associate to a TaskManager."""
        n = cls._nodes.get(id)
        if n:
            n.task_refs.append(t)
        else:
            n = cls(id, t)
            cls._nodes[id] = n
        return n

    @classmethod
    @lockutils.synchronized(RESOURCE_MANAGER_SEMAPHORE, 'ironic-')
    def release(cls, id, t):
        """Release a NodeManager previously acquired."""

        n = cls._nodes.get(id)
        if not n:
            raise exception.IronicException(_(
                "Release called on node %s for which no lock "
                "has been acquired.") % id)

        try:
            n.task_refs.remove(t)
        except ValueError:
            raise exception.IronicException(_(
                "Can not release node %s because it was not "
                "reserved by this tracker.") % id)

        # Delete the resource when no TaskManager references it.
        if len(n.task_refs) == 0:
            del(cls._nodes[id])
