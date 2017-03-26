# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
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
iLO Deploy Driver(s) and supporting methods.
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import iscsi_deploy

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class IloIscsiDeployMixin(object):

    @METRICS.timer('IloIscsiDeployMixin.tear_down')
    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Power off the node. All actual clean-up is done in the clean_up()
        method which should be called separately.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        :raises: IloOperationError, if some operation on iLO failed.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        ilo_boot.disable_secure_boot_if_supported(task)
        return super(IloIscsiDeployMixin, self).tear_down(task)

    @METRICS.timer('IloIscsiDeployMixin.prepare_cleaning')
    def prepare_cleaning(self, task):
        """Boot into the agent to prepare for cleaning.

        :param task: a TaskManager object containing the node
        :returns: states.CLEANWAIT to signify an asynchronous prepare.
        :raises NodeCleaningFailure: if the previous cleaning ports cannot
            be removed or if new cleaning ports cannot be created
        :raises: IloOperationError, if some operation on iLO failed.
        """
        # Powering off the Node before initiating boot for node cleaning.
        # If node is in system POST, setting boot device fails.
        manager_utils.node_power_action(task, states.POWER_OFF)
        return super(IloIscsiDeployMixin, self).prepare_cleaning(task)

    @METRICS.timer('IloIscsiDeployMixin.continue_deploy')
    @task_manager.require_exclusive_lock
    def continue_deploy(self, task, **kwargs):
        """Method invoked when deployed with the IPA ramdisk.

        This method is invoked during a heartbeat from an agent when
        the node is in wait-call-back state.
        This updates boot mode and secure boot settings, if required.
        """
        ilo_common.update_boot_mode(task)
        ilo_common.update_secure_boot_mode(task, True)
        super(IloIscsiDeployMixin, self).continue_deploy(task, **kwargs)


class IloPXEDeploy(IloIscsiDeployMixin, iscsi_deploy.ISCSIDeploy):

    @METRICS.timer('IloPXEDeploy.prepare')
    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        If the node's 'capabilities' property includes a boot_mode, that
        boot mode will be applied for the node. Otherwise, the existing
        boot mode of the node is used in the node's 'capabilities' property.

        PXEDeploys' prepare method is then called, to prepare the deploy
        environment for the node

        :param task: a TaskManager instance containing the node to act on.
        :raises: IloOperationError, if some operation on iLO failed.
        :raises: InvalidParameterValue, if some information is invalid.
        """
        if task.node.provision_state == states.DEPLOYING:
            ilo_boot.prepare_node_for_deploy(task)

        super(IloPXEDeploy, self).prepare(task)

    @METRICS.timer('IloPXEDeploy.deploy')
    def deploy(self, task):
        """Start deployment of the task's node.

        This method sets the boot device to 'NETWORK' and then calls
        PXEDeploy's deploy method to deploy on the given node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        """
        manager_utils.node_set_boot_device(task, boot_devices.PXE)
        return super(IloPXEDeploy, self).deploy(task)
