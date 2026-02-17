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


from oslo_log import log as logging

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import metrics_utils
from ironic.conf import CONF
from ironic.drivers import base

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class AutodetectDeploy(base.DeployInterface):
    """Deploy interface that auto-detects the appropriate deployment method.

    """

    def __init__(self):
        super(AutodetectDeploy, self).__init__()

        # Validate that all autodetect interfaces are enabled
        for interface_name in CONF.autodetect_deploy_interfaces:
            self._validate_autodetect_interface(interface_name)

    def _validate_autodetect_interface(self, interface_name):
        """Validate that the autodetect interface is enabled.

        :param interface_name: Name of the deploy interface to validate.
        :raises: InvalidParameterValue if the interface is not enabled.
        """

        enabled_interfaces = CONF.enabled_deploy_interfaces
        if interface_name not in enabled_interfaces:
            raise exception.InvalidParameterValue(
                _("Deploy interface '%(interface)s' is configured in "
                    "autodetect_deploy_interfaces but is not in "
                    "enabled_deploy_interfaces. Please add '%(interface)s' "
                    "to enabled_deploy_interfaces or remove it from "
                    "autodetect_deploy_interfaces.")
                % {'interface': interface_name})

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return {}

    @METRICS.timer('AutodetectDeploy.validate')
    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method creates the deploy interface that would be switched to
        and calls its validate() method.

        :param task: A TaskManager instance containing the node to act on.
        :raises: MissingParameterValue if required parameters are missing.
        """
        switchable = self._create_switchable_interface(task)
        interface, interface_name, interface_supports = switchable
        return interface.validate(task)

    @METRICS.timer('AutodetectDeploy.deploy')
    @base.deploy_step(priority=100)
    def deploy(self, task):
        """Perform a deployment to the task's node.

        This method should not be called directly as the autodetect interface
        is expected to switch to a concrete interface during
        switch_interface(). If this is called, it means the interface switch
        did not happen.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure if deployment fails.
        """
        raise exception.InstanceDeployFailure(
            _("Autodetect deploy interface did not switch to a concrete "
              "interface during switch_interface(). This indicates a bug or "
              "misconfiguration."))

    @METRICS.timer('AutodetectDeploy.tear_down')
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: A TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        """
        # Autodetect deploy interface does not perform any actual deployment.
        # This is handled by AgentBaseMixin.tear_down() for actual deployments
        pass


    @METRICS.timer('AutodetectDeploy.prepare')
    def prepare(self, task):
        """Prepare the deployment environment for the task's node.

        """
        # Autodetect deploy interface does not perform any actual deployment.
        # This is handled by AgentBaseMixin.prepare() for actual deployments
        raise exception.InstanceDeployFailure(
            _("Autodetect deploy interface did not switch to a concrete "
              "interface during switch_interface(). This indicates a bug or "
              "misconfiguration."))

    @METRICS.timer('AutodetectDeploy.clean_up')
    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        :param task: A TaskManager instance containing the node to act on.
        """
        pass

    @METRICS.timer('AutodetectDeploy.take_over')
    def take_over(self, task):
        """Take over management of this task's node from a dead conductor.

        :param task: A TaskManager instance containing the node to act on.
        """
        pass

    def _create_switchable_interface(self, task):
        """Detect and create the deploy interface to switch to.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if the interface is not enabled.
        :returns: A tuple of (interface instance, interface name,
                  supports deploy).
        """
        node = task.node
        hw_type = driver_factory.get_hardware_type(node.driver)

        interface = None
        interface_name = None
        interface_supports = False
        for interface_name in CONF.autodetect_deploy_interfaces:
            self._validate_autodetect_interface(interface_name)
            # Get the new deploy interface instance from the factory
            interface = driver_factory.get_interface(
            hw_type, 'deploy', interface_name)

            interface_supports = interface.supports_deploy(task)
            if interface_supports:
                break

        if not interface:
            raise exception.InvalidParameterValue(
                _("No valid deploy interfaces found in "
                  "autodetect_deploy_interfaces configuration."))

        return interface, interface_name, interface_supports

    @METRICS.timer('AutodetectDeploy.switch_interface')
    def switch_interface(self, task):
        """Switch the interface to use for deployment.

        This calls supports_deploy() methods of deploy interfaces
        configured in the 'autodetect_deploy_interfaces' option, in order,
        to determine which interface is supported for the current node/image.
        The first interface that returns True from supports_deploy() is chosen.
        If no interfaces are detected as supported, the last interface in the
        list is chosen as the fallback.

        :raises: InvalidParameterValue if the interface is not enabled.
        :param task: A TaskManager instance containing the node to act on.
        """

        switchable = self._create_switchable_interface(task)
        interface, interface_name, interface_supports = switchable
        if not interface_supports:
            LOG.warning("No deploy interfaces in autodetect_deploy_interfaces "
                        "are supported for this node/image. "
                        "Using last interface: %s", interface_name)

        LOG.info("autodetect switching to deploy interface: %s",
                 interface_name)

        node = task.node
        # Save the original deploy interface to restore later
        node.set_driver_internal_info(
            'original_deploy_interface',
            task.node.deploy_interface)
        # Update the node's deploy interface name
        node.deploy_interface = interface_name
        # Replace the deploy interface on the driver
        task.driver.deploy = interface
        node.save()
