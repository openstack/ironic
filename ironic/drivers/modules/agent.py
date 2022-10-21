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

from urllib import parse as urlparse

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import units

from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import images
from ironic.common import raid
from ironic.common import states
from ironic.common import utils
from ironic.conductor import deployments
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils


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
        LOG.warning('Skip the image size check as memory_mb is not '
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
    error_msg = _('Node %s failed to validate http provisoning. Some '
                  'configuration options were missing') % node.uuid
    deploy_utils.check_for_missing_params(params, error_msg)


class CustomAgentDeploy(agent_base.AgentBaseMixin, agent_base.AgentDeployMixin,
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
            if not task.node.driver_internal_info.get('deployment_reboot'):
                manager_utils.node_power_action(task, states.REBOOT)
            info = task.node.driver_internal_info
            info.pop('deployment_reboot', None)
            task.node.driver_internal_info = info
            task.node.save()
            return states.DEPLOYWAIT

    @METRICS.timer('CustomAgentDeployMixin.prepare_instance_boot')
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
            msg = _('Failed to prepare instance for booting')
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
            try:
                task.driver.network.validate(task)
            except exception.InvalidParameterValue:
                # For 'neutron' network interface validation will fail
                # if node is using 'netboot' boot option while provisioning
                # a whole disk image. Updating 'boot_option' in node's
                # 'instance_info' to 'local for backward compatibility.
                # TODO(stendulker): Fail here once the default boot
                # option is local.
                # NOTE(TheJulia): Fixing the default boot mode only
                # masks the failure as the lack of a user definition
                # can be perceived as both an invalid configuration and
                # reliance upon the default configuration. The reality
                # being that in most scenarios, users do not want network
                # booting, so the changed default should be valid.
                with excutils.save_and_reraise_exception(reraise=False) as ctx:
                    instance_info = node.instance_info
                    capabilities = utils.parse_instance_info_capabilities(node)
                    if 'boot_option' not in capabilities:
                        capabilities['boot_option'] = 'local'
                        instance_info['capabilities'] = capabilities
                        node.instance_info = instance_info
                        node.save()
                        # Re-validate the network interface
                        task.driver.network.validate(task)
                    else:
                        ctx.reraise = True
            # Determine if this is a fast track sequence
            fast_track_deploy = manager_utils.is_fast_track(task)
            if fast_track_deploy:
                # The agent has already recently checked in and we are
                # configured to take that as an indicator that we can
                # skip ahead.
                LOG.debug('The agent for node %(node)s has recently checked '
                          'in, and the node power will remain unmodified.',
                          {'node': task.node.uuid})
            else:
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
        if node.provision_state in (states.ACTIVE, states.UNRESCUING):
            # Call is due to conductor takeover
            task.driver.boot.prepare_instance(task)
        elif node.provision_state != states.ADOPTING:
            if node.provision_state not in (states.RESCUING, states.RESCUEWAIT,
                                            states.RESCUE, states.RESCUEFAIL):
                self._update_instance_info(task)
            if CONF.agent.manage_agent_boot:
                deploy_opts = deploy_utils.build_agent_options(node)
                task.driver.boot.prepare_ramdisk(task, deploy_opts)

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

        # NOTE(dtantsur): glance images contain a checksum; for file images we
        # will recalculate the checksum anyway.
        if (not service_utils.is_glance_image(image_source)
                and not image_source.startswith('file://')):

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

    @METRICS.timer('AgentDeployMixin.write_image')
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

        if node.instance_info.get('image_checksum'):
            image_info['checksum'] = node.instance_info['image_checksum']

        if (node.instance_info.get('image_os_hash_algo')
                and node.instance_info.get('image_os_hash_value')):
            image_info['os_hash_algo'] = node.instance_info[
                'image_os_hash_algo']
            image_info['os_hash_value'] = node.instance_info[
                'image_os_hash_value']

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

    @METRICS.timer('AgentDeployMixin.prepare_instance_boot')
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

        # If `boot_option` is set to `netboot`, PXEBoot.prepare_instance()
        # would need root_uuid of the whole disk image to add it into the
        # pxe config to perform chain boot.
        # IPA would have returned us the 'root_uuid_or_disk_id' if image
        # being provisioned is a whole disk image. IPA would also provide us
        # 'efi_system_partition_uuid' if the image being provisioned is a
        # partition image.
        # In case of local boot using partition image, we need both
        # 'root_uuid_or_disk_id' and 'efi_system_partition_uuid' to configure
        # bootloader for local boot.
        # NOTE(mjturek): In the case of local boot using a partition image on
        # ppc64* hardware we need to provide the 'PReP_Boot_partition_uuid' to
        # direct where the bootloader should be installed.
        driver_internal_info = task.node.driver_internal_info
        client = agent_client.get_client(task)
        partition_uuids = client.get_partition_uuids(node).get(
            'command_result') or {}
        root_uuid = partition_uuids.get('root uuid')

        if root_uuid:
            driver_internal_info['root_uuid_or_disk_id'] = root_uuid
            task.node.driver_internal_info = driver_internal_info
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

        # Remove symbolic link when deploy is done.
        deploy_utils.remove_http_instance_symlink(task.node.uuid)

    @METRICS.timer('AgentDeploy.sap_cc_install_vsmp_memoryone')
    @base.deploy_step(priority=50)
    @task_manager.require_exclusive_lock
    def sap_cc_install_vsmp_memoryone(self, task):
        node = task.node
        LOG.debug("Agent sap_cc_install_vsmp_memoryone invoked for node %s.",
                  node.uuid)
        instance_info = node.instance_info
        instance_traits = instance_info.get('traits', [])
        if 'CUSTOM_VSMP_MEMORYONE' not in instance_traits:
            LOG.debug("Instance does not require vSMP MemoryOne on node %s.",
                       node.uuid)
            return

        client = agent_client.get_client(task)
        client.sap_cc_install_vsmp_memoryone(task.node)


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
        node.driver_internal_info['target_raid_config'] = target_raid_config

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
        manager_utils.node_power_action(task, states.POWER_OFF)
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
            ramdisk_opts = deploy_utils.build_agent_options(task.node)
            # prepare_ramdisk will set the boot device
            task.driver.boot.prepare_ramdisk(task, ramdisk_opts)
        manager_utils.node_power_action(task, states.POWER_ON)

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
        manager_utils.node_power_action(task, states.POWER_OFF)

        # NOTE(TheJulia): Revealing that the power is off at any time can
        # cause external power sync to decide that the node must be off.
        # This may result in a post-rescued insance being turned off
        # unexpectedly after unrescue.
        # TODO(TheJulia): Once we have power/state callbacks to nova,
        # the reset of the power_state can be removed.
        task.node.power_state = states.POWER_ON
        task.node.save()

        self.clean_up(task)
        with manager_utils.power_state_for_network_configuration(task):
            task.driver.network.configure_tenant_networks(task)
        task.driver.boot.prepare_instance(task)
        manager_utils.node_power_action(task, states.POWER_ON)

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
