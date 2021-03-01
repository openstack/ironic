# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
PXE Boot Interface
"""

from ironic_lib import metrics_utils
from oslo_log import log as logging

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import pxe_base
LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class PXEBoot(pxe_base.PXEBaseMixin, base.BootInterface):

    capabilities = ['ramdisk_boot', 'pxe_boot']


class PXERamdiskDeploy(agent_base.AgentBaseMixin, agent_base.HeartbeatMixin,
                       base.DeployInterface):

    def get_properties(self):
        return {}

    def validate(self, task):
        if 'ramdisk_boot' not in task.driver.boot.capabilities:
            raise exception.InvalidParameterValue(
                message=_('Invalid configuration: The boot interface '
                          'must have the `ramdisk_boot` capability. '
                          'You are using an incompatible boot interface.'))
        task.driver.boot.validate(task)

        # Validate node capabilities
        deploy_utils.validate_capabilities(task.node)

    @METRICS.timer('RamdiskDeploy.deploy')
    @base.deploy_step(priority=100)
    @task_manager.require_exclusive_lock
    def deploy(self, task):
        if ('configdrive' in task.node.instance_info
                and 'ramdisk_boot_configdrive' not in
                task.driver.boot.capabilities):
            # TODO(dtantsur): make it an actual error?
            LOG.warning('A configuration drive is present in the ramdisk '
                        'deployment request of node %(node)s with boot '
                        'interface %(drv)s. The configuration drive will be '
                        'ignored for this deployment.',
                        {'node': task.node, 'drv': task.node.boot_interface})
        manager_utils.node_power_action(task, states.POWER_OFF)
        # Tenant neworks must enable connectivity to the boot
        # location, as reboot() can otherwise be very problematic.
        # IDEA(TheJulia): Maybe a "trusted environment" mode flag
        # that we otherwise fail validation on for drivers that
        # require explicit security postures.
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.configure_tenant_networks(task)

        # calling boot.prepare_instance will also set the node
        # to PXE boot, and update PXE templates accordingly
        task.driver.boot.prepare_instance(task)

        # Power-on the instance, with PXE prepared, we're done.
        manager_utils.node_power_action(task, states.POWER_ON)
        LOG.info('Deployment setup for node %s done', task.node.uuid)
        return None

    @METRICS.timer('RamdiskDeploy.prepare')
    @task_manager.require_exclusive_lock
    def prepare(self, task):
        node = task.node
        # Log a warning if the boot_option is wrong... and
        # otherwise reset it.
        boot_option = deploy_utils.get_boot_option(node)
        if boot_option != 'ramdisk':
            LOG.warning('Incorrect "boot_option" set for node %(node)s '
                        'and will be overridden to "ramdisk" as to '
                        'match the deploy interface. Found: %(boot_opt)s.',
                        {'node': node.uuid,
                         'boot_opt': boot_option})
            i_info = task.node.instance_info
            i_info.update({'capabilities': {'boot_option': 'ramdisk'}})
            node.instance_info = i_info
            node.save()

        deploy_utils.populate_storage_driver_internal_info(task)
        if node.provision_state == states.DEPLOYING:
            # Ask the network interface to validate itself so
            # we can ensure we are able to proceed.
            task.driver.network.validate(task)

            manager_utils.node_power_action(task, states.POWER_OFF)
            # NOTE(TheJulia): If this was any other interface, we would
            # unconfigure tenant networks, add provisioning networks, etc.
            task.driver.storage.attach_volumes(task)
        if node.provision_state in (states.ACTIVE, states.UNRESCUING):
            # In the event of takeover or unrescue.
            task.driver.boot.prepare_instance(task)


class PXEAnacondaDeploy(agent_base.AgentBaseMixin, agent_base.HeartbeatMixin,
                        base.DeployInterface):

    def get_properties(self):
        return {}

    def validate(self, task):
        task.driver.boot.validate(task)

    @METRICS.timer('AnacondaDeploy.deploy')
    @base.deploy_step(priority=100)
    @task_manager.require_exclusive_lock
    def deploy(self, task):
        manager_utils.node_power_action(task, states.POWER_OFF)
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.configure_tenant_networks(task)

        # calling boot.prepare_instance will also set the node
        # to PXE boot, and update PXE templates accordingly
        task.driver.boot.prepare_instance(task)

        # Power-on the instance, with PXE prepared, we're done.
        manager_utils.node_power_action(task, states.POWER_ON)
        LOG.info('Deployment setup for node %s done', task.node.uuid)
        return None

    @METRICS.timer('AnacondaDeploy.prepare')
    @task_manager.require_exclusive_lock
    def prepare(self, task):
        node = task.node

        deploy_utils.populate_storage_driver_internal_info(task)
        if node.provision_state == states.DEPLOYING:
            # Ask the network interface to validate itself so
            # we can ensure we are able to proceed.
            task.driver.network.validate(task)

            manager_utils.node_power_action(task, states.POWER_OFF)
            # NOTE(TheJulia): If this was any other interface, we would
            # unconfigure tenant networks, add provisioning networks, etc.
            task.driver.storage.attach_volumes(task)
        if node.provision_state in (states.ACTIVE, states.UNRESCUING):
            # In the event of takeover or unrescue.
            task.driver.boot.prepare_instance(task)

    def deploy_has_started(self, task):
        agent_status = task.node.driver_internal_info.get('agent_status')
        if agent_status == 'start':
            return True
        return False

    def deploy_is_done(self, task):
        agent_status = task.node.driver_internal_info.get('agent_status')
        if agent_status == 'end':
            return True
        return False

    def should_manage_boot(self, task):
        return False

    def reboot_to_instance(self, task):
        node = task.node
        try:
            # anaconda deploy will install the bootloader and the node is ready
            # to boot from disk.

            deploy_utils.try_set_boot_device(task, boot_devices.DISK)
        except Exception as e:
            msg = (_("Failed to change the boot device to %(boot_dev)s "
                     "when deploying node %(node)s. Error: %(error)s") %
                   {'boot_dev': boot_devices.DISK, 'node': node.uuid,
                    'error': e})
            agent_base.log_and_raise_deployment_error(task, msg)

        try:
            self.clean_up(task)
            manager_utils.node_power_action(task, states.POWER_OFF)
            task.driver.network.remove_provisioning_network(task)
            task.driver.network.configure_tenant_networks(task)
            manager_utils.node_power_action(task, states.POWER_ON)
            node.provision_state = states.ACTIVE
            node.save()
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     'Error: %(error)s') %
                   {'node': node.uuid, 'error': e})
            agent_base.log_and_raise_deployment_error(task, msg)

    def _heartbeat_deploy_wait(self, task):
        node = task.node
        agent_status_message = node.driver_internal_info.get(
            'agent_status_message'
        )
        msg = {'node_id': node.uuid,
               'agent_status_message': agent_status_message}

        if self.deploy_has_started(task):
            LOG.info('The deploy on node %(node_id)s has started. Anaconda '
                     'returned following message: '
                     '%(agent_status_message)s ', msg)
            node.touch_provisioning()

        elif self.deploy_is_done(task):
            LOG.info('The deploy on node %(node_id)s has ended. Anaconda '
                     'agent returned following message: '
                     '%(agent_status_message)s', msg)
            self.reboot_to_instance(task)
        else:
            LOG.error('The deploy on node %(node_id)s failed. Anaconda '
                      'returned following error message: '
                      '%(agent_status_message)s', msg)
            deploy_utils.set_failed_state(task, agent_status_message,
                                          collect_logs=False)
