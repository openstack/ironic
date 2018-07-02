# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

from futurist import periodics
from ironic_lib import metrics_utils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules import inspector
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils

METRICS = metrics_utils.get_metrics_logger(__name__)


class OneViewInspect(inspector.Inspector):
    """Interface for in band inspection."""

    # NOTE(TheJulia): Marking as unsupported as 3rd party CI was taken down
    # shortly before the beginning of the Rocky cycle, and no replies have
    # indicated that 3rd party CI will be re-established nor visible
    # actions observed regarding re-establishing 3rd party CI.
    # TODO(TheJulia): This should be expected to be removed in Stein.
    supported = False

    def get_properties(self):
        return deploy_utils.get_properties()

    @METRICS.timer('OneViewInspect.validate')
    def validate(self, task):
        """Checks required info on 'driver_info' and validates node for OneView

        Validates whether the 'driver_info' property of the supplied
        task's node contains the required info such as server_hardware_uri,
        server_hardware_type, server_profile_template_uri and
        enclosure_group_uri. Also, checks if the server profile of the node is
        applied, if NICs are valid for the server profile of the node.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue if parameters set are inconsistent with
                 resources in OneView
        """

        common.verify_node_info(task.node)

        try:
            common.validate_oneview_resources_compatibility(task)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)

    @METRICS.timer('OneViewInspect.inspect_hardware')
    def inspect_hardware(self, task):
        profile_name = 'Ironic Inspecting [%s]' % task.node.uuid
        deploy_utils.allocate_server_hardware_to_ironic(
            task.node, profile_name
        )
        return super(OneViewInspect, self).inspect_hardware(task)

    @periodics.periodic(spacing=CONF.inspector.status_check_period)
    def _periodic_check_result(self, manager, context):
        filters = {'provision_state': states.INSPECTWAIT,
                   'driver': 'oneview'}
        node_iter = manager.iter_nodes(filters=filters)

        for node_uuid, driver, conductor_group in node_iter:
            try:
                lock_purpose = 'checking hardware inspection status'
                with task_manager.acquire(context, node_uuid,
                                          shared=True,
                                          purpose=lock_purpose) as task:
                    self._check_status(task)
            except (exception.NodeLocked, exception.NodeNotFound):
                continue

    def _check_status(self, task):
        state_before = task.node.provision_state
        result = inspector._check_status(task)
        state_after = task.node.provision_state

        # inspection finished
        if state_before == states.INSPECTWAIT and state_after in [
                states.MANAGEABLE, states.INSPECTFAIL
        ]:
            deploy_utils.deallocate_server_hardware_from_ironic(task.node)

        return result
