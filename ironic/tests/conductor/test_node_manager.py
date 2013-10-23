# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

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

import contextlib
import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import resource_manager
from ironic.tests import base


class NodeManagerTestCase(base.TestCase):

    def setUp(self):
        super(NodeManagerTestCase, self).setUp()
        self.existing_driver_name = 'some existing driver'
        self.existing_driver_name_2 = 'some other existing driver'
        self.non_existing_driver_name = "non existing driver"
        self.existing_driver = mock.MagicMock()
        self.existing_driver_2 = mock.MagicMock()
        self.test_id = 1
        self.test_task = mock.MagicMock()
        self.test_node = {'driver': self.existing_driver_name, }
        self.test_ports = mock.MagicMock()
        self.driver_factory = {
            self.existing_driver_name: self.existing_driver,
            self.existing_driver_name_2: self.existing_driver_2, }
        db_keys = {
            "get_node.return_value": self.test_node,
            "get_ports_by_node.return_value": self.test_ports, }
        self.dbapi = mock.MagicMock()
        self.dbapi.get_instance.return_value = mock.MagicMock(**db_keys)

    def _fake_init(*args, **kwargs):
        return None

    def test_node_manager_init_id(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch("ironic.conductor.resource_manager.dbapi",
                           self.dbapi)):
            new_nm = NodeManager(id=self.test_id, t=self.test_task)
            self.assertEqual(new_nm.id, self.test_id)

    def test_node_manager_init_task(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch("ironic.conductor.resource_manager.dbapi",
                           self.dbapi)
                ):
            new_nm = NodeManager(id=self.test_id, t=self.test_task)
            self.assertEqual(new_nm.task_refs, [self.test_task])

    def test_node_manager_init_node(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch("ironic.conductor.resource_manager.dbapi",
                           self.dbapi)
                ):
            new_nm = NodeManager(id=self.test_id, t=self.test_task)
            self.assertEqual(new_nm.node, self.test_node)

    def test_node_manager_init_ports(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch("ironic.conductor.resource_manager.dbapi",
                           self.dbapi)
                ):
            new_nm = NodeManager(id=self.test_id, t=self.test_task)
            self.assertEqual(new_nm.ports, self.test_ports)

    def test_node_manager_init_driver(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch("ironic.conductor.resource_manager.dbapi",
                           self.dbapi)
                ):
            new_nm = NodeManager(id=self.test_id, t=self.test_task)
            self.assertEqual(new_nm.driver, self.existing_driver.obj)

    def test_node_manager_init_new_driver(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch("ironic.conductor.resource_manager.dbapi",
                           self.dbapi)
                ):
            new_nm = NodeManager(id=self.test_id,
                                 t=self.test_task,
                                 driver_name=self.existing_driver_name_2)
            self.assertEqual(new_nm.driver, self.existing_driver_2.obj)

    def test_load_existing_driver(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch.object(NodeManager,
                                  '__init__',
                                  new=self._fake_init)
                ):
            node_manager = NodeManager()
            self.assertEqual(node_manager.load_driver(
                                self.existing_driver_name
                                ),
                            self.existing_driver.obj
                            )

    def test_load_non_existing_driver(self):
        NodeManager = resource_manager.NodeManager
        DriverFactory = driver_factory.DriverFactory
        with contextlib.nested(
                mock.patch.object(DriverFactory,
                                  '_extension_manager',
                                  new=self.driver_factory),
                mock.patch.object(NodeManager,
                                  '__init__',
                                  new=self._fake_init)
                ):
            node_manager = NodeManager()
            self.assertRaises(exception.DriverNotFound,
                              node_manager.load_driver,
                              self.non_existing_driver_name)
