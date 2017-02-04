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

from ironic.common import exception as excp
from ironic.common import fsm
from ironic.tests import base


class FSMTest(base.TestCase):
    def setUp(self):
        super(FSMTest, self).setUp()
        m = fsm.FSM()
        m.add_state('working', stable=True)
        m.add_state('daydream')
        m.add_state('wakeup', target='working')
        m.add_state('play', stable=True)
        m.add_transition('wakeup', 'working', 'walk')
        self.fsm = m

    def test_is_stable(self):
        self.assertTrue(self.fsm.is_stable('working'))

    def test_is_stable_not(self):
        self.assertFalse(self.fsm.is_stable('daydream'))

    def test_is_stable_invalid_state(self):
        self.assertRaises(excp.InvalidState, self.fsm.is_stable, 'foo')

    def test_target_state_stable(self):
        # Test to verify that adding a new state with a 'target' state pointing
        # to a 'stable' state does not raise an exception
        self.fsm.add_state('foo', target='working')
        self.fsm.default_start_state = 'working'
        self.fsm.initialize()

    def test__validate_target_state(self):
        # valid
        self.fsm._validate_target_state('working')

        # target doesn't exist
        self.assertRaisesRegex(excp.InvalidState, "does not exist",
                               self.fsm._validate_target_state, 'new state')

        # target isn't a stable state
        self.assertRaisesRegex(excp.InvalidState, "stable",
                               self.fsm._validate_target_state, 'daydream')

    def test_initialize(self):
        # no start state
        self.assertRaises(excp.InvalidState, self.fsm.initialize)

        # no target state
        self.fsm.initialize('working')
        self.assertEqual('working', self.fsm.current_state)
        self.assertIsNone(self.fsm.target_state)

        # default target state
        self.fsm.initialize('wakeup')
        self.assertEqual('wakeup', self.fsm.current_state)
        self.assertEqual('working', self.fsm.target_state)

        # specify (it overrides default) target state
        self.fsm.initialize('wakeup', 'play')
        self.assertEqual('wakeup', self.fsm.current_state)
        self.assertEqual('play', self.fsm.target_state)

        # specify an invalid target state
        self.assertRaises(excp.InvalidState, self.fsm.initialize,
                          'wakeup', 'daydream')

    def test_process_event(self):
        # default target state
        self.fsm.initialize('wakeup')
        self.fsm.process_event('walk')
        self.assertEqual('working', self.fsm.current_state)
        self.assertIsNone(self.fsm.target_state)

        # specify (it overrides default) target state
        self.fsm.initialize('wakeup')
        self.fsm.process_event('walk', 'play')
        self.assertEqual('working', self.fsm.current_state)
        self.assertEqual('play', self.fsm.target_state)

        # specify an invalid target state
        self.fsm.initialize('wakeup')
        self.assertRaises(excp.InvalidState, self.fsm.process_event,
                          'walk', 'daydream')
