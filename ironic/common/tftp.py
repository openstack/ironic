#
# Copyright 2014 Rackspace, Inc
# All Rights Reserved
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

import jinja2
from oslo.config import cfg

from ironic.common import utils
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import fileutils
from ironic.openstack.common import log as logging


tftp_opts = [
    cfg.StrOpt('tftp_server',
               default='$my_ip',
               help='IP address of Ironic compute node\'s tftp server.',
               deprecated_group='pxe'),
    cfg.StrOpt('tftp_root',
               default='/tftpboot',
               help='Ironic compute node\'s tftp root path.',
               deprecated_group='pxe')
    ]

CONF = cfg.CONF
CONF.register_opts(tftp_opts, group='tftp')

LOG = logging.getLogger(__name__)


def get_deploy_kr_info(node_uuid, driver_info):
    """Get uuid and tftp path for deploy kernel and ramdisk.

    Note: driver_info should be validated outside of this method.
    """
    image_info = {}
    for label in ('deploy_kernel', 'deploy_ramdisk'):
        # the values for these keys will look like "glance://image-uuid"
        image_info[label] = (
            str(driver_info[label]).split('/')[-1],
            os.path.join(CONF.tftp.tftp_root, node_uuid, label)
        )
    return image_info


def create_pxe_config(task, pxe_options, pxe_config_template):
    """Generate PXE configuration file and MAC symlinks for it."""
    node = task.node
    fileutils.ensure_tree(os.path.join(CONF.tftp.tftp_root,
                                       node.uuid))
    fileutils.ensure_tree(os.path.join(CONF.tftp.tftp_root,
                                       'pxelinux.cfg'))

    pxe_config_file_path = get_pxe_config_file_path(node.uuid)
    pxe_config = build_pxe_config(node, pxe_options, pxe_config_template)
    utils.write_to_file(pxe_config_file_path, pxe_config)
    _write_mac_pxe_configs(task)


def clean_up_pxe_config(task):
    """Clean up the TFTP environment for the task's node."""
    node = task.node

    utils.unlink_without_raise(get_pxe_config_file_path(node.uuid))
    for port in driver_utils.get_node_mac_addresses(task):
        utils.unlink_without_raise(get_pxe_mac_path(port))

    utils.rmtree_without_raise(os.path.join(CONF.tftp.tftp_root, node.uuid))


def _write_mac_pxe_configs(task):
    """Create a file in the PXE config directory for each MAC so regardless
    of which port boots first, they'll get the same PXE config.
    """
    pxe_config_file_path = get_pxe_config_file_path(task.node.uuid)
    for port in driver_utils.get_node_mac_addresses(task):
        mac_path = get_pxe_mac_path(port)
        utils.unlink_without_raise(mac_path)
        utils.create_link_without_raise(pxe_config_file_path, mac_path)


def build_pxe_config(node, pxe_options, pxe_config_template):
    """Build the PXE config file for a node

    This method builds the PXE boot configuration file for a node,
    given all the required parameters.

    :param pxe_options: A dict of values to set on the configuration file
    :returns: A formatted string with the file content.
    """
    LOG.debug("Building PXE config for deployment %s."), node['id']

    tmpl_path, tmpl_file = os.path.split(pxe_config_template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    template = env.get_template(tmpl_file)
    return template.render({'pxe_options': pxe_options,
                            'ROOT': '{{ ROOT }}'})


def get_pxe_mac_path(mac):
    """Convert a MAC address into a PXE config file name.

    :param mac: A mac address string in the format xx:xx:xx:xx:xx:xx.
    :returns: the path to the config file.
    """
    return os.path.join(
        CONF.tftp.tftp_root,
        'pxelinux.cfg',
        "01-" + mac.replace(":", "-").lower()
    )


def get_pxe_config_file_path(node_uuid):
    """Generate the path for an instances PXE config file."""
    return os.path.join(CONF.tftp.tftp_root, node_uuid, 'config')


def dhcp_options_for_instance(pxe_bootfile_name):
    """Retrives the DHCP PXE boot options."""
    return [{'opt_name': 'bootfile-name',
             'opt_value': pxe_bootfile_name},
            {'opt_name': 'server-ip-address',
             'opt_value': CONF.tftp.tftp_server},
            {'opt_name': 'tftp-server',
             'opt_value': CONF.tftp.tftp_server}
            ]
