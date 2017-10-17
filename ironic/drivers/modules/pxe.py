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

import os

from ironic_lib import metrics_utils
from ironic_lib import utils as ironic_utils
from oslo_log import log as logging
from oslo_utils import fileutils
from oslo_utils import strutils

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service as service
from ironic.common import images
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils
from ironic import objects
LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

REQUIRED_PROPERTIES = {
    'deploy_kernel': _("UUID (from Glance) of the deployment kernel. "
                       "Required."),
    'deploy_ramdisk': _("UUID (from Glance) of the ramdisk that is "
                        "mounted at boot time. Required."),
}
OPTIONAL_PROPERTIES = {
    'force_persistent_boot_device': _("True to enable persistent behavior "
                                      "when the boot device is set during "
                                      "deploy and cleaning operations. "
                                      "Defaults to False. Optional."),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def _parse_driver_info(node):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the driver_info values.
    :raises: MissingParameterValue
    """
    info = node.driver_info
    d_info = {k: info.get(k) for k in ('deploy_kernel', 'deploy_ramdisk')}
    error_msg = _("Cannot validate PXE bootloader. Some parameters were"
                  " missing in node's driver_info")
    deploy_utils.check_for_missing_params(d_info, error_msg)
    return d_info


def _get_instance_image_info(node, ctx):
    """Generate the paths for TFTP files for instance related images.

    This method generates the paths for instance kernel and
    instance ramdisk. This method also updates the node, so caller should
    already have a non-shared lock on the node.

    :param node: a node object
    :param ctx: context
    :returns: a dictionary whose keys are the names of the images (kernel,
        ramdisk) and values are the absolute paths of them. If it's a whole
        disk image or node is configured for localboot,
        it returns an empty dictionary.
    """
    image_info = {}
    # NOTE(pas-ha) do not report image kernel and ramdisk for
    # local boot or whole disk images so that they are not cached
    if (node.driver_internal_info.get('is_whole_disk_image') or
        deploy_utils.get_boot_option(node) == 'local'):
            return image_info

    root_dir = pxe_utils.get_root_dir()
    i_info = node.instance_info
    labels = ('kernel', 'ramdisk')
    d_info = deploy_utils.get_image_instance_info(node)
    if not (i_info.get('kernel') and i_info.get('ramdisk')):
        glance_service = service.GlanceImageService(
            version=CONF.glance.glance_api_version, context=ctx)
        iproperties = glance_service.show(d_info['image_source'])['properties']
        for label in labels:
            i_info[label] = str(iproperties[label + '_id'])
        node.instance_info = i_info
        node.save()

    for label in labels:
        image_info[label] = (
            i_info[label],
            os.path.join(root_dir, node.uuid, label)
        )

    return image_info


def _get_deploy_image_info(node):
    """Generate the paths for TFTP files for deploy images.

    This method generates the paths for the deploy kernel and
    deploy ramdisk.

    :param node: a node object
    :returns: a dictionary whose keys are the names of the images (
        deploy_kernel, deploy_ramdisk) and values are the absolute
        paths of them.
    :raises: MissingParameterValue, if deploy_kernel/deploy_ramdisk is
        missing in node's driver_info.
    """
    d_info = _parse_driver_info(node)
    return pxe_utils.get_deploy_kr_info(node.uuid, d_info)


def _build_deploy_pxe_options(task, pxe_info):
    pxe_opts = {}
    node = task.node

    for label, option in (('deploy_kernel', 'deployment_aki_path'),
                          ('deploy_ramdisk', 'deployment_ari_path')):
        if CONF.pxe.ipxe_enabled:
            image_href = pxe_info[label][0]
            if (CONF.pxe.ipxe_use_swift and
                service_utils.is_glance_image(image_href)):
                    pxe_opts[option] = images.get_temp_url_for_glance_image(
                        task.context, image_href)
            else:
                pxe_opts[option] = '/'.join([CONF.deploy.http_url, node.uuid,
                                            label])
        else:
            pxe_opts[option] = pxe_utils.get_path_relative_to_tftp_root(
                pxe_info[label][1])
    return pxe_opts


def _build_instance_pxe_options(task, pxe_info):
    pxe_opts = {}
    node = task.node

    for label, option in (('kernel', 'aki_path'),
                          ('ramdisk', 'ari_path')):
        if label in pxe_info:
            if CONF.pxe.ipxe_enabled:
                # NOTE(pas-ha) do not use Swift TempURLs for kernel and
                # ramdisk of user image when boot_option is not local,
                # as this breaks instance reboot later when temp urls
                # have timed out.
                pxe_opts[option] = '/'.join(
                    [CONF.deploy.http_url, node.uuid, label])
            else:
                # It is possible that we don't have kernel/ramdisk or even
                # image_source to determine if it's a whole disk image or not.
                # For example, when transitioning to 'available' state
                # for first time from 'manage' state.
                pxe_opts[option] = pxe_utils.get_path_relative_to_tftp_root(
                    pxe_info[label][1])

    # These are dummy values to satisfy elilo.
    # image and initrd fields in elilo config cannot be blank.
    pxe_opts.setdefault('aki_path', 'no_kernel')
    pxe_opts.setdefault('ari_path', 'no_ramdisk')

    return pxe_opts


def _build_extra_pxe_options():
    # Enable debug in IPA according to CONF.debug if it was not
    # specified yet
    pxe_append_params = CONF.pxe.pxe_append_params
    if CONF.debug and 'ipa-debug' not in pxe_append_params:
        pxe_append_params += ' ipa-debug=1'

    return {'pxe_append_params': pxe_append_params,
            'tftp_server': CONF.pxe.tftp_server,
            'ipxe_timeout': CONF.pxe.ipxe_timeout * 1000}


def _build_pxe_config_options(task, pxe_info, service=False):
    """Build the PXE config options for a node

    This method builds the PXE boot options for a node,
    given all the required parameters.

    The options should then be passed to pxe_utils.create_pxe_config to
    create the actual config files.

    :param task: A TaskManager object
    :param pxe_info: a dict of values to set on the configuration file
    :param service: if True, build "service mode" pxe config for netboot-ed
        user image and skip adding deployment image kernel and ramdisk info
        to PXE options.
    :returns: A dictionary of pxe options to be used in the pxe bootfile
        template.
    """
    if service:
        pxe_options = {}
    elif (task.node.driver_internal_info.get('boot_from_volume') and
            CONF.pxe.ipxe_enabled):
        pxe_options = _get_volume_pxe_options(task)
    else:
        pxe_options = _build_deploy_pxe_options(task, pxe_info)

    # NOTE(pas-ha) we still must always add user image kernel and ramdisk info
    # as later during switching PXE config to service mode the template
    # will not be regenerated anew, but instead edited as-is.
    # This can be changed later if/when switching PXE config will also use
    # proper templating instead of editing existing files on disk.
    pxe_options.update(_build_instance_pxe_options(task, pxe_info))
    pxe_options.update(_build_extra_pxe_options())

    return pxe_options


def _build_service_pxe_config(task, instance_image_info,
                              root_uuid_or_disk_id):
    node = task.node
    pxe_config_path = pxe_utils.get_pxe_config_file_path(node.uuid)
    # NOTE(pas-ha) if it is takeover of ACTIVE node,
    # first ensure that basic PXE configs and links
    # are in place before switching pxe config
    if (node.provision_state == states.ACTIVE and
            not os.path.isfile(pxe_config_path)):
        pxe_options = _build_pxe_config_options(task, instance_image_info,
                                                service=True)
        pxe_config_template = deploy_utils.get_pxe_config_template(node)
        pxe_utils.create_pxe_config(task, pxe_options, pxe_config_template)
    iwdi = node.driver_internal_info.get('is_whole_disk_image')
    deploy_utils.switch_pxe_config(
        pxe_config_path, root_uuid_or_disk_id,
        deploy_utils.get_boot_mode_for_deploy(node),
        iwdi, deploy_utils.is_trusted_boot_requested(node),
        deploy_utils.is_iscsi_boot(task))


def _get_volume_pxe_options(task):
    """Identify volume information for iPXE template generation."""
    def __return_item_or_first_if_list(item):
        if isinstance(item, list):
            return item[0]
        else:
            return item

    def __get_property(properties, key):
        prop = __return_item_or_first_if_list(properties.get(key, ''))
        if prop is not '':
            return prop
        return __return_item_or_first_if_list(properties.get(key + 's', ''))

    def __generate_iscsi_url(properties):
        """Returns iscsi url."""
        portal = __get_property(properties, 'target_portal')
        iqn = __get_property(properties, 'target_iqn')
        lun = __get_property(properties, 'target_lun')

        if ':' in portal:
            host, port = portal.split(':')
        else:
            host = portal
            port = ''
        return ("iscsi:%(host)s::%(port)s:%(lun)s:%(iqn)s" %
                {'host': host, 'port': port, 'lun': lun, 'iqn': iqn})

    pxe_options = {}
    node = task.node
    boot_volume = node.driver_internal_info.get('boot_from_volume')
    volume = objects.VolumeTarget.get_by_uuid(task.context,
                                              boot_volume)
    properties = volume.properties
    if 'iscsi' in volume['volume_type']:
        if 'auth_username' in properties:
            pxe_options['username'] = properties['auth_username']
        if 'auth_password' in properties:
            pxe_options['password'] = properties['auth_password']
        iscsi_initiator_iqn = None
        for vc in task.volume_connectors:
            if vc.type == 'iqn':
                iscsi_initiator_iqn = vc.connector_id

        pxe_options.update(
            {'iscsi_boot_url': __generate_iscsi_url(volume.properties),
             'iscsi_initiator_iqn': iscsi_initiator_iqn})
        # NOTE(TheJulia): This may be the route to multi-path, define
        # volumes via sanhook in the ipxe template and let the OS sort it out.
        additional_targets = []
        for target in task.volume_targets:
            if target.boot_index != 0 and 'iscsi' in target.volume_type:
                additional_targets.append(
                    __generate_iscsi_url(target.properties))
        pxe_options.update({'iscsi_volumes': additional_targets,
                            'boot_from_volume': True})
    # TODO(TheJulia): FibreChannel boot, i.e. wwpn in volume_type
    # for FCoE, should go here.
    return pxe_options


@METRICS.timer('validate_boot_option_for_trusted_boot')
def validate_boot_parameters_for_trusted_boot(node):
    """Check if boot parameters are valid for trusted boot."""
    boot_mode = deploy_utils.get_boot_mode_for_deploy(node)
    boot_option = deploy_utils.get_boot_option(node)
    is_whole_disk_image = node.driver_internal_info.get('is_whole_disk_image')
    # 'is_whole_disk_image' is not supported by trusted boot, because there is
    # no Kernel/Ramdisk to measure at all.
    if (boot_mode != 'bios' or
        is_whole_disk_image or
        boot_option != 'netboot'):
        msg = (_("Trusted boot is only supported in BIOS boot mode with "
                 "netboot and without whole_disk_image, but Node "
                 "%(node_uuid)s was configured with boot_mode: %(boot_mode)s, "
                 "boot_option: %(boot_option)s, is_whole_disk_image: "
                 "%(is_whole_disk_image)s: at least one of them is wrong, and "
                 "this can be caused by enable secure boot.") %
               {'node_uuid': node.uuid, 'boot_mode': boot_mode,
                'boot_option': boot_option,
                'is_whole_disk_image': is_whole_disk_image})
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)


@image_cache.cleanup(priority=25)
class TFTPImageCache(image_cache.ImageCache):
    def __init__(self):
        super(TFTPImageCache, self).__init__(
            CONF.pxe.tftp_master_path,
            # MiB -> B
            cache_size=CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            cache_ttl=CONF.pxe.image_cache_ttl * 60)


def _cache_ramdisk_kernel(ctx, node, pxe_info):
    """Fetch the necessary kernels and ramdisks for the instance."""
    fileutils.ensure_tree(
        os.path.join(pxe_utils.get_root_dir(), node.uuid))
    LOG.debug("Fetching necessary kernel and ramdisk for node %s",
              node.uuid)
    deploy_utils.fetch_images(ctx, TFTPImageCache(), list(pxe_info.values()),
                              CONF.force_raw_images)


def _clean_up_pxe_env(task, images_info):
    """Cleanup PXE environment of all the images in images_info.

    Cleans up the PXE environment for the mentioned images in
    images_info.

    :param task: a TaskManager object
    :param images_info: A dictionary of images whose keys are the image names
        to be cleaned up (kernel, ramdisk, etc) and values are a tuple of
        identifier and absolute path.
    """
    for label in images_info:
        path = images_info[label][1]
        ironic_utils.unlink_without_raise(path)

    pxe_utils.clean_up_pxe_config(task)
    TFTPImageCache().clean_up()


class PXEBoot(base.BootInterface):

    def __init__(self):
        self.capabilities = ['iscsi_volume_boot']
        if CONF.pxe.ipxe_enabled:
            pxe_utils.create_ipxe_boot_script()

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return COMMON_PROPERTIES

    @METRICS.timer('PXEBoot.validate')
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
        node = task.node

        if not driver_utils.get_node_mac_addresses(task):
            raise exception.MissingParameterValue(
                _("Node %s does not have any port associated with it.")
                % node.uuid)

        if CONF.pxe.ipxe_enabled:
            if (not CONF.deploy.http_url or
                not CONF.deploy.http_root):
                raise exception.MissingParameterValue(_(
                    "iPXE boot is enabled but no HTTP URL or HTTP "
                    "root was specified."))

        # Check the trusted_boot capabilities value.
        deploy_utils.validate_capabilities(node)
        if deploy_utils.is_trusted_boot_requested(node):
            # Check if 'boot_option' and boot mode is compatible with
            # trusted boot.
            validate_boot_parameters_for_trusted_boot(node)

        _parse_driver_info(node)
        # NOTE(TheJulia): If we're not writing an image, we can skip
        # the remainder of this method.
        if not task.driver.storage.should_write_image(task):
            return

        d_info = deploy_utils.get_image_instance_info(node)
        if (node.driver_internal_info.get('is_whole_disk_image') or
                deploy_utils.get_boot_option(node) == 'local'):
            props = []
        elif service_utils.is_glance_image(d_info['image_source']):
            props = ['kernel_id', 'ramdisk_id']
        else:
            props = ['kernel', 'ramdisk']
        deploy_utils.validate_image_properties(task.context, d_info, props)

    @METRICS.timer('PXEBoot.prepare_ramdisk')
    def prepare_ramdisk(self, task, ramdisk_params):
        """Prepares the boot of Ironic ramdisk using PXE.

        This method prepares the boot of the deploy kernel/ramdisk after
        reading relevant information from the node's driver_info and
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

        if CONF.pxe.ipxe_enabled:
            # NOTE(mjturek): At this point, the ipxe boot script should
            # already exist as it is created at startup time. However, we
            # call the boot script create method here to assert its
            # existence and handle the unlikely case that it wasn't created
            # or was deleted.
            pxe_utils.create_ipxe_boot_script()

        dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
        provider = dhcp_factory.DHCPFactory()
        provider.update_dhcp(task, dhcp_opts)

        pxe_info = _get_deploy_image_info(node)

        # NODE: Try to validate and fetch instance images only
        # if we are in DEPLOYING state.
        if node.provision_state == states.DEPLOYING:
            pxe_info.update(_get_instance_image_info(node, task.context))

        pxe_options = _build_pxe_config_options(task, pxe_info)
        pxe_options.update(ramdisk_params)

        pxe_config_template = deploy_utils.get_pxe_config_template(node)

        pxe_utils.create_pxe_config(task, pxe_options,
                                    pxe_config_template)
        persistent = strutils.bool_from_string(
            node.driver_info.get('force_persistent_boot_device',
                                 False))
        manager_utils.node_set_boot_device(task, boot_devices.PXE,
                                           persistent=persistent)

        if CONF.pxe.ipxe_enabled and CONF.pxe.ipxe_use_swift:
            pxe_info.pop('deploy_kernel', None)
            pxe_info.pop('deploy_ramdisk', None)
        if pxe_info:
            _cache_ramdisk_kernel(task.context, node, pxe_info)

    @METRICS.timer('PXEBoot.clean_up_ramdisk')
    def clean_up_ramdisk(self, task):
        """Cleans up the boot of ironic ramdisk.

        This method cleans up the PXE environment that was setup for booting
        the deploy ramdisk. It unlinks the deploy kernel/ramdisk in the node's
        directory in tftproot and removes it's PXE config.

        :param task: a task from TaskManager.
        :returns: None
        """
        node = task.node
        try:
            images_info = _get_deploy_image_info(node)
        except exception.MissingParameterValue as e:
            LOG.warning('Could not get deploy image info '
                        'to clean up images for node %(node)s: %(err)s',
                        {'node': node.uuid, 'err': e})
        else:
            _clean_up_pxe_env(task, images_info)

    @METRICS.timer('PXEBoot.prepare_instance')
    def prepare_instance(self, task):
        """Prepares the boot of instance.

        This method prepares the boot of the instance after reading
        relevant information from the node's instance_info. In case of netboot,
        it updates the dhcp entries and switches the PXE config. In case of
        localboot, it cleans up the PXE config.

        :param task: a task from TaskManager.
        :returns: None
        """
        node = task.node
        boot_option = deploy_utils.get_boot_option(node)
        boot_device = None

        if deploy_utils.is_iscsi_boot(task):
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            provider = dhcp_factory.DHCPFactory()
            provider.update_dhcp(task, dhcp_opts)

            # configure iPXE for iscsi boot
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)
            if not os.path.isfile(pxe_config_path):
                pxe_options = _build_pxe_config_options(task, {})
                pxe_config_template = (
                    deploy_utils.get_pxe_config_template(node))
                pxe_utils.create_pxe_config(
                    task, pxe_options, pxe_config_template)
            deploy_utils.switch_pxe_config(
                pxe_config_path, None,
                deploy_utils.get_boot_mode_for_deploy(node), False,
                iscsi_boot=True)
            boot_device = boot_devices.PXE

        elif boot_option != "local":
            if task.driver.storage.should_write_image(task):
                # Make sure that the instance kernel/ramdisk is cached.
                # This is for the takeover scenario for active nodes.
                instance_image_info = _get_instance_image_info(
                    task.node, task.context)
                _cache_ramdisk_kernel(task.context, task.node,
                                      instance_image_info)

            # If it's going to PXE boot we need to update the DHCP server
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
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
                                "for node %(node)s", {"node": task.node.uuid})
            else:
                _build_service_pxe_config(task, instance_image_info,
                                          root_uuid_or_disk_id)
                boot_device = boot_devices.PXE
        else:
            # If it's going to boot from the local disk, we don't need
            # PXE config files. They still need to be generated as part
            # of the prepare() because the deployment does PXE boot the
            # deploy ramdisk
            pxe_utils.clean_up_pxe_config(task)
            boot_device = boot_devices.DISK

        # NOTE(pas-ha) do not re-set boot device on ACTIVE nodes
        # during takeover
        if boot_device and task.node.provision_state != states.ACTIVE:
            manager_utils.node_set_boot_device(task, boot_device,
                                               persistent=True)

    @METRICS.timer('PXEBoot.clean_up_instance')
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
            images_info = _get_instance_image_info(node, task.context)
        except exception.MissingParameterValue as e:
            LOG.warning('Could not get instance image info '
                        'to clean up images for node %(node)s: %(err)s',
                        {'node': node.uuid, 'err': e})
        else:
            _clean_up_pxe_env(task, images_info)
