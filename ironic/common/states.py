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

from ironic.common import fsm
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

#####################
# Provisioning states
#####################

NOSTATE = None
""" No state information.

Default for the power and provision state of newly created nodes.
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

This is mainly a target provision state used during node tear down. A
successful tear down leaves the node with a `provision_state` of NOSTATE.
"""

ERROR = 'error'
""" An error occurred during node processing.

The `last_error` attribute of the node details should contain an error message.
"""

REBUILD = 'rebuild'
""" Node is to be rebuilt.

This is not used as a state, but rather as a "verb" when changing the node's
provision_state via the REST API.
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
machine.add_state(NOSTATE, **watchers)
machine.add_state(ACTIVE, **watchers)
machine.add_state(ERROR, **watchers)

# Add deploy* states
machine.add_state(DEPLOYDONE, target=ACTIVE, **watchers)
machine.add_state(DEPLOYING, target=DEPLOYDONE, **watchers)
machine.add_state(DEPLOYWAIT, **watchers)
machine.add_state(DEPLOYFAIL, **watchers)

# Add delete* states
machine.add_state(DELETED, target=NOSTATE, **watchers)
machine.add_state(DELETING, target=DELETED, **watchers)


# From NOSTATE, a deployment may be started
machine.add_transition(NOSTATE, DEPLOYING, 'deploy')

# A deployment may fail
machine.add_transition(DEPLOYING, DEPLOYFAIL, 'fail')

# A failed deployment may be retried
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(DEPLOYFAIL, DEPLOYING, 'rebuild')

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

# A delete may complete
machine.add_transition(DELETING, NOSTATE, 'done')

# These states can also transition to error
machine.add_transition(NOSTATE, ERROR, 'error')
machine.add_transition(DEPLOYING, ERROR, 'error')
machine.add_transition(ACTIVE, ERROR, 'error')
machine.add_transition(DELETING, ERROR, 'error')

# An errored instance can be rebuilt
# ironic/conductor/manager.py:do_node_deploy()
machine.add_transition(ERROR, DEPLOYING, 'rebuild')
# or deleted
# ironic/conductor/manager.py:do_node_tear_down()
machine.add_transition(ERROR, DELETING, 'delete')
