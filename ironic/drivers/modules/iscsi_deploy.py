# Copyright 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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

import os

from oslo.config import cfg
from oslo.utils import strutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common import image_service as service
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import log as logging

LOG = logging.getLogger(__name__)

# NOTE(rameshg87): This file now registers some of opts in pxe group.
# This is acceptable for now as a future refactoring into
# separate boot and deploy interfaces is planned, and moving config
# options twice is not recommended.  Hence we would move the parameters
# to the appropriate place in the final refactoring.
pxe_opts = [
    cfg.StrOpt('pxe_append_params',
               default='nofb nomodeset vga=normal',
               help='Additional append parameters for baremetal PXE boot.'),
    cfg.StrOpt('default_ephemeral_format',
               default='ext4',
               help='Default file system format for ephemeral partition, '
                    'if one is created.'),
    cfg.StrOpt('images_path',
               default='/var/lib/ironic/images/',
               help='Directory where images are stored on disk.'),
    cfg.StrOpt('instance_master_path',
               default='/var/lib/ironic/master_images',
               help='Directory where master instance images are stored on '
                    'disk.'),
    cfg.IntOpt('image_cache_size',
               default=20480,
               help='Maximum size (in MiB) of cache for master images, '
                    'including those in use.'),
    # 10080 here is 1 week - 60*24*7. It is entirely arbitrary in the absence
    # of a facility to disable the ttl entirely.
    cfg.IntOpt('image_cache_ttl',
               default=10080,
               help='Maximum TTL (in minutes) for old master images in '
               'cache.'),
    cfg.StrOpt('disk_devices',
               default='cciss/c0d0,sda,hda,vda',
               help='The disk devices to scan while doing the deploy.'),
    ]

CONF = cfg.CONF
CONF.register_opts(pxe_opts, group='pxe')


@image_cache.cleanup(priority=50)
class InstanceImageCache(image_cache.ImageCache):

    def __init__(self, image_service=None):
        super(self.__class__, self).__init__(
            CONF.pxe.instance_master_path,
            # MiB -> B
            cache_size=CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            cache_ttl=CONF.pxe.image_cache_ttl * 60,
            image_service=image_service)


def _get_image_dir_path(node_uuid):
    """Generate the dir for an instances disk."""
    return os.path.join(CONF.pxe.images_path, node_uuid)


def _get_image_file_path(node_uuid):
    """Generate the full path for an instances disk."""
    return os.path.join(_get_image_dir_path(node_uuid), 'disk')


def parse_instance_info(node):
    """Gets the instance specific Node deployment info.

    This method validates whether the 'instance_info' property of the
    supplied node contains the required information for this driver to
    deploy images to the node.

    :param node: a single Node.
    :returns: A dict with the instance_info values.
    :raises: MissingParameterValue, if any of the required parameters are
        missing.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """
    info = node.instance_info
    i_info = {}
    i_info['image_source'] = info.get('image_source')
    i_info['root_gb'] = info.get('root_gb')

    error_msg = _("Cannot validate iSCSI deploy. Some parameters were missing"
                  " in node's instance_info")
    deploy_utils.check_for_missing_params(i_info, error_msg)

    # Internal use only
    i_info['deploy_key'] = info.get('deploy_key')

    i_info['swap_mb'] = info.get('swap_mb', 0)
    i_info['ephemeral_gb'] = info.get('ephemeral_gb', 0)
    i_info['ephemeral_format'] = info.get('ephemeral_format')

    err_msg_invalid = _("Cannot validate parameter for iSCSI deploy. "
                        "Invalid parameter %(param)s. Reason: %(reason)s")
    for param in ('root_gb', 'swap_mb', 'ephemeral_gb'):
        try:
            int(i_info[param])
        except ValueError:
            reason = _("'%s' is not an integer value.") % i_info[param]
            raise exception.InvalidParameterValue(err_msg_invalid %
                                            {'param': param, 'reason': reason})

    if i_info['ephemeral_gb'] and not i_info['ephemeral_format']:
        i_info['ephemeral_format'] = CONF.pxe.default_ephemeral_format

    preserve_ephemeral = info.get('preserve_ephemeral', False)
    try:
        i_info['preserve_ephemeral'] = strutils.bool_from_string(
                                            preserve_ephemeral, strict=True)
    except ValueError as e:
        raise exception.InvalidParameterValue(err_msg_invalid %
                                  {'param': 'preserve_ephemeral', 'reason': e})
    return i_info


def check_image_size(task):
    """Check if the requested image is larger than the root partition size.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InstanceDeployFailure if size of the image is greater than root
        partition.
    """
    i_info = parse_instance_info(task.node)
    image_path = _get_image_file_path(task.node.uuid)
    image_mb = deploy_utils.get_image_mb(image_path)
    root_mb = 1024 * int(i_info['root_gb'])
    if image_mb > root_mb:
        msg = (_('Root partition is too small for requested image. '
                 'Image size: %(image_mb)d MB, Root size: %(root_mb)d MB')
               % {'image_mb': image_mb, 'root_mb': root_mb})
        raise exception.InstanceDeployFailure(msg)


def cache_instance_image(ctx, node):
    """Fetch the instance's image from Glance

    This method pulls the AMI and writes them to the appropriate place
    on local disk.

    :param ctx: context
    :param node: an ironic node object
    :returns: a tuple containing the uuid of the image and the path in
        the filesystem where image is cached.
    """
    i_info = parse_instance_info(node)
    fileutils.ensure_tree(_get_image_dir_path(node.uuid))
    image_path = _get_image_file_path(node.uuid)
    uuid = i_info['image_source']

    LOG.debug("Fetching image %(ami)s for node %(uuid)s",
              {'ami': uuid, 'uuid': node.uuid})

    deploy_utils.fetch_images(ctx, InstanceImageCache(), [(uuid, image_path)],
                              CONF.force_raw_images)

    return (uuid, image_path)


def destroy_images(node_uuid):
    """Delete instance's image file.

    :param node_uuid: the uuid of the ironic node.
    """
    utils.unlink_without_raise(_get_image_file_path(node_uuid))
    utils.rmtree_without_raise(_get_image_dir_path(node_uuid))
    InstanceImageCache().clean_up()


def get_deploy_info(node, **kwargs):
    """Returns the information required for doing iSCSI deploy in a dictionary.

    :param node: ironic node object
    :param kwargs: the keyword args passed from the conductor node.
    :raises: MissingParameterValue, if some required parameters were not
        passed.
    :raises: InvalidParameterValue, if any of the parameters have invalid
        value.
    """

    deploy_key = kwargs.get('key')
    i_info = parse_instance_info(node)
    if i_info['deploy_key'] != deploy_key:
        raise exception.InvalidParameterValue(_("Deploy key does not match"))

    params = {'address': kwargs.get('address'),
              'port': kwargs.get('port', '3260'),
              'iqn': kwargs.get('iqn'),
              'lun': kwargs.get('lun', '1'),
              'image_path': _get_image_file_path(node.uuid),
              'root_mb': 1024 * int(i_info['root_gb']),
              'swap_mb': int(i_info['swap_mb']),
              'ephemeral_mb': 1024 * int(i_info['ephemeral_gb']),
              'preserve_ephemeral': i_info['preserve_ephemeral'],
              'node_uuid': node.uuid,
             }

    missing = [key for key in params if params[key] is None]
    if missing:
        raise exception.MissingParameterValue(_(
                "Parameters %s were not passed to ironic"
                " for deploy.") % missing)

    # ephemeral_format is nullable
    params['ephemeral_format'] = i_info.get('ephemeral_format')

    return params


def set_failed_state(task, msg):
    """Sets the deploy status as failed with relevant messages.

    This method sets the deployment as fail with the given message.
    It sets node's provision_state to DEPLOYFAIL and updates last_error
    with the given error message. It also powers off the baremetal node.

    :param task: a TaskManager instance containing the node to act on.
    :param msg: the message to set in last_error of the node.
    """
    node = task.node
    node.provision_state = states.DEPLOYFAIL
    node.target_provision_state = states.NOSTATE
    node.save()
    try:
        manager_utils.node_power_action(task, states.POWER_OFF)
    except Exception:
        msg2 = (_('Node %s failed to power off while handling deploy '
                 'failure. This may be a serious condition. Node '
                 'should be removed from Ironic or put in maintenance '
                 'mode until the problem is resolved.') % node.uuid)
        LOG.exception(msg2)
    finally:
        # NOTE(deva): node_power_action() erases node.last_error
        #             so we need to set it again here.
        node.last_error = msg
        node.save()


def continue_deploy(task, **kwargs):
    """Resume a deployment upon getting POST data from deploy ramdisk.

    This method raises no exceptions because it is intended to be
    invoked asynchronously as a callback from the deploy ramdisk.

    :param task: a TaskManager instance containing the node to act on.
    :param kwargs: the kwargs to be passed to deploy.
    :returns: UUID of the root partition or None on error.
    """
    node = task.node

    node.provision_state = states.DEPLOYING
    node.save()

    params = get_deploy_info(node, **kwargs)
    ramdisk_error = kwargs.get('error')

    if ramdisk_error:
        LOG.error(_LE('Error returned from deploy ramdisk: %s'),
                  ramdisk_error)
        set_failed_state(task, _('Failure in deploy ramdisk.'))
        destroy_images(node.uuid)
        return

    LOG.info(_LI('Continuing deployment for node %(node)s, params %(params)s'),
                 {'node': node.uuid, 'params': params})

    root_uuid = None
    try:
        root_uuid = deploy_utils.deploy(**params)
    except Exception as e:
        LOG.error(_LE('Deploy failed for instance %(instance)s. '
                      'Error: %(error)s'),
                  {'instance': node.instance_uuid, 'error': e})
        set_failed_state(task, _('Failed to continue iSCSI deployment.'))

    destroy_images(node.uuid)
    return root_uuid


def build_deploy_ramdisk_options(node):
    """Build the ramdisk config options for a node

    This method builds the ramdisk options for a node,
    given all the required parameters for doing iscsi deploy.

    :param node: a single Node.
    :returns: A dictionary of options to be passed to ramdisk for performing
        the deploy.
    """
    # NOTE: we should strip '/' from the end because this is intended for
    # hardcoded ramdisk script
    ironic_api = (CONF.conductor.api_url or
                  keystone.get_service_url()).rstrip('/')

    deploy_key = utils.random_alnum(32)
    i_info = node.instance_info
    i_info['deploy_key'] = deploy_key
    node.instance_info = i_info
    node.save()

    deploy_options = {
        'deployment_id': node['uuid'],
        'deployment_key': deploy_key,
        'iscsi_target_iqn': "iqn-%s" % node.uuid,
        'ironic_api_url': ironic_api,
        'disk': CONF.pxe.disk_devices,
    }
    return deploy_options


def validate_glance_image_properties(ctx, deploy_info, properties):
    """Validate the image in Glance.

    Check if the image exist in Glance and if it contains the
    properties passed.

    :param ctx: security context
    :param deploy_info: the deploy_info to be validated
    :param properties: the list of image meta-properties to be validated.
    :raises: InvalidParameterValue if connection to glance failed or
        authorization for accessing image failed or if image doesn't exist.
    :raises: MissingParameterValue if the glance image doesn't contain
        the mentioned properties.
    """
    image_id = deploy_info['image_source']
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
    for prop in properties:
        if not image_props.get(prop):
            missing_props.append(prop)

    if missing_props:
        props = ', '.join(missing_props)
        raise exception.MissingParameterValue(_(
            "Image %(image)s is missing the following properties: "
            "%(properties)s") % {'image': image_id, 'properties': props})


def validate(task):
    """Validates the pre-requisites for iSCSI deploy.

    Validates whether node in the task provided has some ports enrolled.
    This method validates whether conductor url is available either from CONF
    file or from keystone.

    :param task: a TaskManager instance containing the node to act on.
    :raises: InvalidParameterValue if the URL of the Ironic API service is not
             configured in config file and is not accessible via Keystone
             catalog.
    :raises: MissingParameterValue if no ports are enrolled for the given node.
    """
    node = task.node
    if not driver_utils.get_node_mac_addresses(task):
        raise exception.MissingParameterValue(_("Node %s does not have "
                            "any port associated with it.") % node.uuid)

    try:
        # TODO(lucasagomes): Validate the format of the URL
        CONF.conductor.api_url or keystone.get_service_url()
    except (exception.KeystoneFailure,
            exception.CatalogNotFound,
            exception.KeystoneUnauthorized) as e:
        raise exception.InvalidParameterValue(_(
            "Couldn't get the URL of the Ironic API service from the "
            "configuration file or keystone catalog. Keystone error: %s") % e)
