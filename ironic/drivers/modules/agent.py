# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import paths
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils


agent_opts = [
    cfg.StrOpt('agent_pxe_append_params',
               default='nofb nomodeset vga=normal',
               help=_('DEPRECATED. Additional append parameters for '
                      'baremetal PXE boot. This option is deprecated and '
                      'will be removed in Mitaka release. Please use '
                      '[pxe]pxe_append_params instead.')),
    cfg.StrOpt('agent_pxe_config_template',
               default=paths.basedir_def(
                   'drivers/modules/agent_config.template'),
               help=_('DEPRECATED. Template file for PXE configuration. '
                      'This option is deprecated and will be removed '
                      'in Mitaka release. Please use [pxe]pxe_config_template '
                      'instead.')),
    cfg.IntOpt('agent_erase_devices_priority',
               help=_('Priority to run in-band erase devices via the Ironic '
                      'Python Agent ramdisk. If unset, will use the priority '
                      'set in the ramdisk (defaults to 10 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('agent_erase_devices_iterations',
               default=1,
               help=_('Number of iterations to be run for erasing devices.')),
    cfg.BoolOpt('manage_agent_boot',
                default=True,
                deprecated_name='manage_tftp',
                deprecated_group='agent',
                help=_('Whether Ironic will manage booting of the agent '
                       'ramdisk. If set to False, you will need to configure '
                       'your mechanism to allow booting the agent '
                       'ramdisk.')),
]

CONF = cfg.CONF
CONF.import_opt('my_ip', 'ironic.netconf')
CONF.register_opts(agent_opts, group='agent')

LOG = log.getLogger(__name__)


REQUIRED_PROPERTIES = {
    'deploy_kernel': _('UUID (from Glance) of the deployment kernel. '
                       'Required.'),
    'deploy_ramdisk': _('UUID (from Glance) of the ramdisk with agent that is '
                        'used at deploy time. Required.'),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES


def _time():
    """Broken out for testing."""
    return time.time()


def _get_client():
    client = agent_client.AgentClient()
    return client


def build_agent_options(node):
    """Build the options to be passed to the agent ramdisk.

    :param node: an ironic node object
    :returns: a dictionary containing the parameters to be passed to
        agent ramdisk.
    """
    ironic_api = (CONF.conductor.api_url or
                  keystone.get_service_url()).rstrip('/')
    agent_config_opts = {
        'ipa-api-url': ironic_api,
        'ipa-driver-name': node.driver,
        # NOTE: The below entry is a temporary workaround for bug/1433812
        'coreos.configdrive': 0,
    }
    root_device = deploy_utils.parse_root_device_hints(node)
    if root_device:
        agent_config_opts['root_device'] = root_device

    return agent_config_opts


def build_instance_info_for_deploy(task):
    """Build instance_info necessary for deploying to a node.

    :param task: a TaskManager object containing the node
    :returns: a dictionary containing the properties to be updated
        in instance_info
    :raises: exception.ImageRefValidationFailed if image_source is not
        Glance href and is not HTTP(S) URL.
    """
    node = task.node
    instance_info = node.instance_info

    image_source = instance_info['image_source']
    if service_utils.is_glance_image(image_source):
        glance = image_service.GlanceImageService(version=2,
                                                  context=task.context)
        image_info = glance.show(image_source)
        swift_temp_url = glance.swift_temp_url(image_info)
        LOG.debug('Got image info: %(info)s for node %(node)s.',
                  {'info': image_info, 'node': node.uuid})
        instance_info['image_url'] = swift_temp_url
        instance_info['image_checksum'] = image_info['checksum']
        instance_info['image_disk_format'] = image_info['disk_format']
        instance_info['image_container_format'] = (
            image_info['container_format'])
    else:
        try:
            image_service.HttpImageService().validate_href(image_source)
        except exception.ImageRefValidationFailed:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Agent deploy supports only HTTP(S) URLs as "
                              "instance_info['image_source']. Either %s "
                              "is not a valid HTTP(S) URL or "
                              "is not reachable."), image_source)
        instance_info['image_url'] = image_source

    return instance_info


class AgentDeploy(base.DeployInterface):
    """Interface for deploy-related actions."""

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the properties of the supplied node
        contain the required information for this driver to deploy images to
        the node.

        :param task: a TaskManager instance
        :raises: MissingParameterValue
        """
        if CONF.agent.manage_agent_boot:
            task.driver.boot.validate(task)

        node = task.node
        params = {}
        image_source = node.instance_info.get('image_source')
        params['instance_info.image_source'] = image_source
        error_msg = _('Node %s failed to validate deploy image info. Some '
                      'parameters were missing') % node.uuid
        deploy_utils.check_for_missing_params(params, error_msg)

        if not service_utils.is_glance_image(image_source):
            if not node.instance_info.get('image_checksum'):
                raise exception.MissingParameterValue(_(
                    "image_source's image_checksum must be provided in "
                    "instance_info for node %s") % node.uuid)

        is_whole_disk_image = node.driver_internal_info.get(
            'is_whole_disk_image')
        # TODO(sirushtim): Remove once IPA has support for partition images.
        if is_whole_disk_image is False:
            raise exception.InvalidParameterValue(_(
                "Node %(node)s is configured to use the %(driver)s driver "
                "which currently does not support deploying partition "
                "images.") % {'node': node.uuid, 'driver': node.driver})

        # Validate the root device hints
        deploy_utils.parse_root_device_hints(node)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Perform a deployment to a node.

        Perform the necessary work to deploy an image onto the specified node.
        This method will be called after prepare(), which may have already
        performed any preparatory steps, such as pre-caching some data for the
        node.

        :param task: a TaskManager instance.
        :returns: status of the deploy. One of ironic.common.states.
        """
        manager_utils.node_power_action(task, states.REBOOT)
        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        :param task: a TaskManager instance.
        :returns: status of the deploy. One of ironic.common.states.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        """
        # Nodes deployed by AgentDeploy always boot from disk now. So there
        # is nothing to be done in prepare() when it's called during
        # take over.
        node = task.node
        if node.provision_state != states.ACTIVE:
            node.instance_info = build_instance_info_for_deploy(task)
            node.save()
            if CONF.agent.manage_agent_boot:
                deploy_opts = build_agent_options(node)
                task.driver.boot.prepare_ramdisk(task, deploy_opts)

    def clean_up(self, task):
        """Clean up the deployment environment for this node.

        If preparation of the deployment environment ahead of time is possible,
        this method should be implemented by the driver. It should erase
        anything cached by the `prepare` method.

        If implemented, this method must be idempotent. It may be called
        multiple times for the same node on the same conductor, and it may be
        called by multiple conductors in parallel. Therefore, it must not
        require an exclusive lock.

        This method is called before `tear_down`.

        :param task: a TaskManager instance.
        """
        if CONF.agent.manage_agent_boot:
            task.driver.boot.clean_up_ramdisk(task)

    def take_over(self, task):
        """Take over management of this node from a dead conductor.

        Since this deploy interface only does local boot, there's no need
        for this conductor to do anything when it takes over management
        of this node.

        :param task: a TaskManager instance.
        """
        pass

    def get_clean_steps(self, task):
        """Get the list of clean steps from the agent.

        :param task: a TaskManager object containing the node

        :returns: A list of clean step dictionaries
        """
        steps = deploy_utils.agent_get_clean_steps(task)
        if CONF.agent.agent_erase_devices_priority is not None:
            for step in steps:
                if (step.get('step') == 'erase_devices' and
                        step.get('interface') == 'deploy'):
                    # Override with operator set priority
                    step['priority'] = CONF.agent.agent_erase_devices_priority
        return steps

    def execute_clean_step(self, task, step):
        """Execute a clean step asynchronously on the agent.

        :param task: a TaskManager object containing the node
        :param step: a clean step dictionary to execute
        :raises: NodeCleaningFailure if the agent does not return a command
            status
        :returns: states.CLEANWAIT to signify the step will be completed async
        """
        return deploy_utils.agent_execute_clean_step(task, step)

    def prepare_cleaning(self, task):
        """Boot into the agent to prepare for cleaning.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the previous cleaning ports cannot
            be removed or if new cleaning ports cannot be created
        :returns: states.CLEANWAIT to signify an asynchronous prepare
        """
        provider = dhcp_factory.DHCPFactory()
        # If we have left over ports from a previous cleaning, remove them
        if getattr(provider.provider, 'delete_cleaning_ports', None):
            # Allow to raise if it fails, is caught and handled in conductor
            provider.provider.delete_cleaning_ports(task)

        # Create cleaning ports if necessary
        if getattr(provider.provider, 'create_cleaning_ports', None):
            # Allow to raise if it fails, is caught and handled in conductor
            ports = provider.provider.create_cleaning_ports(task)

            # Add vif_port_id for each of the ports because some boot
            # interfaces expects these to prepare for booting ramdisk.
            for port in task.ports:
                extra_dict = port.extra
                try:
                    extra_dict['vif_port_id'] = ports[port.uuid]
                except KeyError:
                    # This is an internal error in Ironic.  All DHCP providers
                    # implementing create_cleaning_ports are supposed to
                    # return a VIF port ID for all Ironic ports.  But
                    # that doesn't seem to be true here.
                    error = (_("When creating cleaning ports, DHCP provider "
                               "didn't return VIF port ID for %s") % port.uuid)
                    raise exception.NodeCleaningFailure(
                        node=task.node.uuid, reason=error)
                else:
                    port.extra = extra_dict
                    port.save()

        # Append required config parameters to node's driver_internal_info
        # to pass to IPA.
        deploy_utils.agent_add_clean_params(task)

        if CONF.agent.manage_agent_boot:
            ramdisk_opts = build_agent_options(task.node)
            task.driver.boot.prepare_ramdisk(task, ramdisk_opts)
        manager_utils.node_power_action(task, states.REBOOT)

        # Tell the conductor we are waiting for the agent to boot.
        return states.CLEANWAIT

    def tear_down_cleaning(self, task):
        """Clean up the PXE and DHCP files after cleaning.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the cleaning ports cannot be
            removed
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        if CONF.agent.manage_agent_boot:
            task.driver.boot.clean_up_ramdisk(task)

        # If we created cleaning ports, delete them
        provider = dhcp_factory.DHCPFactory()
        if getattr(provider.provider, 'delete_cleaning_ports', None):
            # Allow to raise if it fails, is caught and handled in conductor
            provider.provider.delete_cleaning_ports(task)

            for port in task.ports:
                if 'vif_port_id' in port.extra:
                    extra_dict = port.extra
                    extra_dict.pop('vif_port_id', None)
                    port.extra = extra_dict
                    port.save()


class AgentVendorInterface(agent_base_vendor.BaseAgentVendor):

    def deploy_has_started(self, task):
        commands = self._client.get_commands_status(task.node)

        for command in commands:
            if command['command_name'] == 'prepare_image':
                # deploy did start at some point
                return True
        return False

    def deploy_is_done(self, task):
        commands = self._client.get_commands_status(task.node)
        if not commands:
            return False

        last_command = commands[-1]

        if last_command['command_name'] != 'prepare_image':
            # catches race condition where prepare_image is still processing
            # so deploy hasn't started yet
            return False

        if last_command['command_status'] != 'RUNNING':
            return True

        return False

    @task_manager.require_exclusive_lock
    def continue_deploy(self, task, **kwargs):
        task.process_event('resume')
        node = task.node
        image_source = node.instance_info.get('image_source')
        LOG.debug('Continuing deploy for node %(node)s with image %(img)s',
                  {'node': node.uuid, 'img': image_source})

        image_info = {
            'id': image_source.split('/')[-1],
            'urls': [node.instance_info['image_url']],
            'checksum': node.instance_info['image_checksum'],
            # NOTE(comstud): Older versions of ironic do not set
            # 'disk_format' nor 'container_format', so we use .get()
            # to maintain backwards compatibility in case code was
            # upgraded in the middle of a build request.
            'disk_format': node.instance_info.get('image_disk_format'),
            'container_format': node.instance_info.get(
                'image_container_format')
        }

        # Tell the client to download and write the image with the given args
        self._client.prepare_image(node, image_info)

        task.process_event('wait')

    def check_deploy_success(self, node):
        # should only ever be called after we've validated that
        # the prepare_image command is complete
        command = self._client.get_commands_status(node)[-1]
        if command['command_status'] == 'FAILED':
            return command['command_error']

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

        manager_utils.node_set_boot_device(task, 'disk', persistent=True)
        self.reboot_and_finish_deploy(task)

        # NOTE(TheJulia): If we deployed a whole disk image, we
        # should expect a whole disk image and clean-up the tftp files
        # on-disk incase the node is disregarding the boot preference.
        # TODO(rameshg87): Not all in-tree drivers using reboot_to_instance
        # have a boot interface. So include a check for now. Remove this
        # check once all in-tree drivers have a boot interface.
        if hasattr(task.driver, 'boot'):
            task.driver.boot.clean_up_ramdisk(task)
