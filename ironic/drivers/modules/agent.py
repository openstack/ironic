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

import base64
from urllib import parse as urlparse

from oslo_log import log
from oslo_utils import strutils
from oslo_utils import units
import tenacity

from ironic.common import async_steps
from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service
from ironic.common import images
from ironic.common import metrics_utils
from ironic.common import oci_registry as oci
from ironic.common import raid
from ironic.common import states
from ironic.common import utils
from ironic.conductor import deployments
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers import utils as driver_utils


LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

REQUIRED_PROPERTIES = {
    'deploy_kernel': _('UUID (from Glance) of the deployment kernel. '
                       'Required.'),
    'deploy_ramdisk': _('UUID (from Glance) of the ramdisk with agent that is '
                        'used at deploy time. Required.'),
}

OPTIONAL_PROPERTIES = {
    'image_http_proxy': _('URL of a proxy server for HTTP connections. '
                          'Optional.'),
    'image_https_proxy': _('URL of a proxy server for HTTPS connections. '
                           'Optional.'),
    'image_no_proxy': _('A comma-separated list of host names, IP addresses '
                        'and domain names (with optional :port) that will be '
                        'excluded from proxying. To denote a domain name, use '
                        'a dot to prefix the domain name. This value will be '
                        'ignored if ``image_http_proxy`` and '
                        '``image_https_proxy`` are not specified. Optional.'),
    'image_download_source': _('Specifies whether direct deploy interface '
                               'should try to use the image source directly '
                               'or if ironic should cache the image on the '
                               'conductor and serve it from ironic\'s own '
                               'HTTP server. Accepted values are "swift", '
                               '"http" and "local". Optional.'),
}

_RAID_APPLY_CONFIGURATION_ARGSINFO = {
    "raid_config": {
        "description": "The RAID configuration to apply.",
        "required": True,
    },
    "delete_existing": {
        "description": (
            "Setting this to 'True' indicates to delete existing RAID "
            "configuration prior to creating the new configuration. "
            "Default value is 'True'."
        ),
        "required": False,
    }
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(agent_base.VENDOR_PROPERTIES)

PARTITION_IMAGE_LABELS = ('kernel', 'ramdisk', 'root_gb', 'root_mb', 'swap_mb',
                          'ephemeral_mb', 'ephemeral_format', 'configdrive',
                          'preserve_ephemeral', 'image_type',
                          'deploy_boot_mode')


@METRICS.timer('check_image_size')
def check_image_size(task):
    """Check if the requested image is larger than the ram size.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InvalidParameterValue if size of the image is greater than
        the available ram size.
    """
    node = task.node
    properties = node.properties
    image_source = node.instance_info.get('image_source')
    image_disk_format = node.instance_info.get('image_disk_format')
    # skip check if 'memory_mb' is not defined
    if 'memory_mb' not in properties:
        LOG.debug('Skip the image size check as memory_mb is not '
                  'defined in properties on node %s.', node.uuid)
        return

    image_show = images.image_show(task.context, image_source)
    if CONF.agent.stream_raw_images and (image_show.get('disk_format') == 'raw'
                                         or image_disk_format == 'raw'):
        LOG.debug('Skip the image size check since the image is going to be '
                  'streamed directly onto the disk for node %s', node.uuid)
        return

    memory_size = int(properties.get('memory_mb'))
    image_size = int(image_show['size'])
    reserved_size = CONF.agent.memory_consumed_by_agent
    if (image_size + (reserved_size * units.Mi)) > (memory_size * units.Mi):
        msg = (_('Memory size is too small for requested image, if it is '
                 'less than (image size + reserved RAM size), will break '
                 'the IPA deployments. Image size: %(image_size)d MiB, '
                 'Memory size: %(memory_size)d MiB, Reserved size: '
                 '%(reserved_size)d MiB.')
               % {'image_size': image_size / units.Mi,
                  'memory_size': memory_size,
                  'reserved_size': reserved_size})
        raise exception.InvalidParameterValue(msg)


@METRICS.timer('validate_image_proxies')
def validate_image_proxies(node):
    """Check that the provided proxy parameters are valid.

    :param node: an Ironic node.
    :raises: InvalidParameterValue if any of the provided proxy parameters are
        incorrect.
    """
    invalid_proxies = {}
    for scheme in ('http', 'https'):
        proxy_param = 'image_%s_proxy' % scheme
        proxy = node.driver_info.get(proxy_param)
        if proxy:
            chunks = urlparse.urlparse(proxy)
            # NOTE(vdrok) If no scheme specified, this is still a valid
            # proxy address. It is also possible for a proxy to have a
            # scheme different from the one specified in the image URL,
            # e.g. it is possible to use https:// proxy for downloading
            # http:// image.
            if chunks.scheme not in ('', 'http', 'https'):
                invalid_proxies[proxy_param] = proxy
    msg = ''
    if invalid_proxies:
        msg += _("Proxy URL should either have HTTP(S) scheme "
                 "or no scheme at all, the following URLs are "
                 "invalid: %s.") % invalid_proxies
    no_proxy = node.driver_info.get('image_no_proxy')
    if no_proxy is not None and not utils.is_valid_no_proxy(no_proxy):
        msg += _(
            "image_no_proxy should be a list of host names, IP addresses "
            "or domain names to exclude from proxying, the specified list "
            "%s is incorrect. To denote a domain name, prefix it with a dot "
            "(instead of e.g. '.*').") % no_proxy
    if msg:
        raise exception.InvalidParameterValue(msg)


def validate_http_provisioning_configuration(node):
    """Validate configuration options required to perform HTTP provisioning.

    :param node: an ironic node object
    :raises: MissingParameterValue if required option(s) is not set.
    """
    image_source = node.instance_info.get('image_source')
    image_download_source = deploy_utils.get_image_download_source(node)
    if image_download_source not in ('swift', 'http', 'local'):
        raise exception.InvalidParameterValue(
            _('Invalid value for image_download_source: "%s". Valid values '
              'are swift, http or local.') % image_download_source)

    # NOTE(dtantsur): local HTTP configuration is required in two cases:
    # 1. Glance images with image_download_source == http
    # 2. File images (since we need to serve them to IPA)
    if (not image_source.startswith('file://')
            and image_download_source != 'local'
            and (not service_utils.is_glance_image(image_source)
                 or image_download_source == 'swift')):
        return

    params = {
        '[deploy]http_url': CONF.deploy.http_url,
        '[deploy]http_root': CONF.deploy.http_root,
        '[deploy]http_image_subdir': CONF.deploy.http_image_subdir
    }
    error_msg = _('Node %s failed to validate http provisioning. Some '
                  'configuration options were missing') % node.uuid
    deploy_utils.check_for_missing_params(params, error_msg)


def soft_power_off(task, client=None):
    """Power off the node using the agent API."""
    if client is None:
        client = agent_client.get_client(task)

    wait = CONF.agent.post_deploy_get_power_state_retry_interval
    attempts = CONF.agent.post_deploy_get_power_state_retries + 1

    @tenacity.retry(stop=tenacity.stop_after_attempt(attempts),
                    retry=(tenacity.retry_if_result(
                        lambda state: state != states.POWER_OFF)
                        | tenacity.retry_if_exception_type(Exception)),
                    wait=tenacity.wait_fixed(wait),
                    reraise=True)
    def _wait_until_powered_off(task):
        return task.driver.power.get_power_state(task)

    try:
        client.power_off(task.node)
    except Exception as e:
        LOG.warning('Failed to soft power off node %(node_uuid)s. '
                    '%(cls)s: %(error)s',
                    {'node_uuid': task.node.uuid,
                     'cls': e.__class__.__name__, 'error': e},
                    exc_info=not isinstance(
                        e, exception.IronicException))

    # NOTE(dtantsur): in rare cases it may happen that the power
    # off request comes through but we never receive the response.
    # Check the power state before trying to force off.
    try:
        _wait_until_powered_off(task)
    except Exception:
        LOG.warning('Failed to soft power off node %(node_uuid)s '
                    'in at least %(timeout)d seconds. Forcing '
                    'hard power off and proceeding.',
                    {'node_uuid': task.node.uuid,
                     'timeout': (wait * (attempts - 1))})
        manager_utils.node_power_action(task, states.POWER_OFF)


def set_boot_to_disk(task, target_boot_mode=None):
    """Boot a node to disk.

    This is a helper method to reduce duplication of code around
    handling vendor specifics for setting boot modes between multiple
    deployment interfaces inside of Ironic.

    :param task: A Taskmanager object.
    :param target_boot_mode: The target boot_mode, defaults to UEFI.
    """
    if not target_boot_mode:
        target_boot_mode = boot_modes.UEFI
    node = task.node
    try:
        persistent = True
        # NOTE(TheJulia): We *really* only should be doing this in bios
        # boot mode. In UEFI this might just get disregarded, or cause
        # issues/failures.
        if node.driver_info.get('force_persistent_boot_device',
                                'Default') == 'Never':
            persistent = False

        vendor = task.node.properties.get('vendor', None)
        if not (vendor and vendor.lower() == 'lenovo'
                and target_boot_mode == 'uefi'):
            # Lenovo hardware is modeled on a "just update"
            # UEFI nvram model of use, and if multiple actions
            # get requested, you can end up in cases where NVRAM
            # changes are deleted as the host "restores" to the
            # backup. For more information see
            # https://bugs.launchpad.net/ironic/+bug/2053064
            # NOTE(TheJulia): We likely just need to do this with
            # all hosts in uefi mode, but libvirt VMs don't handle
            # nvram only changes *and* this pattern is known to generally
            # work for Ironic operators.
            deploy_utils.try_set_boot_device(task, boot_devices.DISK,
                                             persistent=persistent)
    except Exception as e:
        msg = (_("Failed to change the boot device to %(boot_dev)s "
                 "when deploying node %(node)s: %(error)s") %
               {'boot_dev': boot_devices.DISK, 'node': node.uuid,
                'error': e})
        agent_base.log_and_raise_deployment_error(task, msg, exc=e)


class CustomAgentDeploy(agent_base.AgentBaseMixin,
                        agent_base.HeartbeatMixin,
                        agent_base.AgentOobStepsMixin,
                        base.DeployInterface):
    """A deploy interface that relies on a custom agent to deploy.

    Only provides the basic deploy steps to start the ramdisk, tear down
    the ramdisk and prepare the instance boot.
    """

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    def should_manage_boot(self, task):
        """Whether agent boot is managed by ironic."""
        return CONF.agent.manage_agent_boot

    @METRICS.timer('CustomAgentDeploy.validate')
    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the properties of the supplied node
        contain the required information for this driver to deploy images to
        the node.

        :param task: a TaskManager instance
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        if CONF.agent.manage_agent_boot:
            task.driver.boot.validate(task)

        deploy_utils.validate_capabilities(task.node)
        # Validate the root device hints
        deploy_utils.get_root_device_for_deploy(task.node)

    @METRICS.timer('CustomAgentDeploy.get_deploy_steps')
    def get_deploy_steps(self, task):
        """Get the list of deploy steps from the agent.

        :param task: a TaskManager object containing the node
        :raises InstanceDeployFailure: if the deploy steps are not yet
            available (cached), for example, when a node has just been
            enrolled and has not been deployed yet.
        :returns: A list of deploy step dictionaries
        """
        steps = super().get_deploy_steps(task)[:]
        ib_steps = agent_base.get_steps(task, 'deploy', interface='deploy')
        # NOTE(dtantsur): we allow in-band steps to be shadowed by out-of-band
        # ones, see the docstring of execute_deploy_step for details.
        steps += [step for step in ib_steps
                  # FIXME(dtantsur): nested loops are not too efficient
                  if not conductor_steps.find_step(steps, step)]
        return steps

    @METRICS.timer('CustomAgentDeploy.execute_deploy_step')
    def execute_deploy_step(self, task, step):
        """Execute a deploy step.

        We're trying to find a step among both out-of-band and in-band steps.
        In case of duplicates, out-of-band steps take priority. This property
        allows having an out-of-band deploy step that calls into
        a corresponding in-band step after some preparation (e.g. with
        additional input).

        :param task: a TaskManager object containing the node
        :param step: a deploy step dictionary to execute
        :raises: InstanceDeployFailure if the agent does not return a command
            status
        :returns: states.DEPLOYWAIT to signify the step will be completed async
        """
        agent_running = task.node.driver_internal_info.get(
            'agent_cached_deploy_steps')
        oob_steps = self.deploy_steps

        if conductor_steps.find_step(oob_steps, step):
            return super().execute_deploy_step(task, step)
        elif not agent_running:
            raise exception.InstanceDeployFailure(
                _('Deploy step %(step)s has not been found. Available '
                  'out-of-band steps: %(oob)s. Agent is not running.') %
                {'step': step, 'oob': oob_steps})
        else:
            return agent_base.execute_step(task, step, 'deploy')

    @METRICS.timer('CustomAgentDeploy.deploy')
    @base.deploy_step(priority=100)
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
        if manager_utils.is_fast_track(task):
            # NOTE(mgoddard): For fast track we can skip this step and proceed
            # immediately to the next deploy step.
            LOG.debug('Performing a fast track deployment for %(node)s.',
                      {'node': task.node.uuid})
            # NOTE(dtantsur): while the node is up and heartbeating, we don't
            # necessary have the deploy steps cached. Force a refresh here.
            self.refresh_steps(task, 'deploy')
            deployments.validate_deploy_steps(task)
        elif task.driver.storage.should_write_image(task):
            # Check if the driver has already performed a reboot in a previous
            # deploy step.
            already_rebooted = task.node.del_driver_internal_info(
                async_steps.DEPLOYMENT_REBOOT)
            task.node.save()
            if not already_rebooted:
                manager_utils.node_power_action(task, states.REBOOT)
            return states.DEPLOYWAIT

    @METRICS.timer('CustomAgentDeploy.prepare_instance_boot')
    @base.deploy_step(priority=60)
    @task_manager.require_exclusive_lock
    def prepare_instance_boot(self, task):
        """Prepare instance for booting.

        The base version only calls prepare_instance on the boot interface.
        """
        try:
            task.driver.boot.prepare_instance(task)
        except Exception as e:
            LOG.error('Preparing instance for booting failed for node '
                      '%(node)s. %(cls)s: %(error)s',
                      {'node': task.node.uuid,
                       'cls': e.__class__.__name__, 'error': e})
            msg = _('Failed to prepare instance for booting: %s') % e
            agent_base.log_and_raise_deployment_error(task, msg, exc=e)

    @METRICS.timer('CustomAgentDeploy.tear_down_agent')
    @base.deploy_step(priority=40)
    @task_manager.require_exclusive_lock
    def tear_down_agent(self, task):
        """A deploy step to tear down the agent.

        :param task: a TaskManager object containing the node
        """
        node = task.node

        if CONF.agent.deploy_logs_collect == 'always':
            driver_utils.collect_ramdisk_logs(node)

        # Whether ironic should power off the node via out-of-band or
        # in-band methods
        oob_power_off = strutils.bool_from_string(
            node.driver_info.get('deploy_forces_oob_reboot', False))
        can_power_on = (states.POWER_ON in
                        task.driver.power.get_supported_power_states(task))

        client = agent_client.get_client(task)
        try:
            if node.disable_power_off:
                LOG.info("Node %s does not support power off, locking "
                         "down the agent", node.uuid)
                client.lockdown(node)
            elif not can_power_on:
                LOG.info('Power interface of node %s does not support '
                         'power on, using reboot to switch to the instance',
                         node.uuid)
                client.sync(node)
                manager_utils.node_power_action(task, states.REBOOT)
            elif not oob_power_off:
                soft_power_off(task, client)
            else:
                # Flush the file system prior to hard rebooting the node
                result = client.sync(node)
                error = result.get('faultstring')
                if error:
                    if 'Unknown command' in error:
                        error = _('The version of the IPA ramdisk used in '
                                  'the deployment do not support the '
                                  'command "sync"')
                    LOG.warning(
                        'Failed to flush the file system prior to hard '
                        'rebooting the node %(node)s: %(error)s',
                        {'node': node.uuid, 'error': error})

                manager_utils.node_power_action(task, states.POWER_OFF)
        except Exception as e:
            msg = (_('Error rebooting node %(node)s after deploy. '
                     '%(cls)s: %(error)s') %
                   {'node': node.uuid, 'cls': e.__class__.__name__,
                    'error': e})
            agent_base.log_and_raise_deployment_error(task, msg, exc=e)

    def _update_instance_info(self, task):
        """Update instance information with extra data for deploy.

        Called from `prepare` to populate fields that can be deduced from
        the already provided information.

        Does nothing in the base class.
        """

    @METRICS.timer('CustomAgentDeploy.prepare')
    @task_manager.require_exclusive_lock
    def prepare(self, task):
        """Prepare the deployment environment for this node.

        :param task: a TaskManager instance.
        :raises: NetworkError: if the previous cleaning ports cannot be removed
            or if new cleaning ports cannot be created.
        :raises: InvalidParameterValue when the wrong power state is specified
            or the wrong driver info is specified for power management.
        :raises: StorageError If the storage driver is unable to attach the
            configured volumes.
        :raises: other exceptions by the node's power driver if something
            wrong occurred during the power action.
        :raises: exception.ImageRefValidationFailed if image_source is not
            Glance href and is not HTTP(S) URL.
        :raises: exception.InvalidParameterValue if network validation fails.
        :raises: any boot interface's prepare_ramdisk exceptions.
        """

        node = task.node
        deploy_utils.populate_storage_driver_internal_info(task)
        if node.provision_state == states.DEPLOYING:
            # Validate network interface to ensure that it supports boot
            # options configured on the node.
            task.driver.network.validate(task)
            # Determine if this is a fast track sequence
            fast_track_deploy = manager_utils.is_fast_track(task)
            if fast_track_deploy:
                # The agent has already recently checked in and we are
                # configured to take that as an indicator that we can
                # skip ahead.
                LOG.debug('The agent for node %(node)s has recently checked '
                          'in, and the node power will remain unmodified.',
                          {'node': task.node.uuid})
            elif not node.disable_power_off:
                # Powering off node to setup networking for port and
                # ensure that the state is reset if it is inadvertently
                # on for any unknown reason.
                manager_utils.node_power_action(task, states.POWER_OFF)
            if task.driver.storage.should_write_image(task):
                # NOTE(vdrok): in case of rebuild, we have tenant network
                # already configured, unbind tenant ports if present
                if not fast_track_deploy:
                    power_state_to_restore = (
                        manager_utils.power_on_node_if_needed(task))

                task.driver.network.unconfigure_tenant_networks(task)
                task.driver.network.add_provisioning_network(task)
                if not fast_track_deploy:
                    manager_utils.restore_power_state_if_needed(
                        task, power_state_to_restore)
                else:
                    # Fast track sequence in progress
                    self._update_instance_info(task)
            # Signal to storage driver to attach volumes
            task.driver.storage.attach_volumes(task)
            if (not task.driver.storage.should_write_image(task)
                or fast_track_deploy):
                # We have nothing else to do as this is handled in the
                # backend storage system, and we can return to the caller
                # as we do not need to boot the agent to deploy.
                # Alternatively, we could be in a fast track deployment
                # and again, we should have nothing to do here.
                return
        if node.provision_state in (states.ACTIVE, states.UNRESCUING,
                                    states.ADOPTING):
            # Call is due to conductor takeover
            task.driver.boot.prepare_instance(task)
        else:
            if node.provision_state not in (states.RESCUING, states.RESCUEWAIT,
                                            states.RESCUE, states.RESCUEFAIL):
                self._update_instance_info(task)
            if CONF.agent.manage_agent_boot:
                deploy_utils.prepare_agent_boot(task)

    @METRICS.timer('CustomAgentDeploy.clean_up')
    @task_manager.require_exclusive_lock
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
        super().clean_up(task)
        deploy_utils.destroy_http_instance_images(task.node)


class AgentDeploy(CustomAgentDeploy):
    """Interface for deploy-related actions."""

    def _update_instance_info(self, task):
        """Update instance information with extra data for deploy."""
        task.node.instance_info = (
            deploy_utils.build_instance_info_for_deploy(task))
        task.node.save()
        check_image_size(task)

    @METRICS.timer('AgentDeploy.validate')
    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the properties of the supplied node
        contain the required information for this driver to deploy images to
        the node.

        :param task: a TaskManager instance
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        super().validate(task)

        node = task.node

        if not task.driver.storage.should_write_image(task):
            # NOTE(TheJulia): There is no reason to validate
            # image properties if we will not be writing an image
            # in a boot from volume case. As such, return to the caller.
            LOG.debug('Skipping complete deployment interface validation '
                      'for node %s as it is set to boot from a remote '
                      'volume.', node.uuid)
            return
        params = {}
        image_source = node.instance_info.get('image_source')
        image_checksum = node.instance_info.get('image_checksum')
        os_hash_algo = node.instance_info.get('image_os_hash_algo')
        os_hash_value = node.instance_info.get('image_os_hash_value')

        params['instance_info.image_source'] = image_source
        error_msg = _('Node %s failed to validate deploy image info. Some '
                      'parameters were missing') % node.uuid

        deploy_utils.check_for_missing_params(params, error_msg)

        image_type = node.instance_info.get('image_type')
        if image_type and image_type not in images.VALID_IMAGE_TYPES:
            raise exception.InvalidParameterValue(
                _('Invalid image_type "%(value)s", valid are %(valid)s')
                % {'value': image_type,
                   'valid': ', '.join(images.VALID_IMAGE_TYPES)})

        # NOTE(dtantsur): glance images contain a checksum; for file images we
        # will recalculate the checksum anyway.
        if (not service_utils.is_glance_image(image_source)
                and not image_source.startswith('file://')
                and not image_source.startswith('oci://')):

            def _raise_missing_checksum_exception(node):
                raise exception.MissingParameterValue(_(
                    'image_source\'s "image_checksum", or '
                    '"image_os_hash_algo" and "image_os_hash_value" '
                    'must be provided in instance_info for '
                    'node %s') % node.uuid)

            if os_hash_value and not os_hash_algo:
                # We are missing a piece of information,
                # so we still need to raise an error.
                _raise_missing_checksum_exception(node)
            elif not os_hash_value and os_hash_algo:
                # We have the hash setting, but not the hash.
                _raise_missing_checksum_exception(node)
            elif not os_hash_value and not image_checksum:
                # We are lacking the original image_checksum,
                # so we raise the error.
                _raise_missing_checksum_exception(node)

        validate_http_provisioning_configuration(node)
        validate_image_proxies(node)

        capabilities = utils.parse_instance_info_capabilities(node)
        if 'boot_option' in capabilities:
            LOG.warning("The boot_option capability has been deprecated, "
                        "please unset it for node %s", node.uuid)

    @METRICS.timer('AgentDeploy.write_image')
    @base.deploy_step(priority=80)
    @task_manager.require_exclusive_lock
    def write_image(self, task):
        if not task.driver.storage.should_write_image(task):
            return
        node = task.node
        image_source = node.instance_info.get('image_source')
        LOG.debug('Continuing deploy for node %(node)s with image %(img)s',
                  {'node': node.uuid, 'img': image_source})

        image_info = {
            'id': image_source.split('/')[-1],
            'urls': [node.instance_info['image_url']],
            # NOTE(comstud): Older versions of ironic do not set
            # 'disk_format' nor 'container_format', so we use .get()
            # to maintain backwards compatibility in case code was
            # upgraded in the middle of a build request.
            'disk_format': node.instance_info.get('image_disk_format'),
            'container_format': node.instance_info.get(
                'image_container_format'),
            'stream_raw_images': CONF.agent.stream_raw_images,
        }

        if (CONF.deploy.image_server_auth_strategy != 'noauth'):
            image_info['image_server_auth_strategy'] = \
                CONF.deploy.image_server_auth_strategy
            image_info['image_server_user'] = CONF.deploy.image_server_user
            image_info['image_server_password'] =\
                CONF.deploy.image_server_password

        if node.instance_info.get('image_checksum'):
            image_info['checksum'] = node.instance_info['image_checksum']

        if (node.instance_info.get('image_os_hash_algo')
                and node.instance_info.get('image_os_hash_value')):
            image_info['os_hash_algo'] = node.instance_info[
                'image_os_hash_algo']
            image_info['os_hash_value'] = node.instance_info[
                'image_os_hash_value']

        if node.instance_info.get('image_request_authorization_secret'):
            ah = node.instance_info.get('image_request_authorization_secret')
            ah = base64.standard_b64encode(ah.encode())
            image_info['image_request_authorization'] = ah

        proxies = {}
        for scheme in ('http', 'https'):
            proxy_param = 'image_%s_proxy' % scheme
            proxy = node.driver_info.get(proxy_param)
            if proxy:
                proxies[scheme] = proxy
        if proxies:
            image_info['proxies'] = proxies
            no_proxy = node.driver_info.get('image_no_proxy')
            if no_proxy is not None:
                image_info['no_proxy'] = no_proxy

        image_info['node_uuid'] = node.uuid
        iwdi = node.driver_internal_info.get('is_whole_disk_image')
        if not iwdi:
            for label in PARTITION_IMAGE_LABELS:
                image_info[label] = node.instance_info.get(label)
            boot_option = deploy_utils.get_boot_option(node)
            image_info['deploy_boot_mode'] = (
                boot_mode_utils.get_boot_mode(node))
            image_info['boot_option'] = boot_option
            disk_label = deploy_utils.get_disk_label(node)
            if disk_label is not None:
                image_info['disk_label'] = disk_label

        configdrive = manager_utils.get_configdrive_image(node)
        if configdrive:
            # FIXME(dtantsur): remove this duplication once IPA is ready:
            # https://review.opendev.org/c/openstack/ironic-python-agent/+/790471
            image_info['configdrive'] = configdrive
        # Now switch into the corresponding in-band deploy step and let the
        # result be polled normally.
        new_step = {'interface': 'deploy',
                    'step': 'write_image',
                    'args': {'image_info': image_info,
                             'configdrive': configdrive}}
        client = agent_client.get_client(task)
        return agent_base.execute_step(task, new_step, 'deploy',
                                       client=client)

    @METRICS.timer('AgentDeploy.prepare_instance_boot')
    @base.deploy_step(priority=60)
    @task_manager.require_exclusive_lock
    def prepare_instance_boot(self, task):
        if not task.driver.storage.should_write_image(task):
            task.driver.boot.prepare_instance(task)
            # Move straight to the final steps
            return

        node = task.node
        iwdi = task.node.driver_internal_info.get('is_whole_disk_image')
        cpu_arch = task.node.properties.get('cpu_arch')

        # In case of local boot using partition image, we need both
        # 'root_uuid_or_disk_id' and 'efi_system_partition_uuid' to configure
        # bootloader for local boot.
        # NOTE(mjturek): In the case of local boot using a partition image on
        # ppc64* hardware we need to provide the 'PReP_Boot_partition_uuid' to
        # direct where the bootloader should be installed.
        client = agent_client.get_client(task)
        partition_uuids = client.get_partition_uuids(node).get(
            'command_result') or {}
        root_uuid = partition_uuids.get('root uuid')

        if root_uuid:
            node.set_driver_internal_info('root_uuid_or_disk_id', root_uuid)
            task.node.save()
        elif not iwdi:
            LOG.error('No root UUID returned from the ramdisk for node '
                      '%(node)s, the deploy will likely fail. Partition '
                      'UUIDs are %(uuids)s',
                      {'node': node.uuid, 'uuid': partition_uuids})

        efi_sys_uuid = None
        if not iwdi:
            if boot_mode_utils.get_boot_mode(node) == 'uefi':
                efi_sys_uuid = partition_uuids.get(
                    'efi system partition uuid')

        prep_boot_part_uuid = None
        if cpu_arch is not None and cpu_arch.startswith('ppc64'):
            prep_boot_part_uuid = partition_uuids.get(
                'PReP Boot partition uuid')

        LOG.info('Image successfully written to node %s', node.uuid)

        if CONF.agent.manage_agent_boot:
            # It is necessary to invoke prepare_instance() of the node's
            # boot interface, so that the any necessary configurations like
            # setting of the boot mode (e.g. UEFI secure boot) which cannot
            # be done on node during deploy stage can be performed.
            LOG.debug('Executing driver specific tasks before booting up the '
                      'instance for node %s', node.uuid)
            self.prepare_instance_to_boot(task, root_uuid,
                                          efi_sys_uuid, prep_boot_part_uuid)
        else:
            manager_utils.node_set_boot_device(task, 'disk', persistent=True)

        # Remove symbolic link and image when deploy is done.
        deploy_utils.destroy_http_instance_images(task.node)

    @METRICS.timer('AgentDeploy.prepare_instance_to_boot')
    def prepare_instance_to_boot(self, task, root_uuid, efi_sys_uuid,
                                 prep_boot_part_uuid=None):
        """Prepares instance to boot.

        :param task: a TaskManager object containing the node
        :param root_uuid: the UUID for root partition
        :param efi_sys_uuid: the UUID for the efi partition
        :raises: InvalidState if fails to prepare instance
        """

        node = task.node
        # Install the boot loader
        self.configure_local_boot(
            task, root_uuid=root_uuid,
            efi_system_part_uuid=efi_sys_uuid,
            prep_boot_part_uuid=prep_boot_part_uuid)

        try:
            task.driver.boot.prepare_instance(task)
        except Exception as e:
            LOG.error('Preparing instance for booting failed for instance '
                      '%(instance)s. %(cls)s: %(error)s',
                      {'instance': node.instance_uuid,
                       'cls': e.__class__.__name__, 'error': e})
            msg = _('Failed to prepare instance for booting: %s') % e
            agent_base.log_and_raise_deployment_error(task, msg, exc=e)

    @METRICS.timer('AgentDeploy.configure_local_boot')
    def configure_local_boot(self, task, root_uuid=None,
                             efi_system_part_uuid=None,
                             prep_boot_part_uuid=None):
        """Helper method to configure local boot on the node.

        This method triggers bootloader installation on the node.
        On successful installation of bootloader, this method sets the
        node to boot from disk.

        :param task: a TaskManager object containing the node
        :param root_uuid: The UUID of the root partition. This is used
            for identifying the partition which contains the image deployed
            or None in case of whole disk images which we expect to already
            have a bootloader installed.
        :param efi_system_part_uuid: The UUID of the efi system partition.
            This is used only in uefi boot mode.
        :param prep_boot_part_uuid: The UUID of the PReP Boot partition.
            This is used only for booting ppc64* hardware.
        :raises: InstanceDeployFailure if bootloader installation failed or
            on encountering error while setting the boot device on the node.
        """
        node = task.node
        # Almost never taken into account on agent side, just used for softraid
        # Can be useful with whole_disk_images
        target_boot_mode = boot_mode_utils.get_boot_mode(task.node)
        LOG.debug('Configuring local boot for node %s', node.uuid)

        # If the target RAID configuration is set to 'software' for the
        # 'controller', we need to trigger the installation of grub on
        # the holder disks of the desired Software RAID.
        internal_info = node.driver_internal_info
        raid_config = node.target_raid_config
        logical_disks = raid_config.get('logical_disks', [])
        software_raid = False
        for logical_disk in logical_disks:
            if logical_disk.get('controller') == 'software':
                LOG.debug('Node %s has a Software RAID configuration',
                          node.uuid)
                software_raid = True
                break

        # For software RAID try to get the UUID of the root fs from the
        # image's metadata (via Glance). Fall back to the driver internal
        # info in case it is not available (e.g. not set or there's no Glance).
        if software_raid:
            root_uuid = node.instance_info.get('image_rootfs_uuid')
            if not root_uuid:
                image_source = node.instance_info.get('image_source')
                try:
                    context = task.context
                    # TODO(TheJulia): Uhh, is_admin likely needs to be
                    # addressed in Xena as undesirable behavior may
                    # result, or just outright break in an entirely
                    # system scoped configuration.
                    context.is_admin = True
                    glance = image_service.GlanceImageService(
                        context=context)
                    image_info = glance.show(image_source)
                    image_properties = image_info.get('properties')
                    root_uuid = image_properties['rootfs_uuid']
                    LOG.debug('Got rootfs_uuid from Glance: %s '
                              '(node %s)', root_uuid, node.uuid)
                except Exception as e:
                    LOG.warning(
                        'Could not get \'rootfs_uuid\' property for '
                        'image %(image)s from Glance for node %(node)s. '
                        '%(cls)s: %(error)s.',
                        {'image': image_source, 'node': node.uuid,
                         'cls': e.__class__.__name__, 'error': e})
                    root_uuid = internal_info.get('root_uuid_or_disk_id')
                    LOG.debug('Got rootfs_uuid from driver internal info: '
                              '%s (node %s)', root_uuid, node.uuid)

        # For whole disk images it is not necessary that the root_uuid
        # be provided since the bootloaders on the disk will be used
        whole_disk_image = internal_info.get('is_whole_disk_image')
        if (software_raid or (root_uuid and not whole_disk_image)
                or (whole_disk_image
                    and boot_mode_utils.get_boot_mode(node) == 'uefi')):
            LOG.debug('Installing the bootloader for node %(node)s on '
                      'partition %(part)s, EFI system partition %(efi)s',
                      {'node': node.uuid, 'part': root_uuid,
                       'efi': efi_system_part_uuid})
            client = agent_client.get_client(task)
            result = client.install_bootloader(
                node, root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid,
                prep_boot_part_uuid=prep_boot_part_uuid,
                target_boot_mode=target_boot_mode,
                software_raid=software_raid
            )
            if result['command_status'] == 'FAILED':
                msg = (_("Failed to install a bootloader when "
                         "deploying node %(node)s: %(error)s") %
                       {'node': node.uuid,
                        'error': agent_client.get_command_error(result)})
                agent_base.log_and_raise_deployment_error(task, msg)

        set_boot_to_disk(task, target_boot_mode)
        LOG.info('Local boot successfully configured for node %s', node.uuid)


class BootcAgentDeploy(CustomAgentDeploy):
    """Interface for deploy-related actions."""

    @METRICS.timer('AgentBootcDeploy.validate')
    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the properties of the supplied node
        contain the required information for this driver to deploy images to
        the node.

        :param task: a TaskManager instance
        :raises: MissingParameterValue, if any of the required parameters are
            missing.
        :raises: InvalidParameterValue, if any of the parameters have invalid
            value.
        """
        super().validate(task)

        node = task.node

        image_source = node.instance_info.get('image_source')
        if not image_source or not image_source.startswith('oci://'):
            raise exception.InvalidImageRef(image_href=image_source)

    @METRICS.timer('AgentBootcDeploy.execute_bootc_install')
    @base.deploy_step(priority=80)
    @task_manager.require_exclusive_lock
    def execute_bootc_install(self, task):
        node = task.node
        image_source = node.instance_info.get('image_source')
        # FIXME(TheJulia): We likely, either need to grab/collect creds
        # and pass them along in the step call, or initialize the client.
        # bootc runs in the target container as well, so ... hmmm
        configdrive = manager_utils.get_configdrive_image(node)

        img_auth = image_service.get_image_service_auth_override(task.node)

        if not img_auth:
            fqdn = urlparse.urlparse(image_source).netloc
            img_auth = oci.RegistrySessionHelper.get_token_from_config(
                fqdn)
        else:
            # Internally, image data is a username and password, and we
            # only currently support pull secrets which are just transmitted
            # via the password value.
            img_auth = img_auth.get('password')
        if img_auth:
            # This is not encryption, but obfustication.
            img_auth = base64.standard_b64encode(img_auth.encode())
        # Now switch into the corresponding in-band deploy step and let the
        # result be polled normally.
        new_step = {'interface': 'deploy',
                    'step': 'execute_bootc_install',
                    'args': {'image_source': image_source,
                             'configdrive': configdrive,
                             'oci_pull_secret': img_auth}}
        client = agent_client.get_client(task)
        return agent_base.execute_step(task, new_step, 'deploy',
                                       client=client)

    @METRICS.timer('AgentBootcDeploy.set_boot_to_disk')
    @base.deploy_step(priority=60)
    @task_manager.require_exclusive_lock
    def set_boot_to_disk(self, task):
        """Sets the node to boot from disk.

        In some cases, other steps may handle aspects like bootloaders
        and UEFI NVRAM entries required to boot. That leaves one last
        aspect, resetting the node to boot from disk.

        This primarily exists for compatibility reasons of flow
        for Ironic, but we know some BMCs *really* need to be
        still told to boot from disk. The exception to this is
        Lenovo hardware, where we skip the action because it
        can create a UEFI NVRAM update failure case, which
        reverts the NVRAM state to "last known good configuration".

        :param task: A Taskmanager object.
        """
        # Call the helper to de-duplicate code.
        set_boot_to_disk(task)


class AgentRAID(base.RAIDInterface):
    """Implementation of RAIDInterface which uses agent ramdisk."""

    def get_properties(self):
        """Return the properties of the interface."""
        return {}

    @METRICS.timer('AgentRAID.get_clean_steps')
    def get_clean_steps(self, task):
        """Get the list of clean steps from the agent.

        :param task: a TaskManager object containing the node
        :raises NodeCleaningFailure: if the clean steps are not yet
            available (cached), for example, when a node has just been
            enrolled and has not been cleaned yet.
        :returns: A list of clean step dictionaries
        """
        new_priorities = {
            'delete_configuration': CONF.deploy.delete_configuration_priority,
            'create_configuration': CONF.deploy.create_configuration_priority
        }
        return agent_base.get_steps(
            task, 'clean', interface='raid',
            override_priorities=new_priorities)

    @METRICS.timer('AgentRAID.get_deploy_steps')
    def get_deploy_steps(self, task):
        """Get the list of deploy steps from the agent.

        :param task: a TaskManager object containing the node
        :raises InstanceDeployFailure: if the deploy steps are not yet
            available (cached), for example, when a node has just been
            enrolled and has not been deployed yet.
        :returns: A list of deploy step dictionaries
        """
        return agent_base.get_steps(task, 'deploy', interface='raid')

    @METRICS.timer('AgentRAID.apply_configuration')
    @base.service_step(priority=0,
                       argsinfo=_RAID_APPLY_CONFIGURATION_ARGSINFO)
    @base.deploy_step(priority=0,
                      argsinfo=_RAID_APPLY_CONFIGURATION_ARGSINFO)
    def apply_configuration(self, task, raid_config,
                            delete_existing=True):
        """Applies RAID configuration on the given node.

        :param task: A TaskManager instance.
        :param raid_config: The RAID configuration to apply.
        :param delete_existing: Setting this to True indicates to delete RAID
            configuration prior to creating the new configuration.
        :raises: InvalidParameterValue, if the RAID configuration is invalid.
        :returns: states.DEPLOYWAIT if RAID configuration is in progress
            asynchronously or None if it is complete.
        """
        self.validate_raid_config(task, raid_config)
        step = task.node.deploy_step
        return agent_base.execute_step(task, step, 'deploy')

    @METRICS.timer('AgentRAID.create_configuration')
    @base.clean_step(priority=0)
    def create_configuration(self, task,
                             create_root_volume=True,
                             create_nonroot_volumes=True):
        """Create a RAID configuration on a bare metal using agent ramdisk.

        This method creates a RAID configuration on the given node.

        :param task: a TaskManager instance.
        :param create_root_volume: If True, a root volume is created
            during RAID configuration. Otherwise, no root volume is
            created. Default is True.
        :param create_nonroot_volumes: If True, non-root volumes are
            created. If False, no non-root volumes are created. Default
            is True.
        :returns: states.CLEANWAIT if operation was successfully invoked.
        :raises: MissingParameterValue, if node.target_raid_config is missing
            or was found to be empty after skipping root volume and/or non-root
            volumes.
        """
        node = task.node
        LOG.debug("Agent RAID create_configuration invoked for node %(node)s "
                  "with create_root_volume=%(create_root_volume)s and "
                  "create_nonroot_volumes=%(create_nonroot_volumes)s with the "
                  "following target_raid_config: %(target_raid_config)s.",
                  {'node': node.uuid,
                   'create_root_volume': create_root_volume,
                   'create_nonroot_volumes': create_nonroot_volumes,
                   'target_raid_config': node.target_raid_config})

        target_raid_config = raid.filter_target_raid_config(
            node,
            create_root_volume=create_root_volume,
            create_nonroot_volumes=create_nonroot_volumes)
        # Rewrite it back to the node object, but no need to save it as
        # we need to just send this to the agent ramdisk.
        node.set_driver_internal_info('target_raid_config', target_raid_config)

        LOG.debug("Calling agent RAID create_configuration for node %(node)s "
                  "with the following target RAID configuration: %(target)s",
                  {'node': node.uuid, 'target': target_raid_config})
        step = node.clean_step
        return agent_base.execute_clean_step(task, step)

    @staticmethod
    @agent_base.post_clean_step_hook(
        interface='raid', step='create_configuration')
    @agent_base.post_deploy_step_hook(
        interface='raid', step='apply_configuration')
    def _create_configuration_final(task, command):
        """Clean step hook after a RAID configuration was created.

        This method is invoked as a post clean step hook by the Ironic
        conductor once a create raid configuration is completed successfully.
        The node (properties, capabilities, RAID information) will be updated
        to reflect the actual RAID configuration that was created.

        :param task: a TaskManager instance.
        :param command: A command result structure of the RAID operation
            returned from agent ramdisk on query of the status of command(s).
        :raises: InvalidParameterValue, if 'current_raid_config' has more than
            one root volume or if node.properties['capabilities'] is malformed.
        :raises: IronicException, if clean_result couldn't be found within
            the 'command' argument passed.
        """
        try:
            if task.node.provision_state == states.DEPLOYWAIT:
                result = command['command_result']['deploy_result']
            else:
                result = command['command_result']['clean_result']
        except KeyError:
            result = None

        if not result:
            raise exception.IronicException(
                _("Agent ramdisk didn't return a proper command result while "
                  "building RAID on %(node)s. It returned '%(result)s' after "
                  "command execution.") % {'node': task.node.uuid,
                                           'result': command})

        raid.update_raid_info(task.node, result)

    @METRICS.timer('AgentRAID.delete_configuration')
    @base.clean_step(priority=0)
    def delete_configuration(self, task):
        """Deletes RAID configuration on the given node.

        :param task: a TaskManager instance.
        :returns: states.CLEANWAIT if operation was successfully invoked
        """
        LOG.debug("Agent RAID delete_configuration invoked for node %s.",
                  task.node.uuid)
        step = task.node.clean_step
        return agent_base.execute_clean_step(task, step)

    @staticmethod
    @agent_base.post_clean_step_hook(
        interface='raid', step='delete_configuration')
    def _delete_configuration_final(task, command):
        """Clean step hook after RAID configuration was deleted.

        This method is invoked as a post clean step hook by the Ironic
        conductor once a delete raid configuration is completed successfully.
        It sets node.raid_config to empty dictionary.

        :param task: a TaskManager instance.
        :param command: A command result structure of the RAID operation
            returned from agent ramdisk on query of the status of command(s).
        :returns: None
        """
        prop = task.node.properties
        prop.pop('root_device', None)
        task.node.properties = prop
        task.node.raid_config = {}
        task.node.save()


class AgentRescue(base.RescueInterface):
    """Implementation of RescueInterface which uses agent ramdisk."""

    def get_properties(self):
        """Return the properties of the interface. """
        return {}

    @METRICS.timer('AgentRescue.rescue')
    @task_manager.require_exclusive_lock
    def rescue(self, task):
        """Boot a rescue ramdisk on the node.

        :param task: a TaskManager instance.
        :raises: NetworkError if the tenant ports cannot be removed.
        :raises: InvalidParameterValue when the wrong power state is specified
             or the wrong driver info is specified for power management.
        :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.
        :raises: any boot interface's prepare_ramdisk exceptions.
        :returns: Returns states.RESCUEWAIT
        """
        with driver_utils.power_off_and_on(task):
            # NOTE(TheJulia): Revealing that the power is off at any time can
            # cause external power sync to decide that the node must be off.
            # This may result in a post-rescued instance being turned off
            # unexpectedly after rescue has started.
            # TODO(TheJulia): Once we have power/state callbacks to nova,
            # the reset of the power_state can be removed.
            task.node.power_state = states.POWER_ON
            task.node.save()

            task.driver.boot.clean_up_instance(task)
            with manager_utils.power_state_for_network_configuration(task):
                task.driver.network.unconfigure_tenant_networks(task)
                task.driver.network.add_rescuing_network(task)
            if CONF.agent.manage_agent_boot:
                # prepare_ramdisk will set the boot device
                deploy_utils.prepare_agent_boot(task)

        return states.RESCUEWAIT

    @METRICS.timer('AgentRescue.unrescue')
    @task_manager.require_exclusive_lock
    def unrescue(self, task):
        """Attempt to move a rescued node back to active state.

        :param task: a TaskManager instance.
        :raises: NetworkError if the rescue ports cannot be removed.
        :raises: InvalidParameterValue when the wrong power state is specified
             or the wrong driver info is specified for power management.
        :raises: other exceptions by the node's power driver if something
             wrong occurred during the power action.
        :raises: any boot interface's prepare_instance exceptions.
        :returns: Returns states.ACTIVE
        """
        with driver_utils.power_off_and_on(task):
            # NOTE(TheJulia): Revealing that the power is off at any time can
            # cause external power sync to decide that the node must be off.
            # This may result in a post-rescued instance being turned off
            # unexpectedly after unrescue.
            # TODO(TheJulia): Once we have power/state callbacks to nova,
            # the reset of the power_state can be removed.
            task.node.power_state = states.POWER_ON
            task.node.save()

            self.clean_up(task)
            with manager_utils.power_state_for_network_configuration(task):
                task.driver.network.configure_tenant_networks(task)
            task.driver.boot.prepare_instance(task)

        return states.ACTIVE

    @METRICS.timer('AgentRescue.validate')
    def validate(self, task):
        """Validate that the node has required properties for agent rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: InvalidParameterValue if 'instance_info/rescue_password' has
            empty password or rescuing network UUID config option
            has an invalid value.
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        """
        # Validate rescuing network
        task.driver.network.validate_rescue(task)
        if CONF.agent.manage_agent_boot:
            # Validate boot properties
            task.driver.boot.validate(task)
            # Validate boot properties related to rescue
            task.driver.boot.validate_rescue(task)

        node = task.node
        rescue_pass = node.instance_info.get('rescue_password')
        if rescue_pass is None:
            msg = _("Node %(node)s is missing "
                    "'instance_info/rescue_password'. "
                    "It is required for rescuing node.")
            raise exception.MissingParameterValue(msg % {'node': node.uuid})

        if not rescue_pass.strip():
            msg = (_("The 'instance_info/rescue_password' is an empty string "
                     "for node %s. The 'rescue_password' must be a non-empty "
                     "string value.") % node.uuid)
            raise exception.InvalidParameterValue(msg)

    @METRICS.timer('AgentRescue.clean_up')
    def clean_up(self, task):
        """Clean up after RESCUEWAIT timeout/failure or finishing rescue.

        Rescue password should be removed from the node and ramdisk boot
        environment should be cleaned if Ironic is managing the ramdisk boot.

        :param task: a TaskManager instance with the node.
        :raises: NetworkError if the rescue ports cannot be removed.
        """
        manager_utils.remove_node_rescue_password(task.node, save=True)
        if CONF.agent.manage_agent_boot:
            task.driver.boot.clean_up_ramdisk(task)
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.remove_rescuing_network(task)
