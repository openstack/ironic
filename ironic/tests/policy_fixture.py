# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

import fixtures
from oslo.config import cfg

from ironic.openstack.common import policy as common_policy
import ironic.policy
from ironic.tests import fake_policy

CONF = cfg.CONF


class PolicyFixture(fixtures.Fixture):

    def setUp(self):
        super(PolicyFixture, self).setUp()
        self.policy_dir = self.useFixture(fixtures.TempDir())
        self.policy_file_name = os.path.join(self.policy_dir.path,
                                             'policy.json')
        with open(self.policy_file_name, 'w') as policy_file:
            policy_file.write(fake_policy.policy_data)
        CONF.set_override('policy_file', self.policy_file_name)
        ironic.policy.reset()
        ironic.policy.init()
        self.addCleanup(ironic.policy.reset)

    def set_rules(self, rules):
        common_policy.set_rules(common_policy.Rules(
                dict((k, common_policy.parse_rule(v))
                     for k, v in rules.items())))
