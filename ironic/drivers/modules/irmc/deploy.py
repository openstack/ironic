# Copyright 2015 FUJITSU LIMITED
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
iRMC Deploy Driver
"""

from oslo_log import log as logging

from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.irmc import boot as irmc_boot


LOG = logging.getLogger(__name__)


class IRMCVirtualMediaAgentDeploy(base.DeployInterface):

    def __init__(self):
        """Constructor of IRMCVirtualMediaAgentDeploy.

        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if config option has invalid value.
        """
        irmc_boot.check_share_fs_mounted()
        super(IRMCVirtualMediaAgentDeploy, self).__init__()

    """Interface for Agent deploy-related actions."""
    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return irmc_boot.COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        :param task: a TaskManager instance
        :raises: IRMCSharedFileSystemNotMounted, if shared file system is
            not mounted.
        :raises: InvalidParameterValue, if config option has invalid value.
        :raises: MissingParameterValue if some parameters are missing.
        """
        irmc_boot.check_share_fs_mounted()
        irmc_boot.parse_driver_info(task.node)
        deploy_utils.validate_capabilities(task.node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Prepares the options for the agent ramdisk and sets the node to boot
        from virtual media cdrom.

        :param task: a TaskManager instance.
        :returns: states.DEPLOYWAIT
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: IRMCOperationError, if some operation on iRMC fails.
        """
        deploy_ramdisk_opts = deploy_utils.build_agent_options(task.node)
        irmc_boot.setup_deploy_iso(task, deploy_ramdisk_opts)
        manager_utils.node_power_action(task, states.REBOOT)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: states.DELETED
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        node = task.node
        node.instance_info = agent.build_instance_info_for_deploy(task)
        node.save()

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        Ejects the attached virtual media from the iRMC and also removes
        the floppy image from the share file system, if it exists.

        :param task: a TaskManager instance.
        """
        irmc_boot.cleanup_vmedia_boot(task)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        :param task: a TaskManager instance.
        """
        pass


class IRMCVirtualMediaAgentVendorInterface(agent.AgentVendorInterface):
    """Interface for vendor passthru related actions."""

    def reboot_to_instance(self, task, **kwargs):
        node = task.node
        LOG.debug('Preparing to reboot to instance for node %s',
                  node.uuid)

        irmc_boot.cleanup_vmedia_boot(task)

        super(IRMCVirtualMediaAgentVendorInterface,
              self).reboot_to_instance(task, **kwargs)
