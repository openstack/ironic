# -*- encoding: utf-8 -*-
#
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

from oslo.config import cfg

from ironic.common import exception
from ironic.common import policy as ironic_policy
from ironic.tests import base


CONF = cfg.CONF


class PolicyTestCase(base.TestCase):

    def test_policy_file_not_found(self):
        ironic_policy.reset()
        CONF.set_override('policy_file', '/non/existent/policy/file')
        self.assertRaises(exception.ConfigNotFound, ironic_policy.init)
