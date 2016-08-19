#
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _, _LE
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base
from ironic.drivers.modules.oneview import common


LOG = logging.getLogger(__name__)

oneview_exceptions = importutils.try_import('oneview_client.exceptions')


class OneViewPower(base.PowerInterface):

    def get_properties(self):
        return common.COMMON_PROPERTIES

    def validate(self, task):
        """Checks required info on 'driver_info' and validates node with OneView

        Validates whether the 'oneview_info' property of the supplied
        task's node contains the required info such as server_hardware_uri,
        server_hardware_type, server_profile_template_uri and
        enclosure_group_uri. Also, checks if the server profile of the node is
        applied, if NICs are valid for the server profile of the node, and if
        the server hardware attributes (ram, memory, vcpus count) are
        consistent with OneView.

        :param task: a task from TaskManager.
        :raises: MissingParameterValue if a required parameter is missing.
        :raises: InvalidParameterValue if parameters set are inconsistent with
                 resources in OneView
        """
        common.verify_node_info(task.node)

        try:
            common.validate_oneview_resources_compatibility(task)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)

    def get_power_state(self, task):
        """Gets the current power state.

        :param task: a TaskManager instance.
        :param node: The Node.
        :returns: one of :mod:`ironic.common.states` POWER_OFF,
                  POWER_ON or ERROR.
        :raises: OneViewError if fails to retrieve power state of OneView
                 resource
        """
        oneview_info = common.get_oneview_info(task.node)

        oneview_client = common.get_oneview_client()
        try:
            power_state = oneview_client.get_node_power_state(oneview_info)
        except oneview_exceptions.OneViewException as oneview_exc:
            LOG.error(
                _LE("Error getting power state for node %(node)s. Error:"
                    "%(error)s"),
                {'node': task.node.uuid, 'error': oneview_exc}
            )
            raise exception.OneViewError(error=oneview_exc)
        return common.translate_oneview_power_state(power_state)

    @task_manager.require_exclusive_lock
    def set_power_state(self, task, power_state):
        """Turn the current power state on or off.

        :param task: a TaskManager instance.
        :param node: The Node.
        :param power_state: The desired power state POWER_ON, POWER_OFF or
                            REBOOT from :mod:`ironic.common.states`.
        :raises: InvalidParameterValue if an invalid power state was specified.
        :raises: PowerStateFailure if the power couldn't be set to power_state.
        :raises: OneViewError if OneView fails setting the power state.
        """
        oneview_info = common.get_oneview_info(task.node)

        oneview_client = common.get_oneview_client()

        LOG.debug('Setting power state of node %(node_uuid)s to '
                  '%(power_state)s',
                  {'node_uuid': task.node.uuid, 'power_state': power_state})

        try:
            if power_state == states.POWER_ON:
                oneview_client.power_on(oneview_info)
            elif power_state == states.POWER_OFF:
                oneview_client.power_off(oneview_info)
            elif power_state == states.REBOOT:
                oneview_client.power_off(oneview_info)
                oneview_client.power_on(oneview_info)
            else:
                raise exception.InvalidParameterValue(
                    _("set_power_state called with invalid power state %s.")
                    % power_state)
        except oneview_exceptions.OneViewException as exc:
            raise exception.OneViewError(
                _("Error setting power state: %s") % exc
            )

    @task_manager.require_exclusive_lock
    def reboot(self, task):
        """Reboot the node

        :param task: a TaskManager instance.
        :param node: The Node.
        :raises: PowerStateFailure if the final state of the node is not
                 POWER_ON.
        """

        self.set_power_state(task, states.REBOOT)
