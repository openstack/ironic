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

from ironic.common import exception as excp
from ironic.common import fsm
from ironic.tests import base


class FSMTest(base.TestCase):
    def setUp(self):
        super(FSMTest, self).setUp()
        self.jumper = fsm.FSM("down")
        self.jumper.add_state('up')
        self.jumper.add_state('down')
        self.jumper.add_transition('down', 'up', 'jump')
        self.jumper.add_transition('up', 'down', 'fall')

    def test_contains(self):
        m = fsm.FSM('unknown')
        self.assertNotIn('unknown', m)
        m.add_state('unknown')
        self.assertIn('unknown', m)

    def test_duplicate_state(self):
        m = fsm.FSM('unknown')
        m.add_state('unknown')
        self.assertRaises(excp.Duplicate, m.add_state, 'unknown')

    def test_bad_transition(self):
        m = fsm.FSM('unknown')
        m.add_state('unknown')
        m.add_state('fire')
        self.assertRaises(excp.NotFound, m.add_transition,
                          'unknown', 'something', 'boom')
        self.assertRaises(excp.NotFound, m.add_transition,
                          'something', 'unknown', 'boom')

    def test_on_enter_on_exit(self):
        def on_exit(state, event):
            exit_transitions.append((state, event))

        def on_enter(state, event):
            enter_transitions.append((state, event))

        enter_transitions = []
        exit_transitions = []

        m = fsm.FSM('start')
        m.add_state('start', on_exit=on_exit)
        m.add_state('down', on_enter=on_enter, on_exit=on_exit)
        m.add_state('up', on_enter=on_enter, on_exit=on_exit)
        m.add_transition('start', 'down', 'beat')
        m.add_transition('down', 'up', 'jump')
        m.add_transition('up', 'down', 'fall')

        m.initialize()
        m.process_event('beat')
        m.process_event('jump')
        m.process_event('fall')
        self.assertEqual([('down', 'beat'),
                          ('up', 'jump'), ('down', 'fall')], enter_transitions)
        self.assertEqual([('down', 'jump'), ('up', 'fall')], exit_transitions)

    def test_not_initialized(self):
        self.assertRaises(excp.InvalidState,
                          self.jumper.process_event, 'jump')

    def test_copy_states(self):
        c = fsm.FSM()
        self.assertEqual(0, len(c.states))

        c.add_state('up')
        self.assertEqual(1, len(c.states))

        deep = c.copy()
        shallow = c.copy(shallow=True)

        c.add_state('down')
        c.add_transition('up', 'down', 'fall')
        self.assertEqual(2, len(c.states))

        # deep copy created new members, so change is not visible
        self.assertEqual(1, len(deep.states))
        self.assertNotEqual(c._transitions, deep._transitions)

        # but a shallow copy references the same state object
        self.assertEqual(2, len(shallow.states))
        self.assertEqual(c._transitions, shallow._transitions)

    def test_copy_clears_current(self):
        c = fsm.FSM()
        c.add_state('up')
        c.initialize('up')
        d = c.copy()

        self.assertEqual('up', c.current_state)
        self.assertEqual(None, d.current_state)

    def test_invalid_callbacks(self):
        m = fsm.FSM('working')
        m.add_state('working')
        m.add_state('broken')
        self.assertRaises(ValueError, m.add_state, 'b', on_enter=2)
        self.assertRaises(ValueError, m.add_state, 'b', on_exit=2)

    def test_invalid_target_state(self):
        # Test to verify that adding a state which has a 'target' state that
        # does not exist will raise an exception
        self.assertRaises(excp.InvalidState,
                          self.jumper.add_state, 'jump', target='unknown')

    def test_target_state_not_stable(self):
        # Test to verify that adding a state that has a 'target' state which is
        # not a 'stable' state will raise an exception
        self.assertRaises(excp.InvalidState,
                          self.jumper.add_state, 'jump', target='down')

    def test_target_state_stable(self):
        # Test to verify that adding a new state with a 'target' state pointing
        # to a 'stable' state does not raise an exception
        m = fsm.FSM('working')
        m.add_state('working', stable=True)
        m.add_state('foo', target='working')
        m.initialize()
