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

"""Test class for Ironic TaskManagers."""

from ironic.db import api as dbapi
#from ironic.drivers import fake as fake_driver
#from ironic.manager import task_manager
#from ironic.manager import resource_manager
from ironic.tests.db import base
from ironic.tests.db import utils


class TaskManagerTestCase(base.DbTestCase):

    def setUp(self):
        super(TaskManagerTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()

    def _init(self):
        self.node = utils.get_test_node(control_driver='fake',
                                        deploy_driver='fake')
        self.dbapi.create_node(self.node)
