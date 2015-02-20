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
"""State machine modelling, copied from TaskFlow project.

This work will be turned into a library.
See https://github.com/harlowja/automaton

This is being used in the implementation of:
http://specs.openstack.org/openstack/ironic-specs/specs/kilo/new-ironic-state-machine.html
"""

from collections import OrderedDict  # noqa

import six

from ironic.common import exception as excp
from ironic.common.i18n import _


class _Jump(object):
    """A FSM transition tracks this data while jumping."""
    def __init__(self, name, on_enter, on_exit):
        self.name = name
        self.on_enter = on_enter
        self.on_exit = on_exit


class FSM(object):
    """A finite state machine.

    This class models a state machine, and expects an outside caller to
    manually trigger the state changes one at a time by invoking process_event
    """
    def __init__(self, start_state=None):
        self._transitions = {}
        self._states = OrderedDict()
        self._start_state = start_state
        self._target_state = None
        # Note that _current is a _Jump instance
        self._current = None

    @property
    def start_state(self):
        return self._start_state

    @property
    def current_state(self):
        if self._current is not None:
            return self._current.name
        return None

    @property
    def target_state(self):
        return self._target_state

    @property
    def terminated(self):
        """Returns whether the state machine is in a terminal state."""
        if self._current is None:
            return False
        return self._states[self._current.name]['terminal']

    def add_state(self, state, on_enter=None, on_exit=None,
            target=None, terminal=None, stable=False):
        """Adds a given state to the state machine.

        The on_enter and on_exit callbacks, if provided will be expected to
        take two positional parameters, these being the state being exited (for
        on_exit) or the state being entered (for on_enter) and a second
        parameter which is the event that is being processed that caused the
        state transition.

        :param stable: Use this to specify that this state is a stable/passive
                       state. A state must have been previously defined as
                       'stable' before it can be used as a 'target'
        :param target: The target state for 'state' to go to.  Before a state
                       can be used as a target it must have been previously
                       added and specified as 'stable'
        """
        if state in self._states:
            raise excp.Duplicate(_("State '%s' already defined") % state)
        if on_enter is not None:
            if not six.callable(on_enter):
                raise ValueError(_("On enter callback must be callable"))
        if on_exit is not None:
            if not six.callable(on_exit):
                raise ValueError(_("On exit callback must be callable"))
        if target is not None and target not in self._states:
            raise excp.InvalidState(_("Target state '%s' does not exist")
                    % target)
        if target is not None and not self._states[target]['stable']:
            raise excp.InvalidState(
                _("Target state '%s' is not a 'stable' state") % target)

        self._states[state] = {
            'terminal': bool(terminal),
            'reactions': {},
            'on_enter': on_enter,
            'on_exit': on_exit,
            'target': target,
            'stable': stable,
        }
        self._transitions[state] = OrderedDict()

    def add_transition(self, start, end, event):
        """Adds an allowed transition from start -> end for the given event."""
        if start not in self._states:
            raise excp.NotFound(
                _("Can not add a transition on event '%(event)s' that "
                  "starts in a undefined state '%(state)s'")
                % {'event': event, 'state': start})
        if end not in self._states:
            raise excp.NotFound(
                _("Can not add a transition on event '%(event)s' that "
                  "ends in a undefined state '%(state)s'")
                % {'event': event, 'state': end})
        self._transitions[start][event] = _Jump(end,
                                                self._states[end]['on_enter'],
                                                self._states[start]['on_exit'])

    def process_event(self, event):
        """Trigger a state change in response to the provided event."""
        current = self._current
        if current is None:
            raise excp.InvalidState(_("Can only process events after"
                                      " being initialized (not before)"))
        if self._states[current.name]['terminal']:
            raise excp.InvalidState(
                _("Can not transition from terminal "
                  "state '%(state)s' on event '%(event)s'")
                % {'state': current.name, 'event': event})
        if event not in self._transitions[current.name]:
            raise excp.InvalidState(
                _("Can not transition from state '%(state)s' on "
                  "event '%(event)s' (no defined transition)")
                % {'state': current.name, 'event': event})
        replacement = self._transitions[current.name][event]
        if current.on_exit is not None:
            current.on_exit(current.name, event)
        if replacement.on_enter is not None:
            replacement.on_enter(replacement.name, event)
        self._current = replacement

        # clear _target if we've reached it
        if (self._target_state is not None and
                self._target_state == replacement.name):
            self._target_state = None
        # if new state has a different target, update the target
        if self._states[replacement.name]['target'] is not None:
            self._target_state = self._states[replacement.name]['target']

    def is_valid_event(self, event):
        """Check whether the event is actionable in the current state."""
        current = self._current
        if current is None:
            return False
        if self._states[current.name]['terminal']:
            return False
        if event not in self._transitions[current.name]:
            return False
        return True

    def initialize(self, state=None):
        """Sets up the state machine.

        sets the current state to the specified state, or start_state
        if no state was specified..
        """
        if state is None:
            state = self._start_state
        if state not in self._states:
            raise excp.NotFound(_("Can not start from an undefined"
                                  " state '%s'") % (state))
        if self._states[state]['terminal']:
            raise excp.InvalidState(_("Can not start from a terminal"
                                      " state '%s'") % (state))
        self._current = _Jump(state, None, None)
        self._target_state = self._states[state]['target']

    def copy(self, shallow=False):
        """Copies the current state machine (shallow or deep).

        NOTE(harlowja): the copy will be left in an *uninitialized* state.

        NOTE(harlowja): when a shallow copy is requested the copy will share
                        the same transition table and state table as the
                        source; this can be advantageous if you have a machine
                        and transitions + states that is defined somewhere
                        and want to use copies to run with (the copies have
                        the current state that is different between machines).
        """
        c = FSM(self.start_state)
        if not shallow:
            for state, data in six.iteritems(self._states):
                copied_data = data.copy()
                copied_data['reactions'] = copied_data['reactions'].copy()
                c._states[state] = copied_data
            for state, data in six.iteritems(self._transitions):
                c._transitions[state] = data.copy()
        else:
            c._transitions = self._transitions
            c._states = self._states
        return c

    def __contains__(self, state):
        """Returns if this state exists in the machines known states."""
        return state in self._states

    @property
    def states(self):
        """Returns a list of the state names."""
        return list(six.iterkeys(self._states))

    def __iter__(self):
        """Iterates over (start, event, end) transition tuples."""
        for state in six.iterkeys(self._states):
            for event, target in six.iteritems(self._transitions[state]):
                yield (state, event, target.name)

    @property
    def events(self):
        """Returns how many events exist."""
        c = 0
        for state in six.iterkeys(self._states):
            c += len(self._transitions[state])
        return c
