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
from ironic.drivers.modules import agent_base

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class AutodetectDeploy(agent_base.HeartbeatMixin, base.DeployInterface):
    """Deploy interface that auto-detects the appropriate deployment method.

    This interface never performs any real work itself: it only resolves
    which concrete deploy interface should be used and switches the node
    over to it. The conductor calls switch_interface() at the start of
    every flow which may act on a node, so by the time any work method
    would run, a concrete interface is in place. Every method which would
    otherwise do actual work therefore fails loudly rather than silently
    doing nothing.

    Inherits from HeartbeatMixin so that heartbeats received while
    autodetect is the active deploy interface (e.g. during inspection)
    store agent_url in driver_internal_info.  Without this, fast-track
    deployment fails with AgentConnectionFailed because agent_url was
    never recorded.
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

    def _fail_not_switched(self, task, method_name):
        """Raise a clear error when a work method is called on autodetect.

        :param task: A TaskManager instance containing the node to act on.
        :param method_name: Name of the method which was called.
        :raises: InstanceDeployFailure always.
        """
        raise exception.InstanceDeployFailure(
            _("%(method)s was called on the autodetect deploy interface for "
              "node %(node)s, which does not perform any deployment itself. "
              "The autodetect interface did not switch to a concrete "
              "interface during switch_interface(). This indicates a bug or "
              "misconfiguration.")
            % {'method': method_name, 'node': task.node.uuid})

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
        interface, _name, _supports = self._create_switchable_interface(task)
        return interface.validate(task)

    @METRICS.timer('AutodetectDeploy.deploy')
    @base.deploy_step(priority=100)
    def deploy(self, task):
        """Perform a deployment to the task's node.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'deploy')

    @METRICS.timer('AutodetectDeploy.prepare')
    def prepare(self, task):
        """Prepare the deployment environment for the task's node.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'prepare')

    @METRICS.timer('AutodetectDeploy.take_over')
    def take_over(self, task):
        """Take over management of this task's node.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'take_over')

    @METRICS.timer('AutodetectDeploy.tear_down')
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'tear_down')

    @METRICS.timer('AutodetectDeploy.clean_up')
    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'clean_up')

    @METRICS.timer('AutodetectDeploy.prepare_cleaning')
    def prepare_cleaning(self, task):
        """Prepare the node for cleaning tasks.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'prepare_cleaning')

    @METRICS.timer('AutodetectDeploy.tear_down_cleaning')
    def tear_down_cleaning(self, task):
        """Tear down after cleaning is completed.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'tear_down_cleaning')

    @METRICS.timer('AutodetectDeploy.prepare_service')
    def prepare_service(self, task):
        """Prepare the node for servicing tasks.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'prepare_service')

    @METRICS.timer('AutodetectDeploy.tear_down_service')
    def tear_down_service(self, task):
        """Tear down after servicing is completed.

        Never reached: the conductor switches to a concrete interface
        first. See the class docstring.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InstanceDeployFailure always.
        """
        self._fail_not_switched(task, 'tear_down_service')

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
            if task.node.instance_info.get('image_source'):
                LOG.warning("No deploy interfaces in "
                            "autodetect_deploy_interfaces are supported for "
                            "this node/image. Using last interface: %s",
                            interface_name)
            else:
                # No image to detect from, which is normal outside of a
                # deployment, e.g. when cleaning a node which has never
                # been deployed. The fallback is the expected outcome.
                LOG.debug("No image to detect a deploy interface from for "
                          "node %(node)s. Using last interface: %(iface)s",
                          {'node': task.node.uuid, 'iface': interface_name})

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
