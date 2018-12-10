#    Copyright 2017 Lenovo, Inc.
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

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.xclarity import common

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

xclarity_client_exceptions = importutils.try_import(
    'xclarity_client.exceptions')


class XClarityPower(base.PowerInterface):

    def get_properties(self):
        return common.get_properties()

    @METRICS.timer('XClarityPower.validate')
    def validate(self, task):
        """Validate the driver-specific info supplied.

        This method validates if the 'driver_info' property of the supplied
        task's node contains the required information for this driver to
        manage the power state of the node.

        :param task: a task from TaskManager.
        """
        common.parse_driver_info(task.node)

    @METRICS.timer('XClarityPower.get_power_state')
    def get_power_state(self, task):
        """Gets the current power state.

        :param task: a TaskManager instance.
        :returns: one of :mod:`ironic.common.states` POWER_OFF,
                  POWER_ON or ERROR.
        :raises: XClarityError if fails to retrieve power state of XClarity
                 resource
        """
        node = task.node
        client = common.get_xclarity_client(node)
        server_hardware_id = common.get_server_hardware_id(node)
        try:
            power_state = client.get_node_power_status(server_hardware_id)
        except xclarity_client_exceptions.XClarityError as xclarity_exc:
            LOG.error(
                ("Error getting power state for node %(node)s. Error: "
                 "%(error)s"),
                {'node': node.uuid, 'error': xclarity_exc}
            )
            raise exception.XClarityError(error=xclarity_exc)
        return common.translate_xclarity_power_state(power_state)

    @METRICS.timer('XClarityPower.set_power_state')
    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state, timeout=None):
        """Turn the current power state on or off.

        :param task: a TaskManager instance.
        :param power_state: The desired power state POWER_ON, POWER_OFF or
                            REBOOT from :mod:`ironic.common.states`.
        :param timeout: timeout (in seconds). Unsupported by this interface.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: XClarityError if XClarity fails setting the power state.
        """
        # TODO(rloo): Support timeouts!
        if timeout is not None:
            LOG.warning(
                "The 'xclarity' Power Interface's 'set_power_state' method "
                "doesn't support the 'timeout' parameter. Ignoring "
                "timeout=%(timeout)s",
                {'timeout': timeout})

        if power_state == states.REBOOT:
            target_power_state = self.get_power_state(task)
            if target_power_state == states.POWER_OFF:
                power_state = states.POWER_ON

        node = task.node
        client = common.get_xclarity_client(node)
        server_hardware_id = common.get_server_hardware_id(node)
        LOG.debug("Setting power state of node %(node_uuid)s to "
                  "%(power_state)s",
                  {'node_uuid': node.uuid, 'power_state': power_state})

        try:
            client.set_node_power_status(server_hardware_id, power_state)
        except xclarity_client_exceptions.XClarityError as xclarity_exc:
            LOG.error(
                "Error setting power state of node %(node_uuid)s to "
                "%(power_state)s",
                {'node_uuid': task.node.uuid, 'power_state': power_state})
            raise exception.XClarityError(error=xclarity_exc)

    @METRICS.timer('XClarityPower.reboot')
    @task_manager.require_exclusive_lock
    def reboot(self, task, timeout=None):
        """Soft reboot the node

        :param task: a TaskManager instance.
        :param timeout: timeout (in seconds). Unsupported by this interface.
        """
        # TODO(rloo): Support timeouts!
        if timeout is not None:
            LOG.warning("The 'xclarity' Power Interface's 'reboot' method "
                        "doesn't support the 'timeout' parameter. Ignoring "
                        "timeout=%(timeout)s",
                        {'timeout': timeout})

        self.set_power_state(task, states.REBOOT)
