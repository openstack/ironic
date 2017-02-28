# Copyright 2016 Hewlett Packard Enterprise Development LP.
# Copyright 2016 Universidade Federal de Campina Grande
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

import abc

from futurist import periodics
from ironic_lib import metrics_utils
from oslo_log import log as logging
import retrying
import six

from ironic.common import exception
from ironic.common.i18n import _, _LE, _LI, _LW
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils as ironic_deploy_utils
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic import objects

LOG = logging.getLogger(__name__)
METRICS = metrics_utils.get_metrics_logger(__name__)


@six.add_metaclass(abc.ABCMeta)
class OneViewPeriodicTasks(object):

    @abc.abstractproperty
    def oneview_driver(self):
        pass

    @periodics.periodic(spacing=CONF.oneview.periodic_check_interval,
                        enabled=CONF.oneview.enable_periodic_tasks)
    def _periodic_check_nodes_taken_by_oneview(self, manager, context):
        """Checks if nodes in Ironic were taken by OneView users.

        This driver periodic task will check for nodes that were taken by
        OneView users while the node is in available state, set the node to
        maintenance mode with an appropriate maintenance reason message and
        move the node to manageable state.

        :param manager: a ConductorManager instance
        :param context: request context
        :returns: None.
        """

        filters = {
            'provision_state': states.AVAILABLE,
            'maintenance': False,
            'driver': self.oneview_driver
        }
        node_iter = manager.iter_nodes(filters=filters)

        for node_uuid, driver in node_iter:

            node = objects.Node.get(context, node_uuid)

            try:
                oneview_using = deploy_utils.is_node_in_use_by_oneview(
                    self.oneview_client, node
                )
            except exception.OneViewError as e:
                # NOTE(xavierr): Skip this node and process the
                # remaining nodes. This node will be checked in
                # the next periodic call.

                LOG.error(_LE("Error while determining if node "
                              "%(node_uuid)s is in use by OneView. "
                              "Error: %(error)s"),
                          {'node_uuid': node.uuid, 'error': e})

                continue

            if oneview_using:
                purpose = (_LI('Updating node %(node_uuid)s in use '
                               'by OneView from %(provision_state)s state '
                               'to %(target_state)s state and maintenance '
                               'mode %(maintenance)s.'),
                           {'node_uuid': node_uuid,
                            'provision_state': states.AVAILABLE,
                            'target_state': states.MANAGEABLE,
                            'maintenance': True})

                LOG.info(purpose)

                node.maintenance = True
                node.maintenance_reason = common.NODE_IN_USE_BY_ONEVIEW
                manager.update_node(context, node)
                manager.do_provisioning_action(context, node.uuid, 'manage')

    @periodics.periodic(spacing=CONF.oneview.periodic_check_interval,
                        enabled=CONF.oneview.enable_periodic_tasks)
    def _periodic_check_nodes_freed_by_oneview(self, manager, context):
        """Checks if nodes taken by OneView users were freed.

        This driver periodic task will be responsible to poll the nodes that
        are in maintenance mode and on manageable state to check if the Server
        Profile was removed, indicating that the node was freed by the OneView
        user. If so, it'll provide the node, that will pass through the
        cleaning process and become available to be provisioned.

        :param manager: a ConductorManager instance
        :param context: request context
        :returns: None.
        """

        filters = {
            'provision_state': states.MANAGEABLE,
            'maintenance': True,
            'driver': self.oneview_driver
        }
        node_iter = manager.iter_nodes(fields=['maintenance_reason'],
                                       filters=filters)
        for node_uuid, driver, maintenance_reason in node_iter:

            if maintenance_reason == common.NODE_IN_USE_BY_ONEVIEW:

                node = objects.Node.get(context, node_uuid)

                try:
                    oneview_using = deploy_utils.is_node_in_use_by_oneview(
                        self.oneview_client, node
                    )
                except exception.OneViewError as e:
                    # NOTE(xavierr): Skip this node and process the
                    # remaining nodes. This node will be checked in
                    # the next periodic call.

                    LOG.error(_LE("Error while determining if node "
                                  "%(node_uuid)s is in use by OneView. "
                                  "Error: %(error)s"),
                              {'node_uuid': node.uuid, 'error': e})

                    continue

                if not oneview_using:
                    purpose = (_LI('Bringing node %(node_uuid)s back from '
                                   'use by OneView from %(provision_state)s '
                                   'state to %(target_state)s state and '
                                   'maintenance mode %(maintenance)s.'),
                               {'node_uuid': node_uuid,
                                'provision_state': states.MANAGEABLE,
                                'target_state': states.AVAILABLE,
                                'maintenance': False})

                    LOG.info(purpose)

                    node.maintenance = False
                    node.maintenance_reason = None
                    manager.update_node(context, node)
                    manager.do_provisioning_action(
                        context, node.uuid, 'provide'
                    )

    @periodics.periodic(spacing=CONF.oneview.periodic_check_interval,
                        enabled=CONF.oneview.enable_periodic_tasks)
    def _periodic_check_nodes_taken_on_cleanfail(self, manager, context):
        """Checks failed deploys due to Oneview users taking Server Hardware.

        This last driver periodic task will take care of nodes that would be
        caught on a race condition between OneView and a deploy by Ironic. In
        such cases, the validation will fail, throwing the node on deploy fail
        and, afterwards on clean fail.

        This task will set the node to maintenance mode with a proper reason
        message and move it to manageable state, from where the second task
        can rescue the node as soon as the Server Profile is removed.

        :param manager: a ConductorManager instance
        :param context: request context
        :returns: None.
        """

        filters = {
            'provision_state': states.CLEANFAIL,
            'driver': self.oneview_driver
        }
        node_iter = manager.iter_nodes(fields=['driver_internal_info'],
                                       filters=filters)

        for node_uuid, driver, driver_internal_info in node_iter:

            node_oneview_error = driver_internal_info.get('oneview_error')
            if node_oneview_error == common.SERVER_HARDWARE_ALLOCATION_ERROR:

                node = objects.Node.get(context, node_uuid)

                purpose = (_LI('Bringing node %(node_uuid)s back from use '
                               'by OneView from %(provision_state)s state '
                               'to %(target_state)s state and '
                               'maintenance mode %(maintenance)s.'),
                           {'node_uuid': node_uuid,
                            'provision_state': states.CLEANFAIL,
                            'target_state': states.MANAGEABLE,
                            'maintenance': False})

                LOG.info(purpose)

                node.maintenance = True
                node.maintenance_reason = common.NODE_IN_USE_BY_ONEVIEW
                driver_internal_info = node.driver_internal_info
                driver_internal_info.pop('oneview_error', None)
                node.driver_internal_info = driver_internal_info
                manager.update_node(context, node)
                manager.do_provisioning_action(context, node.uuid, 'manage')


class OneViewIscsiDeploy(iscsi_deploy.ISCSIDeploy, OneViewPeriodicTasks):
    """Class for OneView ISCSI deployment driver."""

    oneview_driver = common.ISCSI_PXE_ONEVIEW

    def __init__(self):
        super(OneViewIscsiDeploy, self).__init__()
        self.oneview_client = common.get_oneview_client()

    def get_properties(self):
        return deploy_utils.get_properties()

    @METRICS.timer('OneViewIscsiDeploy.validate')
    def validate(self, task):
        common.verify_node_info(task.node)
        try:
            common.validate_oneview_resources_compatibility(
                self.oneview_client, task)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)
        super(OneViewIscsiDeploy, self).validate(task)

    @METRICS.timer('OneViewIscsiDeploy.prepare')
    def prepare(self, task):
        if common.is_dynamic_allocation_enabled(task.node):
            deploy_utils.prepare(self.oneview_client, task)
        super(OneViewIscsiDeploy, self).prepare(task)

    @METRICS.timer('OneViewIscsiDeploy.tear_down')
    def tear_down(self, task):
        if (common.is_dynamic_allocation_enabled(task.node) and
           not CONF.conductor.automated_clean):
            deploy_utils.tear_down(self.oneview_client, task)
        return super(OneViewIscsiDeploy, self).tear_down(task)

    @METRICS.timer('OneViewIscsiDeploy.prepare_cleaning')
    def prepare_cleaning(self, task):
        if common.is_dynamic_allocation_enabled(task.node):
            deploy_utils.prepare_cleaning(self.oneview_client, task)
        return super(OneViewIscsiDeploy, self).prepare_cleaning(task)

    @METRICS.timer('OneViewIscsiDeploy.tear_down_cleaning')
    def tear_down_cleaning(self, task):
        if common.is_dynamic_allocation_enabled(task.node):
            deploy_utils.tear_down_cleaning(self.oneview_client, task)
        super(OneViewIscsiDeploy, self).tear_down_cleaning(task)


# NOTE (thiagop): We overwrite this interface because we cannot change the boot
# device of OneView managed blades while they are still powered on. We moved
# the call of node_set_boot_device from reboot_to_instance to
# reboot_and_finish_deploy and changed the behavior to shutdown the node before
# doing it.
# TODO(thiagop): remove this interface once bug/1503855 is fixed
class OneViewAgentDeployMixin(object):

    @METRICS.timer('OneViewAgentDeployMixin.reboot_to_instance')
    def reboot_to_instance(self, task, **kwargs):
        task.process_event('resume')
        node = task.node
        error = self.check_deploy_success(node)
        if error is not None:
            # TODO(jimrollenhagen) power off if using neutron dhcp to
            #                      align with pxe driver?
            msg = (_('node %(node)s command status errored: %(error)s') %
                   {'node': node.uuid, 'error': error})
            LOG.error(msg)
            ironic_deploy_utils.set_failed_state(task, msg)
            return

        LOG.info(_LI('Image successfully written to node %s'), node.uuid)
        LOG.debug('Rebooting node %s to instance', node.uuid)

        self.reboot_and_finish_deploy(task)

        # NOTE(TheJulia): If we deployed a whole disk image, we
        # should expect a whole disk image and clean-up the tftp files
        # on-disk incase the node is disregarding the boot preference.
        # TODO(rameshg87): Not all in-tree drivers using reboot_to_instance
        # have a boot interface. So include a check for now. Remove this
        # check once all in-tree drivers have a boot interface.
        if task.driver.boot:
            task.driver.boot.clean_up_ramdisk(task)

    @METRICS.timer('OneViewAgentDeployMixin.reboot_and_finish_deploy')
    def reboot_and_finish_deploy(self, task):
        """Helper method to trigger reboot on the node and finish deploy.

        This method initiates a reboot on the node. On success, it
        marks the deploy as complete. On failure, it logs the error
        and marks deploy as failure.

        :param task: a TaskManager object containing the node
        :raises: InstanceDeployFailure, if node reboot failed.
        """
        wait = CONF.agent.post_deploy_get_power_state_retry_interval * 1000
        attempts = CONF.agent.post_deploy_get_power_state_retries + 1

        @retrying.retry(
            stop_max_attempt_number=attempts,
            retry_on_result=lambda state: state != states.POWER_OFF,
            wait_fixed=wait
        )
        def _wait_until_powered_off(task):
            return task.driver.power.get_power_state(task)

        node = task.node

        try:
            try:
                self._client.power_off(node)
                _wait_until_powered_off(task)
            except Exception as e:
                LOG.warning(
                    _LW('Failed to soft power off node %(node_uuid)s '
                        'in at least %(timeout)d seconds. Error: %(error)s'),
                    {'node_uuid': node.uuid,
                     'timeout': (wait * (attempts - 1)) / 1000,
                     'error': e})
                manager_utils.node_power_action(task, states.POWER_OFF)

            manager_utils.node_set_boot_device(task, 'disk',
                                               persistent=True)
            manager_utils.node_power_action(task, states.POWER_ON)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     'Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            agent_base_vendor.log_and_raise_deployment_error(task, msg)

        task.process_event('done')
        LOG.info(_LI('Deployment to node %s done'), task.node.uuid)


class OneViewAgentDeploy(OneViewAgentDeployMixin, agent.AgentDeploy,
                         OneViewPeriodicTasks):
    """Class for OneView Agent deployment driver."""

    oneview_driver = common.AGENT_PXE_ONEVIEW

    def __init__(self):
        super(OneViewAgentDeploy, self).__init__()
        self.oneview_client = common.get_oneview_client()

    def get_properties(self):
        return deploy_utils.get_properties()

    @METRICS.timer('OneViewAgentDeploy.validate')
    def validate(self, task):
        common.verify_node_info(task.node)
        try:
            common.validate_oneview_resources_compatibility(
                self.oneview_client, task)
        except exception.OneViewError as oneview_exc:
            raise exception.InvalidParameterValue(oneview_exc)
        super(OneViewAgentDeploy, self).validate(task)

    @METRICS.timer('OneViewAgentDeploy.prepare')
    def prepare(self, task):
        if common.is_dynamic_allocation_enabled(task.node):
            deploy_utils.prepare(self.oneview_client, task)
        super(OneViewAgentDeploy, self).prepare(task)

    @METRICS.timer('OneViewAgentDeploy.tear_down')
    def tear_down(self, task):
        if (common.is_dynamic_allocation_enabled(task.node) and
           not CONF.conductor.automated_clean):
            deploy_utils.tear_down(self.oneview_client, task)
        return super(OneViewAgentDeploy, self).tear_down(task)

    @METRICS.timer('OneViewAgentDeploy.prepare_cleaning')
    def prepare_cleaning(self, task):
        if common.is_dynamic_allocation_enabled(task.node):
            deploy_utils.prepare_cleaning(self.oneview_client, task)
        return super(OneViewAgentDeploy, self).prepare_cleaning(task)

    @METRICS.timer('OneViewAgentDeploy.tear_down_cleaning')
    def tear_down_cleaning(self, task):
        if common.is_dynamic_allocation_enabled(task.node):
            deploy_utils.tear_down_cleaning(self.oneview_client, task)
        super(OneViewAgentDeploy, self).tear_down_cleaning(task)
