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

import os
import time

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import fileutils

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import paths
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache


agent_opts = [
    cfg.StrOpt('agent_pxe_append_params',
               default='nofb nomodeset vga=normal',
               help=_('Additional append parameters for baremetal PXE boot.')),
    cfg.StrOpt('agent_pxe_config_template',
               default=paths.basedir_def(
                   'drivers/modules/agent_config.template'),
               help=_('Template file for PXE configuration.')),
    cfg.IntOpt('agent_erase_devices_priority',
               help=_('Priority to run in-band erase devices via the Ironic '
                      'Python Agent ramdisk. If unset, will use the priority '
                      'set in the ramdisk (defaults to 10 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('agent_erase_devices_iterations',
               default=1,
               help=_('Number of iterations to be run for erasing devices.')),
    cfg.BoolOpt('manage_tftp',
                default=True,
                help=_('Whether Ironic will manage TFTP files for the deploy '
                       'ramdisks. If set to False, you will need to configure '
                       'your own TFTP server that allows booting the deploy '
                       'ramdisks.')),
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


def _build_pxe_config_options(node, pxe_info):
    """Builds the pxe config options for booting agent.

    This method builds the config options to be replaced on
    the agent pxe config template.

    :param node: an ironic node object
    :param pxe_info: A dict containing the 'deploy_kernel' and
        'deploy_ramdisk' for the agent pxe config template.
    :returns: a dict containing the options to be applied on
    the agent pxe config template.
    """
    agent_config_opts = {
        'deployment_aki_path': pxe_info['deploy_kernel'][1],
        'deployment_ari_path': pxe_info['deploy_ramdisk'][1],
        'pxe_append_params': CONF.agent.agent_pxe_append_params,
    }
    agent_opts = build_agent_options(node)
    agent_config_opts.update(agent_opts)
    return agent_config_opts


def _get_tftp_image_info(node):
    return pxe_utils.get_deploy_kr_info(node.uuid, node.driver_info)


def _driver_uses_pxe(driver):
    """A quick hack to check if driver uses pxe."""
    # If driver.deploy says I need deploy_kernel and deploy_ramdisk,
    # then it's using PXE boot.
    properties = driver.deploy.get_properties()
    return (('deploy_kernel' in properties) and
            ('deploy_ramdisk' in properties))


@image_cache.cleanup(priority=25)
class AgentTFTPImageCache(image_cache.ImageCache):
    def __init__(self):
        super(AgentTFTPImageCache, self).__init__(
            CONF.pxe.tftp_master_path,
            # MiB -> B
            CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            CONF.pxe.image_cache_ttl * 60)


def _cache_tftp_images(ctx, node, pxe_info):
    """Fetch the necessary kernels and ramdisks for the instance."""
    fileutils.ensure_tree(
        os.path.join(CONF.pxe.tftp_root, node.uuid))
    LOG.debug("Fetching kernel and ramdisk for node %s",
              node.uuid)
    deploy_utils.fetch_images(ctx, AgentTFTPImageCache(), pxe_info.values())


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


def _prepare_pxe_boot(task):
    """Prepare the files required for PXE booting the agent."""
    if CONF.agent.manage_tftp:
        pxe_info = _get_tftp_image_info(task.node)
        pxe_options = _build_pxe_config_options(task.node, pxe_info)
        pxe_utils.create_pxe_config(task,
                                    pxe_options,
                                    CONF.agent.agent_pxe_config_template)
        _cache_tftp_images(task.context, task.node, pxe_info)


def _do_pxe_boot(task, ports=None):
    """Reboot the node into the PXE ramdisk.

    :param task: a TaskManager instance
    :param ports: a list of Neutron port dicts to update DHCP options on. If
        None, will get the list of ports from the Ironic port objects.
    """
    dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
    provider = dhcp_factory.DHCPFactory()
    provider.update_dhcp(task, dhcp_opts, ports)
    manager_utils.node_set_boot_device(task, boot_devices.PXE, persistent=True)
    manager_utils.node_power_action(task, states.REBOOT)


def _clean_up_pxe(task):
    """Clean up left over PXE and DHCP files."""
    if CONF.agent.manage_tftp:
        pxe_info = _get_tftp_image_info(task.node)
        for label in pxe_info:
            path = pxe_info[label][1]
            utils.unlink_without_raise(path)
        AgentTFTPImageCache().clean_up()
        pxe_utils.clean_up_pxe_config(task)


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
        node = task.node
        params = {}
        if CONF.agent.manage_tftp:
            params['driver_info.deploy_kernel'] = node.driver_info.get(
                'deploy_kernel')
            params['driver_info.deploy_ramdisk'] = node.driver_info.get(
                'deploy_ramdisk')
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
        _do_pxe_boot(task)
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
        node = task.node
        _prepare_pxe_boot(task)

        node.instance_info = build_instance_info_for_deploy(task)
        node.save()

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
        _clean_up_pxe(task)

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
        ports = None
        if getattr(provider.provider, 'create_cleaning_ports', None):
            # Allow to raise if it fails, is caught and handled in conductor
            ports = provider.provider.create_cleaning_ports(task)

        # Append required config parameters to node's driver_internal_info
        # to pass to IPA.
        deploy_utils.agent_add_clean_params(task)

        _prepare_pxe_boot(task)
        _do_pxe_boot(task, ports)
        # Tell the conductor we are waiting for the agent to boot.
        return states.CLEANWAIT

    def tear_down_cleaning(self, task):
        """Clean up the PXE and DHCP files after cleaning.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the cleaning ports cannot be
            removed
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        _clean_up_pxe(task)

        # If we created cleaning ports, delete them
        provider = dhcp_factory.DHCPFactory()
        if getattr(provider.provider, 'delete_cleaning_ports', None):
            # Allow to raise if it fails, is caught and handled in conductor
            provider.provider.delete_cleaning_ports(task)


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
        # NOTE(TheJulia): If we we deployed a whole disk image, we
        # should expect a whole disk image and clean-up the tftp files
        # on-disk incase the node is disregarding the boot preference.
        # TODO(rameshg87): This shouldn't get called for virtual media deploy
        # drivers (iLO and iRMC).  This is just a hack, but it will be taken
        # care in boot/deploy interface separation.
        if (_driver_uses_pxe(task.driver) and
                node.driver_internal_info.get('is_whole_disk_image')):
            _clean_up_pxe(task)
