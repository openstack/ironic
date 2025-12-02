# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2010 OpenStack Foundation
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

"""
Mapping of bare metal node states.

Setting the node `power_state` is handled by the conductor's power
synchronization thread. Based on the power state retrieved from the driver
for the node, the state is set to POWER_ON or POWER_OFF, accordingly.
Should this fail, the `power_state` value is left unchanged, and the node
is placed into maintenance mode.

The `power_state` can also be set manually via the API. A failure to change
the state leaves the current state unchanged. The node is NOT placed into
maintenance mode in this case.
"""

from oslo_log import log as logging

from ironic.common import fsm
from ironic.common import states as st

LOG = logging.getLogger(__name__)

#####################
# State machine model
#####################


def on_exit(old_state, event):
    """Used to log when a state is exited."""
    LOG.debug("Exiting old state '%s' in response to event '%s'",
              old_state, event)


def on_enter(new_state, event):
    """Used to log when entering a state."""
    LOG.debug("Entering new state '%s' in response to event '%s'",
              new_state, event)


watchers = {}
watchers['on_exit'] = on_exit
watchers['on_enter'] = on_enter

machine = fsm.FSM()

# Add stable states
for state in st.STABLE_STATES:
    machine.add_state(state, stable=True, **watchers)

# Add verifying state
machine.add_state(st.VERIFYING, target=st.MANAGEABLE, **watchers)

# Add deploy* states
# NOTE(tenbrae): Juno shows a target_provision_state of DEPLOYDONE
#             this is changed in Kilo to ACTIVE
machine.add_state(st.DEPLOYING, target=st.ACTIVE, **watchers)
machine.add_state(st.DEPLOYWAIT, target=st.ACTIVE, **watchers)
machine.add_state(st.DEPLOYFAIL, target=st.ACTIVE, **watchers)
machine.add_state(st.DEPLOYHOLD, target=st.ACTIVE, **watchers)

# Add clean* states
machine.add_state(st.CLEANING, target=st.AVAILABLE, **watchers)
machine.add_state(st.CLEANWAIT, target=st.AVAILABLE, **watchers)
machine.add_state(st.CLEANFAIL, target=st.AVAILABLE, **watchers)
machine.add_state(st.CLEANHOLD, target=st.AVAILABLE, **watchers)

# Add delete* states
machine.add_state(st.DELETING, target=st.AVAILABLE, **watchers)

# From AVAILABLE, a deployment may be started
machine.add_transition(st.AVAILABLE, st.DEPLOYING, 'deploy')

# Add inspect* states.
machine.add_state(st.INSPECTING, target=st.MANAGEABLE, **watchers)
machine.add_state(st.INSPECTFAIL, target=st.MANAGEABLE, **watchers)
machine.add_state(st.INSPECTWAIT, target=st.MANAGEABLE, **watchers)

# Add adopt* states
machine.add_state(st.ADOPTING, target=st.ACTIVE, **watchers)
machine.add_state(st.ADOPTFAIL, target=st.ACTIVE, **watchers)

# rescue states
machine.add_state(st.RESCUING, target=st.RESCUE, **watchers)
machine.add_state(st.RESCUEWAIT, target=st.RESCUE, **watchers)
machine.add_state(st.RESCUEFAIL, target=st.RESCUE, **watchers)
machine.add_state(st.UNRESCUING, target=st.ACTIVE, **watchers)
machine.add_state(st.UNRESCUEFAIL, target=st.ACTIVE, **watchers)

# A deployment may fail
machine.add_transition(st.DEPLOYING, st.DEPLOYFAIL, 'fail')

# A failed deployment may be retried
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(st.DEPLOYFAIL, st.DEPLOYING, 'rebuild')
# NOTE(tenbrae): Juno allows a client to send "active" to initiate a rebuild
machine.add_transition(st.DEPLOYFAIL, st.DEPLOYING, 'deploy')

# A deployment may also wait on external callbacks
machine.add_transition(st.DEPLOYING, st.DEPLOYWAIT, 'wait')
machine.add_transition(st.DEPLOYING, st.DEPLOYHOLD, 'hold')
machine.add_transition(st.DEPLOYWAIT, st.DEPLOYHOLD, 'hold')
machine.add_transition(st.DEPLOYWAIT, st.DEPLOYING, 'resume')

# A deployment waiting on callback may time out
machine.add_transition(st.DEPLOYWAIT, st.DEPLOYFAIL, 'fail')

# Return the node into a deploying state from holding
machine.add_transition(st.DEPLOYHOLD, st.DEPLOYWAIT, 'unhold')

# A node in deploy hold may also be aborted
machine.add_transition(st.DEPLOYHOLD, st.DEPLOYFAIL, 'abort')

# A deployment may complete
machine.add_transition(st.DEPLOYING, st.ACTIVE, 'done')

# An active instance may be re-deployed
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(st.ACTIVE, st.DEPLOYING, 'rebuild')

# An active instance may be deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(st.ACTIVE, st.DELETING, 'delete')

# While a deployment is waiting, it may be deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(st.DEPLOYWAIT, st.DELETING, 'delete')

# A failed deployment may also be deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(st.DEPLOYFAIL, st.DELETING, 'delete')

# This state can also transition to error
machine.add_transition(st.DELETING, st.ERROR, 'fail')

# When finished deleting, a node will begin cleaning
machine.add_transition(st.DELETING, st.CLEANING, 'clean')

# If cleaning succeeds, it becomes available for scheduling
machine.add_transition(st.CLEANING, st.AVAILABLE, 'done')

# If cleaning fails, wait for operator intervention
machine.add_transition(st.CLEANING, st.CLEANFAIL, 'fail')
machine.add_transition(st.CLEANWAIT, st.CLEANFAIL, 'fail')

# While waiting for a clean step to be finished, cleaning may be aborted
machine.add_transition(st.CLEANWAIT, st.CLEANFAIL, 'abort')

# Cleaning may also wait on external callbacks
machine.add_transition(st.CLEANING, st.CLEANWAIT, 'wait')
machine.add_transition(st.CLEANING, st.CLEANHOLD, 'hold')
machine.add_transition(st.CLEANWAIT, st.CLEANHOLD, 'hold')
machine.add_transition(st.CLEANWAIT, st.CLEANING, 'resume')

# A node in a clean hold step may also be aborted
machine.add_transition(st.CLEANHOLD, st.CLEANFAIL, 'abort')

# Return the node back to cleaning
machine.add_transition(st.CLEANHOLD, st.CLEANWAIT, 'unhold')

# An operator may want to move a CLEANFAIL node to MANAGEABLE, to perform
# other actions like cleaning
machine.add_transition(st.CLEANFAIL, st.MANAGEABLE, 'manage')

# From MANAGEABLE, a node may move to available after going through automated
# cleaning
machine.add_transition(st.MANAGEABLE, st.CLEANING, 'provide')

# From MANAGEABLE, a node may be manually cleaned, going back to manageable
# after cleaning is completed
machine.add_transition(st.MANAGEABLE, st.CLEANING, 'clean')
machine.add_transition(st.CLEANING, st.MANAGEABLE, 'manage')

# From AVAILABLE, a node may be made unavailable by managing it
machine.add_transition(st.AVAILABLE, st.MANAGEABLE, 'manage')

# An errored instance can be rebuilt
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(st.ERROR, st.DEPLOYING, 'rebuild')
# or deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(st.ERROR, st.DELETING, 'delete')

# Added transitions for inspection.
# Initiate inspection.
machine.add_transition(st.MANAGEABLE, st.INSPECTING, 'inspect')

# ironic/conductor/manager.py:inspect_hardware().
machine.add_transition(st.INSPECTING, st.MANAGEABLE, 'done')

# Inspection may fail.
machine.add_transition(st.INSPECTING, st.INSPECTFAIL, 'fail')

# Transition for asynchronous inspection
machine.add_transition(st.INSPECTING, st.INSPECTWAIT, 'wait')

# Inspection is done
machine.add_transition(st.INSPECTWAIT, st.MANAGEABLE, 'done')

# Inspection failed.
machine.add_transition(st.INSPECTWAIT, st.INSPECTFAIL, 'fail')

# Inspection is aborted.
machine.add_transition(st.INSPECTWAIT, st.INSPECTFAIL, 'abort')

# Inspection is continued.
machine.add_transition(st.INSPECTWAIT, st.INSPECTING, 'resume')

# Move the node to manageable state for any other
# action.
machine.add_transition(st.INSPECTFAIL, st.MANAGEABLE, 'manage')

# Reinitiate the inspect after inspectfail.
machine.add_transition(st.INSPECTFAIL, st.INSPECTING, 'inspect')

# A provisioned node may have a rescue initiated.
machine.add_transition(st.ACTIVE, st.RESCUING, 'rescue')

# A rescue may succeed.
machine.add_transition(st.RESCUING, st.RESCUE, 'done')

# A rescue may also wait on external callbacks
machine.add_transition(st.RESCUING, st.RESCUEWAIT, 'wait')
machine.add_transition(st.RESCUEWAIT, st.RESCUING, 'resume')

# A rescued node may be re-rescued.
machine.add_transition(st.RESCUE, st.RESCUING, 'rescue')

# A rescued node may be deleted.
machine.add_transition(st.RESCUE, st.DELETING, 'delete')

# A rescue may fail.
machine.add_transition(st.RESCUEWAIT, st.RESCUEFAIL, 'fail')
machine.add_transition(st.RESCUING, st.RESCUEFAIL, 'fail')

# While waiting for a rescue step to be finished, rescuing may be aborted
machine.add_transition(st.RESCUEWAIT, st.RESCUEFAIL, 'abort')

# A failed rescue may be re-rescued.
machine.add_transition(st.RESCUEFAIL, st.RESCUING, 'rescue')

# A failed rescue may be unrescued.
machine.add_transition(st.RESCUEFAIL, st.UNRESCUING, 'unrescue')

# A failed rescue may be deleted.
machine.add_transition(st.RESCUEFAIL, st.DELETING, 'delete')

# A rescuewait node may be deleted.
machine.add_transition(st.RESCUEWAIT, st.DELETING, 'delete')

# A rescued node may be unrescued.
machine.add_transition(st.RESCUE, st.UNRESCUING, 'unrescue')

# An unrescuing node may succeed
machine.add_transition(st.UNRESCUING, st.ACTIVE, 'done')

# An unrescuing node may fail
machine.add_transition(st.UNRESCUING, st.UNRESCUEFAIL, 'fail')

# A failed unrescue may be re-rescued
machine.add_transition(st.UNRESCUEFAIL, st.RESCUING, 'rescue')

# A failed unrescue may be re-unrescued
machine.add_transition(st.UNRESCUEFAIL, st.UNRESCUING, 'unrescue')

# A failed unrescue may be deleted.
machine.add_transition(st.UNRESCUEFAIL, st.DELETING, 'delete')

# Start power credentials verification
machine.add_transition(st.ENROLL, st.VERIFYING, 'manage')

# Verification can succeed
machine.add_transition(st.VERIFYING, st.MANAGEABLE, 'done')

# Verification can fail with setting last_error and rolling back to ENROLL
machine.add_transition(st.VERIFYING, st.ENROLL, 'fail')

# Node Adoption is being attempted
machine.add_transition(st.MANAGEABLE, st.ADOPTING, 'adopt')

# Adoption can succeed and the node should be set to ACTIVE
machine.add_transition(st.ADOPTING, st.ACTIVE, 'done')

# Node adoptions can fail and as such nodes shall be set
# into a dedicated state to hold the nodes.
machine.add_transition(st.ADOPTING, st.ADOPTFAIL, 'fail')

# Node adoption can be retried when it previously failed.
machine.add_transition(st.ADOPTFAIL, st.ADOPTING, 'adopt')

# A node that failed adoption can be moved back to manageable
machine.add_transition(st.ADOPTFAIL, st.MANAGEABLE, 'manage')

# Add service* states
machine.add_state(st.SERVICING, target=st.ACTIVE, **watchers)
machine.add_state(st.SERVICEWAIT, target=st.ACTIVE, **watchers)
machine.add_state(st.SERVICEFAIL, target=st.ACTIVE, **watchers)
machine.add_state(st.SERVICEHOLD, target=st.ACTIVE, **watchers)

# A node in service an be returned to active
machine.add_transition(st.SERVICING, st.ACTIVE, 'done')

# A node in active can be serviced
machine.add_transition(st.ACTIVE, st.SERVICING, 'service')

# A node in servicing can be failed
machine.add_transition(st.SERVICING, st.SERVICEFAIL, 'fail')

# A node in service can enter a wait state
machine.add_transition(st.SERVICING, st.SERVICEWAIT, 'wait')

# A node in service can be held
machine.add_transition(st.SERVICING, st.SERVICEHOLD, 'hold')
machine.add_transition(st.SERVICEWAIT, st.SERVICEHOLD, 'hold')

# A held node in service can get more service steps to start over
machine.add_transition(st.SERVICEHOLD, st.SERVICING, 'service')

# A held node in service can be removed from service
machine.add_transition(st.SERVICEHOLD, st.SERVICEWAIT, 'unhold')

# A node in service wait can resume
machine.add_transition(st.SERVICEWAIT, st.SERVICING, 'resume')

# A node in service wait can failed
machine.add_transition(st.SERVICEWAIT, st.SERVICEFAIL, 'fail')

# A node in service hold can failed
machine.add_transition(st.SERVICEHOLD, st.SERVICEFAIL, 'fail')

# A node in service wait can be aborted
machine.add_transition(st.SERVICEWAIT, st.SERVICEFAIL, 'abort')

# A node in service hold can be aborted
machine.add_transition(st.SERVICEHOLD, st.SERVICEFAIL, 'abort')

# A node in service fail can re-enter service
machine.add_transition(st.SERVICEFAIL, st.SERVICING, 'service')

# A node in service fail can be rescued
machine.add_transition(st.SERVICEFAIL, st.RESCUING, 'rescue')

# A node in service fail can enter wait state
machine.add_transition(st.SERVICEFAIL, st.SERVICEWAIT, 'wait')

# A node in service fail can be held
machine.add_transition(st.SERVICEFAIL, st.SERVICEHOLD, 'hold')

# A node in service fail may be deleted.
machine.add_transition(st.SERVICEFAIL, st.DELETING, 'delete')

# A node in service fail may be aborted (returned to active)
machine.add_transition(st.SERVICEFAIL, st.ACTIVE, 'abort')

# A node in service wait may be deleted.
machine.add_transition(st.SERVICEWAIT, st.DELETING, 'delete')
