# Copyright (c) 2018 NEC, Corp.
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

from oslo_upgradecheck.upgradecheck import Code

from ironic.cmd import status
from ironic.tests.unit.db import base as db_base


class TestUpgradeChecks(db_base.DbTestCase):

    def setUp(self):
        super(TestUpgradeChecks, self).setUp()
        self.cmd = status.Checks()

    def test__check_placeholder(self):
        check_result = self.cmd._check_placeholder()
        self.assertEqual(
            Code.SUCCESS, check_result.code)
