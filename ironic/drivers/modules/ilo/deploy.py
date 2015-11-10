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

from oslo_config import cfg
from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

clean_opts = [
    cfg.IntOpt('clean_priority_erase_devices',
               help=_('Priority for erase devices clean step. If unset, '
                      'it defaults to 10. If set to 0, the step will be '
                      'disabled and will not run during cleaning.'))
]

CONF.import_opt('pxe_append_params', 'ironic.drivers.modules.iscsi_deploy',
                group='pxe')
CONF.import_opt('swift_ilo_container', 'ironic.drivers.modules.ilo.common',
                group='ilo')
CONF.register_opts(clean_opts, group='ilo')


def _prepare_agent_vmedia_boot(task):
    """Ejects virtual media devices and prepares for vmedia boot."""
    # Eject all virtual media devices, as we are going to use them
    # during deploy.
    ilo_common.eject_vmedia_devices(task)

    deploy_ramdisk_opts = deploy_utils.build_agent_options(task.node)
    deploy_iso = task.node.driver_info['ilo_deploy_iso']
    ilo_common.setup_vmedia(task, deploy_iso, deploy_ramdisk_opts)
    manager_utils.node_power_action(task, states.REBOOT)


def _disable_secure_boot(task):
    """Disables secure boot on node, if secure boot is enabled on node.

    This method checks if secure boot is enabled on node. If enabled, it
    disables same and returns True.

    :param task: a TaskManager instance containing the node to act on.
    :returns: It returns True, if secure boot was successfully disabled on
              the node.
              It returns False, if secure boot on node is in disabled state
              or if secure boot feature is not supported by the node.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    cur_sec_state = False
    try:
        cur_sec_state = ilo_common.get_secure_boot_mode(task)
    except exception.IloOperationNotSupported:
        LOG.debug('Secure boot mode is not supported for node %s',
                  task.node.uuid)
        return False

    if cur_sec_state:
        LOG.debug('Disabling secure boot for node %s', task.node.uuid)
        ilo_common.set_secure_boot_mode(task, False)
        return True
    return False


def _prepare_node_for_deploy(task):
    """Common preparatory steps for all iLO drivers.

    This method performs common preparatory steps required for all drivers.
    1. Power off node
    2. Disables secure boot, if it is in enabled state.
    3. Updates boot_mode capability to 'uefi' if secure boot is requested.
    4. Changes boot mode of the node if secure boot is disabled currently.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    manager_utils.node_power_action(task, states.POWER_OFF)

    # Boot mode can be changed only if secure boot is in disabled state.
    # secure boot and boot mode cannot be changed together.
    change_boot_mode = True

    # Disable secure boot on the node if it is in enabled state.
    if _disable_secure_boot(task):
        change_boot_mode = False

    if change_boot_mode:
        ilo_common.update_boot_mode(task)
    else:
        # Need to update boot mode that will be used during deploy, if one is
        # not provided.
        # Since secure boot was disabled, we are in 'uefi' boot mode.
        if deploy_utils.get_boot_mode_for_deploy(task.node) is None:
            instance_info = task.node.instance_info
            instance_info['deploy_boot_mode'] = 'uefi'
            task.node.instance_info = instance_info
            task.node.save()


def _disable_secure_boot_if_supported(task):
    """Disables secure boot on node, does not throw if its not supported.

    :param task: a TaskManager instance containing the node to act on.
    :raises: IloOperationError, if some operation on iLO failed.
    """
    try:
        ilo_common.update_secure_boot_mode(task, False)
    # We need to handle IloOperationNotSupported exception so that if
    # the user has incorrectly specified the Node capability
    # 'secure_boot' to a node that does not have that capability and
    # attempted deploy. Handling this exception here, will help the
    # user to tear down such a Node.
    except exception.IloOperationNotSupported:
        LOG.warning(_LW('Secure boot mode is not supported for node %s'),
                    task.node.uuid)


class IloVirtualMediaIscsiDeploy(iscsi_deploy.ISCSIDeploy):

    def get_properties(self):
        return {}

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
        _disable_secure_boot_if_supported(task)
        return super(IloVirtualMediaIscsiDeploy, self).tear_down(task)

    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: IloOperationError, if some operation on iLO failed.
        """
        if task.node.provision_state != states.ACTIVE:
            _prepare_node_for_deploy(task)

        super(IloVirtualMediaIscsiDeploy, self).prepare(task)


class IloVirtualMediaAgentDeploy(base.DeployInterface):
    """Interface for deploy-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return ilo_boot.COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        :param task: a TaskManager instance
        :raises: MissingParameterValue if some parameters are missing.
        """

        deploy_utils.validate_capabilities(task.node)
        ilo_boot.parse_driver_info(task.node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Prepares the options for the agent ramdisk and sets the node to boot
        from virtual media cdrom.

        :param task: a TaskManager instance.
        :returns: states.DEPLOYWAIT
        :raises: ImageCreationFailed, if it failed while creating the floppy
            image.
        :raises: IloOperationError, if some operation on iLO fails.
        """
        _prepare_agent_vmedia_boot(task)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: states.DELETED
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        _disable_secure_boot_if_supported(task)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        if task.node.provision_state != states.ACTIVE:
            node = task.node
            node.instance_info = agent.build_instance_info_for_deploy(task)
            node.save()
            _prepare_node_for_deploy(task)

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        Ejects the attached virtual media from the iLO and also removes
        the floppy image from Swift, if it exists.

        :param task: a TaskManager instance.
        """
        ilo_common.cleanup_vmedia_boot(task)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        :param task: a TaskManager instance.
        """
        pass

    def get_clean_steps(self, task):
        """Get the list of clean steps from the agent.

        :param task: a TaskManager object containing the node
        :returns: A list of clean step dictionaries
        """
        new_priorities = {
            'erase_devices': CONF.ilo.clean_priority_erase_devices,
        }
        return deploy_utils.agent_get_clean_steps(
            task, interface='deploy',
            override_priorities=new_priorities)

    def execute_clean_step(self, task, step):
        """Execute a clean step asynchronously on the agent.

        :param task: a TaskManager object containing the node
        :param step: a clean step dictionary to execute
        :returns: states.CLEANWAIT to signify the step will be completed async
        """
        return deploy_utils.agent_execute_clean_step(task, step)

    def prepare_cleaning(self, task):
        """Boot into the agent to prepare for cleaning."""
        # Create cleaning ports if necessary
        provider = dhcp_factory.DHCPFactory().provider

        # If we have left over ports from a previous cleaning, remove them
        if getattr(provider, 'delete_cleaning_ports', None):
            provider.delete_cleaning_ports(task)

        if getattr(provider, 'create_cleaning_ports', None):
            provider.create_cleaning_ports(task)

        # Append required config parameters to node's driver_internal_info
        # to pass to IPA.
        deploy_utils.agent_add_clean_params(task)

        _prepare_agent_vmedia_boot(task)
        # Tell the conductor we are waiting for the agent to boot.
        return states.CLEANWAIT

    def tear_down_cleaning(self, task):
        """Clean up the PXE and DHCP files after cleaning."""
        manager_utils.node_power_action(task, states.POWER_OFF)
        # If we created cleaning ports, delete them
        provider = dhcp_factory.DHCPFactory().provider
        if getattr(provider, 'delete_cleaning_ports', None):
            provider.delete_cleaning_ports(task)


class IloPXEDeploy(iscsi_deploy.ISCSIDeploy):

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
        if task.node.provision_state != states.ACTIVE:
            _prepare_node_for_deploy(task)

            # Check if 'boot_option' is compatible with 'boot_mode' and image.
            # Whole disk image deploy is not supported in UEFI boot mode if
            # 'boot_option' is not 'local'.
            # If boot_mode is not set in the node properties/capabilities then
            # PXEDeploy.validate() would pass.
            # Boot mode gets updated in prepare stage. It is possible that the
            # deploy boot mode is 'uefi' after call to update_boot_mode().
            # Hence a re-check is required here.
            pxe.validate_boot_option_for_uefi(task.node)

        super(IloPXEDeploy, self).prepare(task)

    def deploy(self, task):
        """Start deployment of the task's node.

        This method sets the boot device to 'NETWORK' and then calls
        PXEDeploy's deploy method to deploy on the given node.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYWAIT.
        """
        manager_utils.node_set_boot_device(task, boot_devices.PXE)
        return super(IloPXEDeploy, self).deploy(task)

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: states.DELETED
        """
        # Powering off the Node before disabling secure boot. If the node is
        # is in POST, disable secure boot will fail.
        manager_utils.node_power_action(task, states.POWER_OFF)
        _disable_secure_boot_if_supported(task)
        return super(IloPXEDeploy, self).tear_down(task)


class IloConsoleInterface(ipmitool.IPMIShellinaboxConsole):
    """A ConsoleInterface that uses ipmitool and shellinabox."""

    def get_properties(self):
        d = ilo_common.REQUIRED_PROPERTIES.copy()
        d.update(ilo_common.CONSOLE_PROPERTIES)
        return d

    def validate(self, task):
        """Validate the Node console info.

        :param task: a task from TaskManager.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue when a required parameter is missing

        """
        node = task.node
        driver_info = ilo_common.parse_driver_info(node)
        if 'console_port' not in driver_info:
            raise exception.MissingParameterValue(_(
                "Missing 'console_port' parameter in node's driver_info."))

        ilo_common.update_ipmi_properties(task)
        super(IloConsoleInterface, self).validate(task)
