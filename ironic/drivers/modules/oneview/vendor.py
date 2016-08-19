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

from oslo_log import log
import retrying

from ironic.common.i18n import _, _LI, _LW
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils

LOG = log.getLogger(__name__)
CONF = agent.CONF


# NOTE (thiagop): We overwrite this interface because we cannot change the boot
# device of OneView managed blades while they are still powered on. We moved
# the call of node_set_boot_device from reboot_to_instance to
# reboot_and_finish_deploy and changed the behavior to shutdown the node before
# doing it.
# TODO(thiagop): remove this interface once bug/1503855 is fixed
class AgentVendorInterface(agent.AgentVendorInterface):

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
            deploy_utils.set_failed_state(task, msg)
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
