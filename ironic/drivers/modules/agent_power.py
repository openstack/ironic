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

"""
The agent power interface.
"""

import time

from oslo_config import cfg
from oslo_log import log
import tenacity

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as cond_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_client


CONF = cfg.CONF

LOG = log.getLogger(__name__)

_POWER_WAIT = 30


class AgentPower(base.PowerInterface):
    """Power interface using the running agent for power actions."""

    def __init__(self):
        super(AgentPower, self).__init__()
        self._client = agent_client.AgentClient()

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return {}

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        """
        # NOTE(dtantsur): the fast_track option is mutable, so we have to check
        # it again on validation.
        if not utils.fast_track_enabled(task.node):
            raise exception.InvalidParameterValue(
                _('Fast track mode must be enabled to use the agent '
                  'power interface'))
        # TODO(dtantsur): support ACTIVE nodes
        if not cond_utils.agent_is_alive(task.node):
            raise exception.InvalidParameterValue(
                _('Agent seems offline for node %s, the agent power interface '
                  'cannot be used') % task.node.uuid)

    def supports_power_sync(self, task):
        """Check if power sync is supported for the given node.

        Not supported for the agent power since it is not possible to power
        on/off nodes.

        :param task: A TaskManager instance containing the node to act on
            with a **shared** lock.
        :returns: boolean, whether power sync is supported.
        """
        return False

    def get_supported_power_states(self, task):
        """Get a list of the supported power states.

        Only contains REBOOT.

        :param task: A TaskManager instance containing the node to act on.
        :returns: A list with the supported power states defined
                  in :mod:`ironic.common.states`.
        """
        return [states.REBOOT, states.SOFT_REBOOT]

    def get_power_state(self, task):
        """Return the power state of the task's node.

        Essentially, the only known state is POWER ON, everything else is
        an error (or more precisely ``None``).

        :param task: A TaskManager instance containing the node to act on.
        :returns: A power state. One of :mod:`ironic.common.states`.
        """
        # TODO(dtantsur): support ACTIVE nodes
        if cond_utils.agent_is_alive(task.node):
            return states.POWER_ON
        else:
            LOG.error('Node %s is not fast-track-able, cannot determine '
                      'its power state via the "agent" power interface',
                      task.node.uuid)
            return None

    def set_power_state(self, task, power_state, timeout=None):
        """Set the power state of the task's node.

        :param task: A TaskManager instance containing the node to act on.
        :param power_state: Power state from :mod:`ironic.common.states`.
            Only REBOOT and SOFT_REBOOT are supported and are synonymous.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
          power state. ``None`` indicates to use default timeout.
        :raises: PowerStateFailure on non-supported power state.
        """
        if power_state in (states.REBOOT, states.SOFT_REBOOT):
            return self.reboot(task)
        else:
            LOG.error('Power state %(state)s is not implemented for node '
                      '%(node)s using the "agent" power interface',
                      {'node': task.node.uuid, 'state': power_state})
            raise exception.PowerStateFailure(pstate=power_state)

    def reboot(self, task, timeout=None):
        """Perform a reboot of the task's node.

        Only soft reboot is implemented.

        :param task: A TaskManager instance containing the node to act on.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
            power state. ``None`` indicates to use default timeout.
        """
        node = task.node

        self._client.reboot(node)

        # NOTE(dtantsur): wipe the agent token, otherwise the rebooted agent
        # won't be able to heartbeat. This is mostly a precaution since the
        # calling code in conductor is expected to handle it.
        if not node.driver_internal_info.get(
                'agent_secret_token_pregenerated'):
            node.del_driver_internal_info('agent_secret_token')
        # NOTE(dtantsur): the URL may change on reboot, wipe it as well (but
        # only after we call reboot).
        node.del_driver_internal_info('agent_url')
        node.save()

        LOG.debug('Requested reboot of node %(node)s via the agent, waiting '
                  '%(wait)d seconds for the node to power down',
                  {'node': task.node.uuid, 'wait': _POWER_WAIT})
        time.sleep(_POWER_WAIT)

        if (node.provision_state in (states.DEPLOYING, states.CLEANING)
                and (node.driver_internal_info.get('deployment_reboot')
                     or node.driver_internal_info.get('cleaning_reboot'))):
            # NOTE(dtantsur): we need to downgrade the lock otherwise
            # heartbeats won't be processed. It should not have side effects
            # for nodes in DEPLOYING/CLEANING.
            task.downgrade_lock()

            try:
                self._wait_for_reboot(task, timeout)
            finally:
                # The caller probably expects a lock, so re-acquire it
                task.upgrade_lock()

    def _wait_for_reboot(self, task, timeout):
        wait = CONF.agent.post_deploy_get_power_state_retry_interval
        if not timeout:
            timeout = CONF.agent.post_deploy_get_power_state_retries * wait

        @tenacity.retry(
            stop=tenacity.stop_after_delay(timeout),
            retry=(tenacity.retry_if_result(lambda result: not result)
                   | tenacity.retry_if_exception_type(
                exception.AgentConnectionFailed)),
            wait=tenacity.wait_fixed(wait),
            reraise=True)
        def _wait_until_rebooted(task):
            try:
                status = self._client.get_commands_status(
                    task.node, retry_connection=False, expect_errors=True)
            except exception.AgentConnectionFailed:
                LOG.debug('Still waiting for the agent to come back on the '
                          'node %s', task.node.uuid)
                raise

            if any(cmd['command_name'] == agent_client.REBOOT_COMMAND
                   for cmd in status):
                LOG.debug('Still waiting for the agent to power off on the '
                          'node %s', task.node.uuid)
                return False

            return True

        try:
            _wait_until_rebooted(task)
        except exception.AgentConnectionFailed as exc:
            msg = _('Agent failed to come back on %(node)s with the "agent" '
                    'power interface: %(exc)s') % {
                        'node': task.node.uuid, 'exc': exc}
            LOG.error(msg)
            raise exception.PowerStateFailure(msg)
        except Exception as exc:
            LOG.error('Could not reboot node %(node)s with the "agent" power '
                      'interface: %(exc)s',
                      {'node': task.node.uuid, 'exc': exc})
            raise exception.PowerStateFailure(
                _('Unexpected error when rebooting through the agent: %s')
                % exc)
