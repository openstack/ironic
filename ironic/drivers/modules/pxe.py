# -*- encoding: utf-8 -*-
#
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
PXE Driver and supporting meta-classes.
"""

import os

import jinja2
from oslo.config import cfg

from ironic.common import exception
from ironic.common import image_service as service
from ironic.common import images
from ironic.common import keystone
from ironic.common import neutron
from ironic.common import paths
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import log as logging
from ironic.openstack.common import strutils


pxe_opts = [
    cfg.StrOpt('pxe_append_params',
               default='nofb nomodeset vga=normal',
               help='Additional append parameters for baremetal PXE boot.'),
    cfg.StrOpt('pxe_config_template',
               default=paths.basedir_def(
                    'drivers/modules/pxe_config.template'),
               help='Template file for PXE configuration.'),
    cfg.StrOpt('default_ephemeral_format',
               default='ext4',
               help='Default file system format for ephemeral partition, '
                    'if one is created.'),
    cfg.StrOpt('tftp_server',
               default='$my_ip',
               help='IP address of Ironic compute node\'s tftp server.'),
    cfg.StrOpt('tftp_root',
               default='/tftpboot',
               help='Ironic compute node\'s tftp root path.'),
    cfg.StrOpt('images_path',
               default='/var/lib/ironic/images/',
               help='Directory where images are stored on disk.'),
    cfg.StrOpt('tftp_master_path',
               default='/tftpboot/master_images',
               help='Directory where master tftp images are stored on disk.'),
    cfg.StrOpt('instance_master_path',
               default='/var/lib/ironic/master_images',
               help='Directory where master instance images are stored on '
                    'disk.'),
    # NOTE(dekehn): Additional boot files options may be created in the event
    #  other architectures require different boot files.
    cfg.StrOpt('pxe_bootfile_name',
               default='pxelinux.0',
               help='Neutron bootfile DHCP parameter.'),
    cfg.IntOpt('image_cache_size',
               default=1024,
               help='Maximum size (in MiB) of cache for master images, '
               'including those in use'),
    cfg.IntOpt('image_cache_ttl',
               default=60,
               help='Maximum TTL (in minutes) for old master images in cache'),
    ]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(pxe_opts, group='pxe')
CONF.import_opt('use_ipv6', 'ironic.netconf')


def _parse_driver_info(node):
    """Gets the driver-specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node to validate.
    :returns: A dict with the driver_info values.
    """

    info = node.driver_info or {}
    d_info = {}
    d_info['image_source'] = info.get('pxe_image_source')
    d_info['deploy_kernel'] = info.get('pxe_deploy_kernel')
    d_info['deploy_ramdisk'] = info.get('pxe_deploy_ramdisk')
    d_info['root_gb'] = info.get('pxe_root_gb')

    missing_info = []
    for label in d_info:
        if not d_info[label]:
            missing_info.append("pxe_%s" % label)
    if missing_info:
        raise exception.InvalidParameterValue(_(
                "Can not validate PXE bootloader. The following parameters "
                "were not passed to ironic: %s") % missing_info)

    # Internal use only
    d_info['deploy_key'] = info.get('pxe_deploy_key')

    d_info['swap_mb'] = info.get('pxe_swap_mb', 0)
    d_info['ephemeral_gb'] = info.get('pxe_ephemeral_gb', 0)
    d_info['ephemeral_format'] = info.get('pxe_ephemeral_format')

    err_msg_invalid = _("Can not validate PXE bootloader. Invalid parameter "
                        "pxe_%(param)s. Reason: %(reason)s")
    for param in ('root_gb', 'swap_mb', 'ephemeral_gb'):
        try:
            int(d_info[param])
        except ValueError:
            reason = _("'%s' is not an integer value.") % d_info[param]
            raise exception.InvalidParameterValue(err_msg_invalid %
                                            {'param': param, 'reason': reason})

    if d_info['ephemeral_gb'] and not d_info['ephemeral_format']:
        d_info['ephemeral_format'] = CONF.pxe.default_ephemeral_format

    preserve_ephemeral = info.get('pxe_preserve_ephemeral', False)
    try:
        d_info['preserve_ephemeral'] = strutils.bool_from_string(
                                            preserve_ephemeral, strict=True)
    except ValueError as e:
        raise exception.InvalidParameterValue(err_msg_invalid %
                                  {'param': 'preserve_ephemeral', 'reason': e})
    return d_info


def _build_pxe_config(node, pxe_info, ctx):
    """Build the PXE config file for a node

    This method builds the PXE boot configuration file for a node,
    given all the required parameters.

    The resulting file has both a "deploy" and "boot" label, which correspond
    to the two phases of booting. This may be extended later.

    :param pxe_options: A dict of values to set on the configuarion file
    :returns: A formated string with the file content.
    """
    LOG.debug("Building PXE config for deployment %s." % node.uuid)

    # NOTE: we should strip '/' from the end because this is intended for
    # hardcoded ramdisk script
    ironic_api = (CONF.conductor.api_url or
                  keystone.get_service_url()).rstrip('/')

    deploy_key = utils.random_alnum(32)
    driver_info = node['driver_info']
    driver_info['pxe_deploy_key'] = deploy_key
    node['driver_info'] = driver_info
    node.save(ctx)

    pxe_options = {
            'deployment_id': node['uuid'],
            'deployment_key': deploy_key,
            'deployment_iscsi_iqn': "iqn-%s" % node.uuid,
            'deployment_aki_path': pxe_info['deploy_kernel'][1],
            'deployment_ari_path': pxe_info['deploy_ramdisk'][1],
            'aki_path': pxe_info['kernel'][1],
            'ari_path': pxe_info['ramdisk'][1],
            'ironic_api_url': ironic_api,
            'pxe_append_params': CONF.pxe.pxe_append_params,
        }

    tmpl_path, tmpl_file = os.path.split(CONF.pxe.pxe_config_template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    template = env.get_template(tmpl_file)
    return template.render({'pxe_options': pxe_options,
                            'ROOT': '{{ ROOT }}'})


def _get_node_vif_ids(task):
    """Get all Neutron VIF ids for a node.
       This function does not handle multi node operations.

    :param task: a TaskManager instance.
    :returns: A dict of the Node's port UUIDs and their associated VIFs

    """
    port_vifs = {}
    for port in task.ports:
        vif = port.extra.get('vif_port_id')
        if vif:
            port_vifs[port.uuid] = vif
    return port_vifs


def _get_pxe_mac_path(mac):
    """Convert a MAC address into a PXE config file name.

    :param mac: A mac address string in the format xx:xx:xx:xx:xx:xx.
    :returns: the path to the config file.
    """
    return os.path.join(
            CONF.pxe.tftp_root,
            'pxelinux.cfg',
            "01-" + mac.replace(":", "-").lower()
        )


def _get_pxe_config_file_path(node_uuid):
    """Generate the path for an instances PXE config file."""
    return os.path.join(CONF.pxe.tftp_root, node_uuid, 'config')


def _get_pxe_bootfile_name():
    """Returns the pxe_bootfile_name option."""
    return CONF.pxe.pxe_bootfile_name


def _get_image_dir_path(node_uuid):
    """Generate the dir for an instances disk."""
    return os.path.join(CONF.pxe.images_path, node_uuid)


def _get_image_file_path(node_uuid):
    """Generate the full path for an instances disk."""
    return os.path.join(_get_image_dir_path(node_uuid), 'disk')


def _get_token_file_path(node_uuid):
    """Generate the path for PKI token file."""
    return os.path.join(CONF.pxe.tftp_root, 'token-' + node_uuid)


class PXEImageCache(image_cache.ImageCache):
    def __init__(self, master_dir, image_service=None):
        super(PXEImageCache, self).__init__(
            master_dir,
            # MiB -> B
            cache_size=CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            cache_ttl=CONF.pxe.image_cache_ttl * 60,
            image_service=image_service)


class TFTPImageCache(PXEImageCache):
    def __init__(self, image_service=None):
        super(TFTPImageCache, self).__init__(CONF.pxe.tftp_master_path)


class InstanceImageCache(PXEImageCache):
    def __init__(self, image_service=None):
        super(InstanceImageCache, self).__init__(CONF.pxe.instance_master_path)


def _free_disk_space_for(path):
    """Get free disk space on a drive where path is located."""
    stat = os.statvfs(path)
    return stat.f_frsize * stat.f_bavail


def _cleanup_caches_if_required(ctx, cache, images_info):
    # NOTE(dtantsur): I'd prefer to have this code inside ImageCache. But:
    # To reclaim disk space efficiently, this code needs to be aware of
    # all existing caches (e.g. cleaning instance image cache can be
    # much more efficient, than cleaning TFTP cache).
    total_size = sum(images.download_size(ctx, uuid)
                     for (uuid, path) in images_info)
    free = _free_disk_space_for(cache.master_dir)
    if total_size >= free:
        # NOTE(dtantsur): instance cache is larger - always clean it first
        # NOTE(dtantsur): filter caches, whose directory is on the same device
        st_dev = os.stat(cache.master_dir).st_dev
        caches = [c for c in (InstanceImageCache(), TFTPImageCache())
                  if os.stat(c.master_dir).st_dev == st_dev]
        for cache_to_clean in caches:
            cache_to_clean.clean_up()
            free = _free_disk_space_for(cache.master_dir)
            if total_size < free:
                break
        else:
            msg = _("Disk volume where '%(path)s' is located doesn't have "
                    "enough disk space. Required %(required)d MiB, "
                    "only %(actual)d MiB available space present.")
            raise exception.InstanceDeployFailure(reason=msg % {
                'path': cache.master_dir,
                'required': total_size / 1024 / 1024,
                'actual': free / 1024 / 1024
            })


def _fetch_images(ctx, cache, images_info):
    """Check for available disk space and fetch images using ImageCache.

    :param ctx: context
    :param cache: ImageCache instance to use for fetching
    :param images_info: list of tuples (image uuid, destination path)
    :raises: InstanceDeployFailure if unable to find enough disk space
    """
    _cleanup_caches_if_required(ctx, cache, images_info)
    # NOTE(dtantsur): This code can suffer from race condition,
    # if disk space is used between the check and actual download.
    # This is probably unavoidable, as we can't control other
    # (probably unrelated) processes
    for uuid, path in images_info:
        cache.fetch_image(uuid, path, ctx=ctx)


def _cache_tftp_images(ctx, node, pxe_info):
    """Fetch the necessary kernels and ramdisks for the instance."""
    fileutils.ensure_tree(
        os.path.join(CONF.pxe.tftp_root, node.uuid))
    LOG.debug("Fetching kernel and ramdisk for node %s" %
              node.uuid)
    _fetch_images(ctx, TFTPImageCache(), pxe_info.values())


def _cache_instance_image(ctx, node):
    """Fetch the instance's image from Glance

    This method pulls the relevant AMI and associated kernel and ramdisk,
    and the deploy kernel and ramdisk from Glance, and writes them
    to the appropriate places on local disk.

    Both sets of kernel and ramdisk are needed for PXE booting, so these
    are stored under CONF.pxe.tftp_root.

    At present, the AMI is cached and certain files are injected.
    Debian/ubuntu-specific assumptions are made regarding the injected
    files. In a future revision, this functionality will be replaced by a
    more scalable and os-agnostic approach: the deployment ramdisk will
    fetch from Glance directly, and write its own last-mile configuration.

    """
    d_info = _parse_driver_info(node)
    fileutils.ensure_tree(_get_image_dir_path(node.uuid))
    image_path = _get_image_file_path(node.uuid)
    uuid = d_info['image_source']

    LOG.debug("Fetching image %(ami)s for node %(uuid)s" %
              {'ami': uuid, 'uuid': node.uuid})

    _fetch_images(ctx, InstanceImageCache(), [(uuid, image_path)])

    return (uuid, image_path)


def _get_tftp_image_info(node, ctx):
    """Generate the paths for tftp files for this instance

    Raises IronicException if
    - instance does not contain kernel_id or ramdisk_id
    - deploy_kernel_id or deploy_ramdisk_id can not be read from
      driver_info and defaults are not set

    """
    d_info = _parse_driver_info(node)
    image_info = {}

    for label in ('deploy_kernel', 'deploy_ramdisk'):
        image_info[label] = (
            str(d_info[label]).split('/')[-1],
            os.path.join(CONF.pxe.tftp_root, node.uuid, label)
        )

    driver_info = node.driver_info
    labels = ('kernel', 'ramdisk')
    if not (driver_info.get('pxe_kernel') and driver_info.get('pxe_ramdisk')):
        glance_service = service.Service(version=1, context=ctx)
        iproperties = glance_service.show(d_info['image_source'])['properties']
        for label in labels:
            driver_info['pxe_' + label] = str(iproperties[label +
                                              '_id']).split('/')[-1]
        node.driver_info = driver_info
        node.save(ctx)

    for label in labels:
        image_info[label] = (
            driver_info['pxe_' + label],
            os.path.join(CONF.pxe.tftp_root, node.uuid, label)
        )

    return image_info


def _destroy_images(d_info, node_uuid):
    """Delete instance's image file."""
    utils.unlink_without_raise(_get_image_file_path(node_uuid))
    utils.rmtree_without_raise(_get_image_dir_path(node_uuid))
    InstanceImageCache().clean_up()


def _create_token_file(task):
    """Save PKI token to file."""
    token_file_path = _get_token_file_path(task.node.uuid)
    token = task.context.auth_token
    if token:
        utils.write_to_file(token_file_path, token)
    else:
        utils.unlink_without_raise(token_file_path)


def _destroy_token_file(node):
    """Delete PKI token file."""
    token_file_path = _get_token_file_path(node['uuid'])
    utils.unlink_without_raise(token_file_path)


def _remove_internal_attrs(task):
    """Remove internal attributes from driver_info."""
    internal_attrs = ('pxe_deploy_key', 'pxe_kernel', 'pxe_ramdisk')
    driver_info = task.node.driver_info
    for attr in internal_attrs:
        driver_info.pop(attr, None)
    task.node.driver_info = driver_info
    task.node.save(task.context)


def _dhcp_options_for_instance():
    """Retrives the DHCP PXE boot options."""
    return [{'opt_name': 'bootfile-name',
             'opt_value': _get_pxe_bootfile_name()},
            {'opt_name': 'server-ip-address',
             'opt_value': CONF.pxe.tftp_server},
            {'opt_name': 'tftp-server',
             'opt_value': CONF.pxe.tftp_server}
            ]


def _update_neutron(task):
    """Send or update the DHCP BOOT options to Neutron for this node."""
    options = _dhcp_options_for_instance()
    vifs = _get_node_vif_ids(task)
    if not vifs:
        LOG.warning(_("No VIFs found for node %(node)s when attempting to "
                      "update Neutron DHCP BOOT options."),
                      {'node': task.node.uuid})
        return

    # TODO(deva): decouple instantiation of NeutronAPI from task.context.
    #             Try to use the user's task.context.auth_token, but if it
    #             is not present, fall back to a server-generated context.
    #             We don't need to recreate this in every method call.
    api = neutron.NeutronAPI(task.context)
    failures = []
    for port_id, port_vif in vifs.iteritems():
        try:
            api.update_port_dhcp_opts(port_vif, options)
        except exception.FailedToUpdateDHCPOptOnPort:
            failures.append(port_id)

    if failures:
        if len(failures) == len(vifs):
            raise exception.FailedToUpdateDHCPOptOnPort(_(
                "Failed to set DHCP BOOT options for any port on node %s.") %
                task.node.uuid)
        else:
            LOG.warning(_("Some errors were encountered when updating the "
                          "DHCP BOOT options for node %(node)s on the "
                          "following ports: %(ports)s."),
                          {'node': task.node.uuid, 'ports': failures})


def _create_pxe_config(task, pxe_info):
    """Generate pxe configuration file and link mac ports to it for
    tftp booting.
    """
    fileutils.ensure_tree(os.path.join(CONF.pxe.tftp_root,
                                       task.node.uuid))
    fileutils.ensure_tree(os.path.join(CONF.pxe.tftp_root,
                                       'pxelinux.cfg'))

    pxe_config_file_path = _get_pxe_config_file_path(task.node.uuid)
    pxe_config = _build_pxe_config(task.node, pxe_info, task.context)
    utils.write_to_file(pxe_config_file_path, pxe_config)
    for port in driver_utils.get_node_mac_addresses(task):
        mac_path = _get_pxe_mac_path(port)
        utils.unlink_without_raise(mac_path)
        utils.create_link_without_raise(pxe_config_file_path, mac_path)


def _check_image_size(task):
    """Check if the requested image is larger than the root partition size."""
    driver_info = _parse_driver_info(task.node)
    image_path = _get_image_file_path(task.node.uuid)
    image_mb = deploy_utils.get_image_mb(image_path)
    root_mb = 1024 * int(driver_info['root_gb'])
    if image_mb > root_mb:
        msg = (_('Root partition is too small for requested image. '
                 'Image size: %(image_mb)d MB, Root size: %(root_mb)d MB')
               % {'image_mb': image_mb, 'root_mb': root_mb})
        raise exception.InstanceDeployFailure(msg)


def _validate_glance_image(ctx, driver_info):
    """Validate the image in Glance.

    Check if the image exist in Glance and if it contains the
    'kernel_id' and 'ramdisk_id' properties.

    :raises: InvalidParameterValue.
    """
    image_id = driver_info['image_source']
    try:
        glance_service = service.Service(version=1, context=ctx)
        image_props = glance_service.show(image_id)['properties']
    except (exception.GlanceConnectionFailed,
            exception.ImageNotAuthorized,
            exception.Invalid):
        raise exception.InvalidParameterValue(_(
            "Failed to connect to Glance to get the properties "
            "of the image %s") % image_id)
    except exception.ImageNotFound:
        raise exception.InvalidParameterValue(_(
            "Image %s not found in Glance") % image_id)

    missing_props = []
    for prop in ('kernel_id', 'ramdisk_id'):
        if not image_props.get(prop):
            missing_props.append(prop)

    if missing_props:
        props = ', '.join(missing_props)
        raise exception.InvalidParameterValue(_(
            "Image %(image)s is missing the following properties: "
            "%(properties)s") % {'image': image_id, 'properties': props})


class PXEDeploy(base.DeployInterface):
    """PXE Deploy Interface: just a stub until the real driver is ported."""

    def validate(self, task, node):
        """Validate the driver-specific Node deployment info.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue.
        """
        node = task.node
        if not driver_utils.get_node_mac_addresses(task):
            raise exception.InvalidParameterValue(_("Node %s does not have "
                                "any port associated with it.") % node.uuid)
        d_info = _parse_driver_info(node)

        # Try to get the URL of the Ironic API
        try:
            # TODO(lucasagomes): Validate the format of the URL
            CONF.conductor.api_url or keystone.get_service_url()
        except (exception.CatalogFailure,
                exception.CatalogNotFound,
                exception.CatalogUnauthorized):
            raise exception.InvalidParameterValue(_(
                "Couldn't get the URL of the Ironic API service from the "
                "configuration file or keystone catalog."))

        _validate_glance_image(task.context, d_info)

    @task_manager.require_exclusive_lock
    def deploy(self, task):
        """Start deployment of the task's node'.

        Fetches instance image, creates a temporary keystone token file,
        updates the Neutron DHCP port options for next boot, and issues a
        reboot request to the power driver.
        This causes the node to boot into the deployment ramdisk and triggers
        the next phase of PXE-based deployment via
        VendorPassthru._continue_deploy().

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DEPLOYING.
        """
        _cache_instance_image(task.context, task.node)
        _check_image_size(task)

        # TODO(yuriyz): more secure way needed for pass auth token
        #               to deploy ramdisk
        _create_token_file(task)
        _update_neutron(task)
        manager_utils.node_set_boot_device(task, 'pxe', persistent=True)
        manager_utils.node_power_action(task, states.REBOOT)

        return states.DEPLOYWAIT

    @task_manager.require_exclusive_lock
    def tear_down(self, task):
        """Tear down a previous deployment on the task's node.

        Power off the node. All actual clean-up is done in the clean_up()
        method which should be called separately.

        :param task: a TaskManager instance containing the node to act on.
        :returns: deploy state DELETED.
        """
        manager_utils.node_power_action(task, states.POWER_OFF)
        _remove_internal_attrs(task)

        return states.DELETED

    def prepare(self, task):
        """Prepare the deployment environment for this task's node.

        Generates the TFTP configuration for PXE-booting both the deployment
        and user images, fetches the TFTP image from Glance and add it to the
        local cache.

        :param task: a TaskManager instance containing the node to act on.
        """
        # TODO(deva): optimize this if rerun on existing files
        pxe_info = _get_tftp_image_info(task.node, task.context)
        _create_pxe_config(task, pxe_info)
        _cache_tftp_images(task.context, task.node, pxe_info)

    def clean_up(self, task):
        """Clean up the deployment environment for the task's node.

        Unlinks TFTP and instance images and triggers image cache cleanup.
        Removes the TFTP configuration files for this node. As a precaution,
        this method also ensures the keystone auth token file was removed.

        :param task: a TaskManager instance containing the node to act on.
        """
        node = task.node
        pxe_info = _get_tftp_image_info(node, task.context)
        d_info = _parse_driver_info(node)
        for label in pxe_info:
            path = pxe_info[label][1]
            utils.unlink_without_raise(path)
        TFTPImageCache().clean_up()

        utils.unlink_without_raise(_get_pxe_config_file_path(
                node.uuid))
        for port in driver_utils.get_node_mac_addresses(task):
            mac_path = _get_pxe_mac_path(port)
            utils.unlink_without_raise(mac_path)

        utils.rmtree_without_raise(
                os.path.join(CONF.pxe.tftp_root, node.uuid))

        _destroy_images(d_info, node.uuid)
        _destroy_token_file(node)

    def take_over(self, task):
        _update_neutron(task)


class VendorPassthru(base.VendorInterface):
    """Interface to mix IPMI and PXE vendor-specific interfaces."""

    def _get_deploy_info(self, node, **kwargs):
        d_info = _parse_driver_info(node)

        deploy_key = kwargs.get('key')
        if d_info['deploy_key'] != deploy_key:
            raise exception.InvalidParameterValue(_("Deploy key does not"
                                                    " match"))

        params = {'address': kwargs.get('address'),
                  'port': kwargs.get('port', '3260'),
                  'iqn': kwargs.get('iqn'),
                  'lun': kwargs.get('lun', '1'),
                  'image_path': _get_image_file_path(node.uuid),
                  'pxe_config_path': _get_pxe_config_file_path(
                                                    node.uuid),
                  'root_mb': 1024 * int(d_info['root_gb']),
                  'swap_mb': int(d_info['swap_mb']),
                  'ephemeral_mb': 1024 * int(d_info['ephemeral_gb']),
                  'preserve_ephemeral': d_info['preserve_ephemeral'],
            }

        missing = [key for key in params.keys() if params[key] is None]
        if missing:
            raise exception.InvalidParameterValue(_(
                    "Parameters %s were not passed to ironic"
                    " for deploy.") % missing)

        # ephemeral_format is nullable
        params['ephemeral_format'] = d_info.get('ephemeral_format')

        return params

    def validate(self, task, **kwargs):
        method = kwargs['method']
        if method == 'pass_deploy_info':
            self._get_deploy_info(task.node, **kwargs)
        else:
            raise exception.InvalidParameterValue(_(
                "Unsupported method (%s) passed to PXE driver.")
                % method)

        return True

    @task_manager.require_exclusive_lock
    def _continue_deploy(self, task, **kwargs):
        """Resume a deployment upon getting POST data from deploy ramdisk.

        This method raises no exceptions because it is intended to be
        invoked asynchronously as a callback from the deploy ramdisk.
        """
        node = task.node
        driver_info = _parse_driver_info(node)

        def _set_failed_state(msg):
            node.provision_state = states.DEPLOYFAIL
            node.target_provision_state = states.NOSTATE
            node.save(task.context)
            try:
                manager_utils.node_power_action(task, states.POWER_OFF)
            except Exception:
                msg = (_('Node %s failed to power off while handling deploy '
                         'failure. This may be a serious condition. Node '
                         'should be removed from Ironic or put in maintenance '
                         'mode until the problem is resolved.') % node.uuid)
                LOG.error(msg)
            finally:
                # NOTE(deva): node_power_action() erases node.last_error
                #             so we need to set it again here.
                node.last_error = msg
                node.save(task.context)

        if node.provision_state != states.DEPLOYWAIT:
            LOG.error(_('Node %s is not waiting to be deployed.') %
                      node.uuid)
            return
        node.provision_state = states.DEPLOYING
        node.save(task.context)
        # remove cached keystone token immediately
        _destroy_token_file(node)

        params = self._get_deploy_info(node, **kwargs)
        ramdisk_error = kwargs.get('error')

        if ramdisk_error:
            LOG.error(_('Error returned from PXE deploy ramdisk: %s')
                    % ramdisk_error)
            _set_failed_state(_('Failure in PXE deploy ramdisk.'))
            _destroy_images(driver_info, node.uuid)
            return

        LOG.info(_('Continuing deployment for node %(node)s, params '
                   '%(params)s') % {'node': node.uuid, 'params': params})

        try:
            deploy_utils.deploy(**params)
        except Exception as e:
            LOG.error(_('PXE deploy failed for instance %(instance)s. '
                        'Error: %(error)s') % {'instance': node.instance_uuid,
                                               'error': e})
            _set_failed_state(_('PXE driver failed to continue deployment.'))
        else:
            LOG.info(_('Deployment to node %s done') % node.uuid)
            node.provision_state = states.ACTIVE
            node.target_provision_state = states.NOSTATE
            node.save(task.context)

        _destroy_images(driver_info, node.uuid)

    def vendor_passthru(self, task, **kwargs):
        method = kwargs['method']
        if method == 'pass_deploy_info':
            self._continue_deploy(task, **kwargs)
