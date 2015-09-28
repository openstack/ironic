# -*- coding: utf-8 -*-

#    Copyright (C) 2014 Yahoo! Inc. All Rights Reserved.
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

from ironic.common import fsm
from ironic.tests.unit import base


class FSMTest(base.TestCase):
    def test_target_state_stable(self):
        # Test to verify that adding a new state with a 'target' state pointing
        # to a 'stable' state does not raise an exception
        m = fsm.FSM()
        m.add_state('working', stable=True)
        m.add_state('foo', target='working')
        m.default_start_state = 'working'
        m.initialize()
