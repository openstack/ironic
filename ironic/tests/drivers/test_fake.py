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

"""Test class for Fake driver."""

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as db_api
from ironic.drivers import base as driver_base
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import utils as db_utils


class FakeDriverTestCase(base.TestCase):

    def setUp(self):
        super(FakeDriverTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager(driver='fake')
        self.node = db_utils.get_test_node()
        self.dbapi.create_node(self.node)

    def test_driver_interfaces(self):
        # fake driver implements only 3 out of 5 interfaces
        self.assertIsInstance(self.driver.power, driver_base.PowerInterface)
        self.assertIsInstance(self.driver.deploy, driver_base.DeployInterface)
        self.assertIsInstance(self.driver.vendor, driver_base.VendorInterface)
        self.assertIsNone(self.driver.rescue)
        self.assertIsNone(self.driver.console)

    def test_power_interface(self):
        self.driver.power.validate(self.node)
        with task_manager.acquire(self.context,
                                  [self.node['uuid']]) as task:
            self.driver.power.get_power_state(task, self.node)
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.power.set_power_state,
                              task, self.node, states.NOSTATE)
            self.driver.power.set_power_state(task, self.node, states.POWER_ON)
            self.driver.power.reboot(task, self.node)

    def test_deploy_interface(self):
        self.driver.deploy.validate(self.node)
        self.driver.deploy.deploy(None, None)
        self.driver.deploy.tear_down(None, None)

    def test_vendor_interface(self):
        info = {'method': 'foo',
                'bar': 'baz'}
        self.assertTrue(self.driver.vendor.validate(self.node, **info))
        self.assertTrue(self.driver.vendor.vendor_passthru(None,
                                                           self.node['uuid'],
                                                           **info))
        # no method
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.vendor.validate,
                          self.node, bar='baz')
