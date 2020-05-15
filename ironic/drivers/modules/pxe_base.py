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
Base PXE Interface Methods
"""

from futurist import periodics
from ironic_lib import metrics_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers import utils as driver_utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

REQUIRED_PROPERTIES = {
    'deploy_kernel': _("UUID (from Glance) of the deployment kernel. "
                       "Required."),
    'deploy_ramdisk': _("UUID (from Glance) of the ramdisk that is "
                        "mounted at boot time. Required."),
}
OPTIONAL_PROPERTIES = {
    'force_persistent_boot_device': _("Controls the persistency of boot order "
                                      "changes. 'Always' will make all "
                                      "changes persistent, 'Default' will "
                                      "make all but the final one upon "
                                      "instance deployment non-persistent, "
                                      "and 'Never' will make no persistent "
                                      "changes at all. The old values 'True' "
                                      "and 'False' are still supported but "
                                      "deprecated in favor of the new ones."
                                      "Defaults to 'Default'. Optional."),
}
RESCUE_PROPERTIES = {
    'rescue_kernel': _('UUID (from Glance) of the rescue kernel. This value '
                       'is required for rescue mode.'),
    'rescue_ramdisk': _('UUID (from Glance) of the rescue ramdisk with agent '
                        'that is used at node rescue time. This value is '
                        'required for rescue mode.'),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(RESCUE_PROPERTIES)


class PXEBaseMixin(object):

    ipxe_enabled = False

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    @METRICS.timer('PXEBaseMixin.clean_up_ramdisk')
    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up the PXE environment that was setup for booting
        the deploy or rescue ramdisk. It unlinks the deploy/rescue
        kernel/ramdisk in the node's directory in tftproot and removes it's PXE
        config.

        :param task: a task from TaskManager.
        :param mode: Label indicating a deploy or rescue operation
            was carried out on the node. Supported values are 'deploy' and
            'rescue'. Defaults to 'deploy', indicating deploy operation was
            carried out.
        :returns: None
        """
        node = task.node
        mode = deploy_utils.rescue_or_deploy_mode(node)
        try:
            images_info = pxe_utils.get_image_info(
                node, mode=mode, ipxe_enabled=self.ipxe_enabled)
        except exception.MissingParameterValue as e:
            LOG.warning('Could not get %(mode)s image info '
                        'to clean up images for node %(node)s: %(err)s',
                        {'mode': mode, 'node': node.uuid, 'err': e})
        else:
            pxe_utils.clean_up_pxe_env(
                task, images_info, ipxe_enabled=self.ipxe_enabled)

    @METRICS.timer('PXEBaseMixin.clean_up_instance')
    def clean_up_instance(self, task):
        """Cleans up the boot of instance.

        This method cleans up the environment that was setup for booting
        the instance. It unlinks the instance kernel/ramdisk in node's
        directory in tftproot and removes the PXE config.

        :param task: a task from TaskManager.
        :returns: None
        """
        node = task.node

        try:
            images_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=self.ipxe_enabled)
        except exception.MissingParameterValue as e:
            LOG.warning('Could not get instance image info '
                        'to clean up images for node %(node)s: %(err)s',
                        {'node': node.uuid, 'err': e})
        else:
            pxe_utils.clean_up_pxe_env(task, images_info,
                                       ipxe_enabled=self.ipxe_enabled)

    @METRICS.timer('PXEBaseMixin.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of Ironic ramdisk using PXE.

        This method prepares the boot of the deploy or rescue kernel/ramdisk
        after reading relevant information from the node's driver_info and
        instance_info.

        :param task: a task from TaskManager.
        :param ramdisk_params: the parameters to be passed to the ramdisk.
            pxe driver passes these parameters as kernel command-line
            arguments.
        :returns: None
        :raises: MissingParameterValue, if some information is missing in
            node's driver_info or instance_info.
        :raises: InvalidParameterValue, if some information provided is
            invalid.
        :raises: IronicException, if some power or set boot boot device
            operation failed on the node.
        """
        node = task.node

        # Label indicating a deploy or rescue operation being carried out on
        # the node, 'deploy' or 'rescue'. Unless the node is in a rescue like
        # state, the mode is set to 'deploy', indicating deploy operation is
        # being carried out.
        mode = deploy_utils.rescue_or_deploy_mode(node)

        if self.ipxe_enabled:
            # NOTE(mjturek): At this point, the ipxe boot script should
            # already exist as it is created at startup time. However, we
            # call the boot script create method here to assert its
            # existence and handle the unlikely case that it wasn't created
            # or was deleted.
            pxe_utils.create_ipxe_boot_script()

        # Generate options for both IPv4 and IPv6, and they can be
        # filtered down later based upon the port options.
        # TODO(TheJulia): This should be re-tooled during the Victoria
        # development cycle so that we call a single method and return
        # combined options. The method we currently call is relied upon
        # by two eternal projects, to changing the behavior is not ideal.
        dhcp_opts = pxe_utils.dhcp_options_for_instance(
            task, ipxe_enabled=self.ipxe_enabled, ip_version=4)
        dhcp_opts += pxe_utils.dhcp_options_for_instance(
            task, ipxe_enabled=self.ipxe_enabled, ip_version=6)
        provider = dhcp_factory.DHCPFactory()
        provider.update_dhcp(task, dhcp_opts)

        pxe_info = pxe_utils.get_image_info(node, mode=mode,
                                            ipxe_enabled=self.ipxe_enabled)

        # NODE: Try to validate and fetch instance images only
        # if we are in DEPLOYING state.
        if node.provision_state == states.DEPLOYING:
            pxe_info.update(
                pxe_utils.get_instance_image_info(
                    task, ipxe_enabled=self.ipxe_enabled))

        boot_mode_utils.sync_boot_mode(task)

        pxe_options = pxe_utils.build_pxe_config_options(
            task, pxe_info, ipxe_enabled=self.ipxe_enabled,
            ramdisk_params=ramdisk_params)
        # TODO(dtantsur): backwards compability hack, remove in the V release
        if ramdisk_params.get("ipa-api-url"):
            pxe_options["ipa-api-url"] = ramdisk_params["ipa-api-url"]

        if self.ipxe_enabled:
            pxe_config_template = deploy_utils.get_ipxe_config_template(node)
        else:
            pxe_config_template = deploy_utils.get_pxe_config_template(node)

        pxe_utils.create_pxe_config(task, pxe_options,
                                    pxe_config_template,
                                    ipxe_enabled=self.ipxe_enabled)
        persistent = self._persistent_ramdisk_boot(node)
        manager_utils.node_set_boot_device(task, boot_devices.PXE,
                                           persistent=persistent)

        if self.ipxe_enabled and CONF.pxe.ipxe_use_swift:
            kernel_label = '%s_kernel' % mode
            ramdisk_label = '%s_ramdisk' % mode
            pxe_info.pop(kernel_label, None)
            pxe_info.pop(ramdisk_label, None)

        if pxe_info:
            pxe_utils.cache_ramdisk_kernel(task, pxe_info,
                                           ipxe_enabled=self.ipxe_enabled)

        LOG.debug('Ramdisk (i)PXE boot for node %(node)s has been prepared '
                  'with kernel params %(params)s',
                  {'node': node.uuid, 'params': pxe_options})

    @METRICS.timer('PXEBaseMixin.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info. In case of netboot,
        it updates the dhcp entries and switches the PXE config. In case of
        localboot, it cleans up the PXE config.

        :param task: a task from TaskManager.
        :returns: None
        """
        boot_mode_utils.sync_boot_mode(task)

        node = task.node
        boot_option = deploy_utils.get_boot_option(node)
        boot_device = None
        instance_image_info = {}

        if boot_option == "ramdisk":
            instance_image_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=self.ipxe_enabled)
            pxe_utils.cache_ramdisk_kernel(task, instance_image_info,
                                           ipxe_enabled=self.ipxe_enabled)

        if deploy_utils.is_iscsi_boot(task) or boot_option == "ramdisk":
            pxe_utils.prepare_instance_pxe_config(
                task, instance_image_info,
                iscsi_boot=deploy_utils.is_iscsi_boot(task),
                ramdisk_boot=(boot_option == "ramdisk"),
                ipxe_enabled=self.ipxe_enabled)
            boot_device = boot_devices.PXE

        elif boot_option != "local":
            if task.driver.storage.should_write_image(task):
                # Make sure that the instance kernel/ramdisk is cached.
                # This is for the takeover scenario for active nodes.
                instance_image_info = pxe_utils.get_instance_image_info(
                    task, ipxe_enabled=self.ipxe_enabled)
                pxe_utils.cache_ramdisk_kernel(task, instance_image_info,
                                               ipxe_enabled=self.ipxe_enabled)

            # If it's going to PXE boot we need to update the DHCP server
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=self.ipxe_enabled, ip_version=4)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=self.ipxe_enabled, ip_version=6)
            provider = dhcp_factory.DHCPFactory()
            provider.update_dhcp(task, dhcp_opts)

            iwdi = task.node.driver_internal_info.get('is_whole_disk_image')
            try:
                root_uuid_or_disk_id = task.node.driver_internal_info[
                    'root_uuid_or_disk_id'
                ]
            except KeyError:
                if not task.driver.storage.should_write_image(task):
                    pass
                elif not iwdi:
                    LOG.warning("The UUID for the root partition can't be "
                                "found, unable to switch the pxe config from "
                                "deployment mode to service (boot) mode for "
                                "node %(node)s", {"node": task.node.uuid})
                else:
                    LOG.warning("The disk id for the whole disk image can't "
                                "be found, unable to switch the pxe config "
                                "from deployment mode to service (boot) mode "
                                "for node %(node)s. Booting the instance "
                                "from disk.", {"node": task.node.uuid})
                    pxe_utils.clean_up_pxe_config(
                        task, ipxe_enabled=self.ipxe_enabled)
                    boot_device = boot_devices.DISK
            else:
                pxe_utils.build_service_pxe_config(
                    task, instance_image_info, root_uuid_or_disk_id,
                    ipxe_enabled=self.ipxe_enabled)
                boot_device = boot_devices.PXE
        else:
            # If it's going to boot from the local disk, we don't need
            # PXE config files. They still need to be generated as part
            # of the prepare() because the deployment does PXE boot the
            # deploy ramdisk
            pxe_utils.clean_up_pxe_config(task, ipxe_enabled=self.ipxe_enabled)
            boot_device = boot_devices.DISK

        # NOTE(pas-ha) do not re-set boot device on ACTIVE nodes
        # during takeover
        if boot_device and task.node.provision_state != states.ACTIVE:
            persistent = True
            if node.driver_info.get('force_persistent_boot_device',
                                    'Default') == 'Never':
                persistent = False
            manager_utils.node_set_boot_device(task, boot_device,
                                               persistent=persistent)

    def _validate_common(self, task):
        node = task.node

        if not driver_utils.get_node_mac_addresses(task):
            raise exception.MissingParameterValue(
                _("Node %s does not have any port associated with it.")
                % node.uuid)

        if self.ipxe_enabled:
            if not CONF.deploy.http_url or not CONF.deploy.http_root:
                raise exception.MissingParameterValue(_(
                    "iPXE boot is enabled but no HTTP URL or HTTP "
                    "root was specified."))

        # Check the trusted_boot capabilities value.
        deploy_utils.validate_capabilities(node)
        if deploy_utils.is_trusted_boot_requested(node):
            # Check if 'boot_option' and boot mode is compatible with
            # trusted boot.
            if self.ipxe_enabled:
                # NOTE(TheJulia): So in theory (huge theory here, not put to
                # practice or tested), that one can define the kernel as tboot
                # and define the actual kernel and ramdisk as appended data.
                # Similar to how one can iPXE load the XEN hypervisor.
                # tboot mailing list seem to indicate pxe/ipxe support, or
                # more specifically avoiding breaking the scenarios of use,
                # but there is also no definitive documentation on the subject.
                LOG.warning('Trusted boot has been requested for %(node)s in '
                            'concert with iPXE. This is not a supported '
                            'configuration for an ironic deployment.',
                            {'node': node.uuid})
            pxe_utils.validate_boot_parameters_for_trusted_boot(node)

        pxe_utils.parse_driver_info(node)

    @METRICS.timer('PXEBaseMixin.validate')
    def validate(self, task):
        """Validate the PXE-specific info for booting deploy/instance images.

        This method validates the PXE-specific info for booting the
        ramdisk and instance on the node.  If invalid, raises an
        exception; otherwise returns None.

        :param task: a task from TaskManager.
        :returns: None
        :raises: InvalidParameterValue, if some parameters are invalid.
        :raises: MissingParameterValue, if some required parameters are
            missing.
        """
        self._validate_common(task)

        # NOTE(TheJulia): If we're not writing an image, we can skip
        # the remainder of this method.
        if (not task.driver.storage.should_write_image(task)):
            return

        node = task.node
        d_info = deploy_utils.get_image_instance_info(node)
        if (node.driver_internal_info.get('is_whole_disk_image')
                or deploy_utils.get_boot_option(node) == 'local'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        deploy_utils.validate_image_properties(task.context, d_info, props)

    @METRICS.timer('PXEBaseMixin.validate_rescue')
    def validate_rescue(self, task):
        """Validate that the node has required properties for rescue.

        :param task: a TaskManager instance with the node being checked
        :raises: MissingParameterValue if node is missing one or more required
            parameters
        """
        pxe_utils.parse_driver_info(task.node, mode='rescue')

    @METRICS.timer('PXEBaseMixin.validate_inspection')
    def validate_inspection(self, task):
        """Validate that the node has required properties for inspection.

        :param task: A TaskManager instance with the node being checked
        :raises: UnsupportedDriverExtension
        """
        try:
            self._validate_common(task)
        except exception.MissingParameterValue:
            # Fall back to non-managed in-band inspection
            raise exception.UnsupportedDriverExtension(
                driver=task.node.driver, extension='inspection')

    def _persistent_ramdisk_boot(self, node):
        """If the ramdisk should be configured as a persistent boot device."""
        value = node.driver_info.get('force_persistent_boot_device', 'Default')
        if value in {'Always', 'Default', 'Never'}:
            return value == 'Always'
        else:
            return strutils.bool_from_string(value, False)

    _RETRY_ALLOWED_STATES = {states.DEPLOYWAIT, states.CLEANWAIT,
                             states.RESCUEWAIT}

    @METRICS.timer('PXEBaseMixin._check_boot_timeouts')
    @periodics.periodic(spacing=CONF.pxe.boot_retry_check_interval,
                        enabled=bool(CONF.pxe.boot_retry_timeout))
    def _check_boot_timeouts(self, manager, context):
        """Periodically checks whether boot has timed out and retry it.

        :param manager: conductor manager.
        :param context: request context.
        """
        filters = {'provision_state_in': self._RETRY_ALLOWED_STATES,
                   'reserved': False,
                   'maintenance': False,
                   'provisioned_before': CONF.pxe.boot_retry_timeout}
        node_iter = manager.iter_nodes(filters=filters)

        for node_uuid, driver, conductor_group in node_iter:
            try:
                lock_purpose = 'checking PXE boot status'
                with task_manager.acquire(context, node_uuid,
                                          shared=True,
                                          purpose=lock_purpose) as task:
                    self._check_boot_status(task)
            except (exception.NodeLocked, exception.NodeNotFound):
                continue

    def _check_boot_status(self, task):
        if not isinstance(task.driver.boot, PXEBaseMixin):
            return

        if not _should_retry_boot(task.node):
            return

        task.upgrade_lock(purpose='retrying PXE boot')

        # Retry critical checks after acquiring the exclusive lock.
        if (task.node.maintenance or task.node.provision_state
                not in self._RETRY_ALLOWED_STATES
                or not _should_retry_boot(task.node)):
            return

        LOG.info('Booting the ramdisk on node %(node)s is taking more than '
                 '%(timeout)d seconds, retrying boot',
                 {'node': task.node.uuid,
                  'timeout': CONF.pxe.boot_retry_timeout})

        manager_utils.node_power_action(task, states.POWER_OFF)
        # NOTE(dtantsur): retry even persistent boot setting in case it did not
        # work for some reason.
        persistent = self._persistent_ramdisk_boot(task.node)
        manager_utils.node_set_boot_device(task, boot_devices.PXE,
                                           persistent=persistent)
        manager_utils.node_power_action(task, states.POWER_ON)


def _should_retry_boot(node):
    # NOTE(dtantsur): this assumes IPA, do we need to make it generic?
    for field in ('agent_last_heartbeat', 'last_power_state_change'):
        if manager_utils.value_within_timeout(
                node.driver_internal_info.get(field),
                CONF.pxe.boot_retry_timeout):
            # Alive and heartbeating, probably busy with something long
            LOG.debug('Not retrying PXE boot for node %(node)s; its '
                      '%(event)s happened less than %(timeout)d seconds ago',
                      {'node': node.uuid, 'event': field,
                       'timeout': CONF.pxe.boot_retry_timeout})
            return False
    return True
