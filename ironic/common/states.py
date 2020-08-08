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

LOG = logging.getLogger(__name__)

#####################
# Provisioning states
#####################

# TODO(deva): add add'l state mappings here
VERBS = {
    'active': 'deploy',
    'deleted': 'delete',
    'manage': 'manage',
    'provide': 'provide',
    'inspect': 'inspect',
    'abort': 'abort',
    'clean': 'clean',
    'adopt': 'adopt',
    'rescue': 'rescue',
    'unrescue': 'unrescue',
}
""" Mapping of state-changing events that are PUT to the REST API

This is a mapping of target states which are PUT to the API, eg,
    PUT /v1/node/states/provision {'target': 'active'}

The dict format is:
    {target string used by the API: internal verb}

This provides a reference set of supported actions, and in the future
may be used to support renaming these actions.
"""

NOSTATE = None
""" No state information.

This state is used with power_state to represent a lack of knowledge of
power state, and in target_*_state fields when there is no target.
"""

ENROLL = 'enroll'
""" Node is enrolled.

This state indicates that Ironic is aware of a node, but is not managing it.
"""

VERIFYING = 'verifying'
""" Node power management credentials are being verified. """

MANAGEABLE = 'manageable'
""" Node is in a manageable state.

This state indicates that Ironic has verified, at least once, that it had
sufficient information to manage the hardware. While in this state, the node
is not available for provisioning (it must be in the AVAILABLE state for that).
"""

AVAILABLE = 'available'
""" Node is available for use and scheduling.

This state is replacing the NOSTATE state used prior to Kilo.
"""

ACTIVE = 'active'
""" Node is successfully deployed and associated with an instance. """

DEPLOYWAIT = 'wait call-back'
""" Node is waiting to be deployed.

This will be the node `provision_state` while the node is waiting for
the driver to finish deployment.
"""

DEPLOYING = 'deploying'
""" Node is ready to receive a deploy request, or is currently being deployed.

A node will have its `provision_state` set to DEPLOYING briefly before it
receives its initial deploy request. It will also move to this state from
DEPLOYWAIT after the callback is triggered and deployment is continued
(disk partitioning and image copying).
"""

DEPLOYFAIL = 'deploy failed'
""" Node deployment failed. """

DEPLOYDONE = 'deploy complete'
""" Node was successfully deployed.

This is mainly a target provision state used during deployment. A successfully
deployed node should go to ACTIVE status.
"""

DELETING = 'deleting'
""" Node is actively being torn down. """

DELETED = 'deleted'
""" Node tear down was successful.

In Juno, target_provision_state was set to this value during node tear down.

In Kilo, this will be a transitory value of provision_state, and never
represented in target_provision_state.
"""

CLEANING = 'cleaning'
""" Node is being automatically cleaned to prepare it for provisioning. """

CLEANWAIT = 'clean wait'
""" Node is waiting for a clean step to be finished.

This will be the node's `provision_state` while the node is waiting for
the driver to finish a cleaning step.
"""

CLEANFAIL = 'clean failed'
""" Node failed cleaning. This requires operator intervention to resolve. """

ERROR = 'error'
""" An error occurred during node processing.

The `last_error` attribute of the node details should contain an error message.
"""

REBUILD = 'rebuild'
""" Node is to be rebuilt.

This is not used as a state, but rather as a "verb" when changing the node's
provision_state via the REST API.
"""

INSPECTING = 'inspecting'
""" Node is under inspection.

This is the provision state used when inspection is started. A successfully
inspected node shall transition to MANAGEABLE state. For asynchronous
inspection, node shall transition to INSPECTWAIT state.
"""

INSPECTFAIL = 'inspect failed'
""" Node inspection failed. """

INSPECTWAIT = 'inspect wait'
""" Node is under inspection.

This is the provision state used when an asynchronous inspection is in
progress. A successfully inspected node shall transition to MANAGEABLE state.
"""

ADOPTING = 'adopting'
""" Node is being adopted.

This provision state is intended for use to move a node from MANAGEABLE to
ACTIVE state to permit designation of nodes as being "managed" by Ironic,
however "deployed" previously by external means.
"""

ADOPTFAIL = 'adopt failed'
""" Node failed to complete the adoption process.

This state is the resulting state of a node that failed to complete adoption,
potentially due to invalid or incompatible information being defined for the
node.
"""

RESCUE = 'rescue'
""" Node is in rescue mode. """

RESCUEFAIL = 'rescue failed'
""" Node rescue failed. """

RESCUEWAIT = 'rescue wait'
""" Node is waiting on an external callback.

This will be the node `provision_state` while the node is waiting for
the driver to finish rescuing the node.
"""

RESCUING = 'rescuing'
""" Node is in process of being rescued. """

UNRESCUEFAIL = 'unrescue failed'
""" Node unrescue failed. """

UNRESCUING = 'unrescuing'
""" Node is being restored from rescue mode (to active state). """

# NOTE(kaifeng): INSPECTING is allowed to keep backwards compatibility,
# starting from API 1.39 node update is disallowed in this state.
UPDATE_ALLOWED_STATES = (DEPLOYFAIL, INSPECTING, INSPECTFAIL, INSPECTWAIT,
                         CLEANFAIL, ERROR, VERIFYING, ADOPTFAIL, RESCUEFAIL,
                         UNRESCUEFAIL)
"""Transitional states in which we allow updating a node."""

DELETE_ALLOWED_STATES = (AVAILABLE, MANAGEABLE, ENROLL, ADOPTFAIL)
"""States in which node deletion is allowed."""

STABLE_STATES = (ENROLL, MANAGEABLE, AVAILABLE, ACTIVE, ERROR, RESCUE)
"""States that will not transition unless receiving a request."""

UNSTABLE_STATES = (DEPLOYING, DEPLOYWAIT, CLEANING, CLEANWAIT, VERIFYING,
                   DELETING, INSPECTING, INSPECTWAIT, ADOPTING, RESCUING,
                   RESCUEWAIT, UNRESCUING)
"""States that can be changed without external request."""

STUCK_STATES_TREATED_AS_FAIL = (DEPLOYING, CLEANING, VERIFYING, INSPECTING,
                                ADOPTING, RESCUING, UNRESCUING, DELETING)
"""States that cannot be resumed once a conductor dies.

If a node gets stuck with one of these states for some reason
(eg. conductor goes down when executing task), node will be moved
to fail state.
"""

##############
# Power states
##############

POWER_ON = 'power on'
""" Node is powered on. """

POWER_OFF = 'power off'
""" Node is powered off. """

REBOOT = 'rebooting'
""" Node is rebooting. """

SOFT_REBOOT = 'soft rebooting'
""" Node is rebooting gracefully. """

SOFT_POWER_OFF = 'soft power off'
""" Node is in the process of soft power off. """


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
for state in STABLE_STATES:
    machine.add_state(state, stable=True, **watchers)

# Add verifying state
machine.add_state(VERIFYING, target=MANAGEABLE, **watchers)

# Add deploy* states
# NOTE(deva): Juno shows a target_provision_state of DEPLOYDONE
#             this is changed in Kilo to ACTIVE
machine.add_state(DEPLOYING, target=ACTIVE, **watchers)
machine.add_state(DEPLOYWAIT, target=ACTIVE, **watchers)
machine.add_state(DEPLOYFAIL, target=ACTIVE, **watchers)

# Add clean* states
machine.add_state(CLEANING, target=AVAILABLE, **watchers)
machine.add_state(CLEANWAIT, target=AVAILABLE, **watchers)
machine.add_state(CLEANFAIL, target=AVAILABLE, **watchers)

# Add delete* states
machine.add_state(DELETING, target=AVAILABLE, **watchers)

# From AVAILABLE, a deployment may be started
machine.add_transition(AVAILABLE, DEPLOYING, 'deploy')

# Add inspect* states.
machine.add_state(INSPECTING, target=MANAGEABLE, **watchers)
machine.add_state(INSPECTFAIL, target=MANAGEABLE, **watchers)
machine.add_state(INSPECTWAIT, target=MANAGEABLE, **watchers)

# Add adopt* states
machine.add_state(ADOPTING, target=ACTIVE, **watchers)
machine.add_state(ADOPTFAIL, target=ACTIVE, **watchers)

# rescue states
machine.add_state(RESCUING, target=RESCUE, **watchers)
machine.add_state(RESCUEWAIT, target=RESCUE, **watchers)
machine.add_state(RESCUEFAIL, target=RESCUE, **watchers)
machine.add_state(UNRESCUING, target=ACTIVE, **watchers)
machine.add_state(UNRESCUEFAIL, target=ACTIVE, **watchers)

# A deployment may fail
machine.add_transition(DEPLOYING, DEPLOYFAIL, 'fail')

# A failed deployment may be retried
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(DEPLOYFAIL, DEPLOYING, 'rebuild')
# NOTE(deva): Juno allows a client to send "active" to initiate a rebuild
machine.add_transition(DEPLOYFAIL, DEPLOYING, 'deploy')

# A deployment may also wait on external callbacks
machine.add_transition(DEPLOYING, DEPLOYWAIT, 'wait')
machine.add_transition(DEPLOYWAIT, DEPLOYING, 'resume')

# A deployment waiting on callback may time out
machine.add_transition(DEPLOYWAIT, DEPLOYFAIL, 'fail')

# A deployment may complete
machine.add_transition(DEPLOYING, ACTIVE, 'done')

# An active instance may be re-deployed
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(ACTIVE, DEPLOYING, 'rebuild')

# An active instance may be deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(ACTIVE, DELETING, 'delete')

# While a deployment is waiting, it may be deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(DEPLOYWAIT, DELETING, 'delete')

# A failed deployment may also be deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(DEPLOYFAIL, DELETING, 'delete')

# This state can also transition to error
machine.add_transition(DELETING, ERROR, 'fail')

# When finished deleting, a node will begin cleaning
machine.add_transition(DELETING, CLEANING, 'clean')

# If cleaning succeeds, it becomes available for scheduling
machine.add_transition(CLEANING, AVAILABLE, 'done')

# If cleaning fails, wait for operator intervention
machine.add_transition(CLEANING, CLEANFAIL, 'fail')
machine.add_transition(CLEANWAIT, CLEANFAIL, 'fail')

# While waiting for a clean step to be finished, cleaning may be aborted
machine.add_transition(CLEANWAIT, CLEANFAIL, 'abort')

# Cleaning may also wait on external callbacks
machine.add_transition(CLEANING, CLEANWAIT, 'wait')
machine.add_transition(CLEANWAIT, CLEANING, 'resume')

# An operator may want to move a CLEANFAIL node to MANAGEABLE, to perform
# other actions like cleaning
machine.add_transition(CLEANFAIL, MANAGEABLE, 'manage')

# From MANAGEABLE, a node may move to available after going through automated
# cleaning
machine.add_transition(MANAGEABLE, CLEANING, 'provide')

# From MANAGEABLE, a node may be manually cleaned, going back to manageable
# after cleaning is completed
machine.add_transition(MANAGEABLE, CLEANING, 'clean')
machine.add_transition(CLEANING, MANAGEABLE, 'manage')

# From AVAILABLE, a node may be made unavailable by managing it
machine.add_transition(AVAILABLE, MANAGEABLE, 'manage')

# An errored instance can be rebuilt
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(ERROR, DEPLOYING, 'rebuild')
# or deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(ERROR, DELETING, 'delete')

# Added transitions for inspection.
# Initiate inspection.
machine.add_transition(MANAGEABLE, INSPECTING, 'inspect')

# ironic/conductor/manager.py:inspect_hardware().
machine.add_transition(INSPECTING, MANAGEABLE, 'done')

# Inspection may fail.
machine.add_transition(INSPECTING, INSPECTFAIL, 'fail')

# Transition for asynchronous inspection
machine.add_transition(INSPECTING, INSPECTWAIT, 'wait')

# Inspection is done
machine.add_transition(INSPECTWAIT, MANAGEABLE, 'done')

# Inspection failed.
machine.add_transition(INSPECTWAIT, INSPECTFAIL, 'fail')

# Inspection is aborted.
machine.add_transition(INSPECTWAIT, INSPECTFAIL, 'abort')

# Move the node to manageable state for any other
# action.
machine.add_transition(INSPECTFAIL, MANAGEABLE, 'manage')

# Reinitiate the inspect after inspectfail.
machine.add_transition(INSPECTFAIL, INSPECTING, 'inspect')

# A provisioned node may have a rescue initiated.
machine.add_transition(ACTIVE, RESCUING, 'rescue')

# A rescue may succeed.
machine.add_transition(RESCUING, RESCUE, 'done')

# A rescue may also wait on external callbacks
machine.add_transition(RESCUING, RESCUEWAIT, 'wait')
machine.add_transition(RESCUEWAIT, RESCUING, 'resume')

# A rescued node may be re-rescued.
machine.add_transition(RESCUE, RESCUING, 'rescue')

# A rescued node may be deleted.
machine.add_transition(RESCUE, DELETING, 'delete')

# A rescue may fail.
machine.add_transition(RESCUEWAIT, RESCUEFAIL, 'fail')
machine.add_transition(RESCUING, RESCUEFAIL, 'fail')

# While waiting for a rescue step to be finished, rescuing may be aborted
machine.add_transition(RESCUEWAIT, RESCUEFAIL, 'abort')

# A failed rescue may be re-rescued.
machine.add_transition(RESCUEFAIL, RESCUING, 'rescue')

# A failed rescue may be unrescued.
machine.add_transition(RESCUEFAIL, UNRESCUING, 'unrescue')

# A failed rescue may be deleted.
machine.add_transition(RESCUEFAIL, DELETING, 'delete')

# A rescuewait node may be deleted.
machine.add_transition(RESCUEWAIT, DELETING, 'delete')

# A rescued node may be unrescued.
machine.add_transition(RESCUE, UNRESCUING, 'unrescue')

# An unrescuing node may succeed
machine.add_transition(UNRESCUING, ACTIVE, 'done')

# An unrescuing node may fail
machine.add_transition(UNRESCUING, UNRESCUEFAIL, 'fail')

# A failed unrescue may be re-rescued
machine.add_transition(UNRESCUEFAIL, RESCUING, 'rescue')

# A failed unrescue may be re-unrescued
machine.add_transition(UNRESCUEFAIL, UNRESCUING, 'unrescue')

# A failed unrescue may be deleted.
machine.add_transition(UNRESCUEFAIL, DELETING, 'delete')

# Start power credentials verification
machine.add_transition(ENROLL, VERIFYING, 'manage')

# Verification can succeed
machine.add_transition(VERIFYING, MANAGEABLE, 'done')

# Verification can fail with setting last_error and rolling back to ENROLL
machine.add_transition(VERIFYING, ENROLL, 'fail')

# Node Adoption is being attempted
machine.add_transition(MANAGEABLE, ADOPTING, 'adopt')

# Adoption can succeed and the node should be set to ACTIVE
machine.add_transition(ADOPTING, ACTIVE, 'done')

# Node adoptions can fail and as such nodes shall be set
# into a dedicated state to hold the nodes.
machine.add_transition(ADOPTING, ADOPTFAIL, 'fail')

# Node adoption can be retried when it previously failed.
machine.add_transition(ADOPTFAIL, ADOPTING, 'adopt')

# A node that failed adoption can be moved back to manageable
machine.add_transition(ADOPTFAIL, MANAGEABLE, 'manage')
