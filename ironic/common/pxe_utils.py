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

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

PXE_CFG_DIR_NAME = 'pxelinux.cfg'


def _ensure_config_dirs_exist(node_uuid):
    """Ensure that the node's and PXE configuration directories exist.

    :param node_uuid: the UUID of the node.

    """
    tftp_root = CONF.pxe.tftp_root
    fileutils.ensure_tree(os.path.join(tftp_root, node_uuid))
    fileutils.ensure_tree(os.path.join(tftp_root, PXE_CFG_DIR_NAME))


def _build_pxe_config(pxe_options, template):
    """Build the PXE boot configuration file.

    This method builds the PXE boot configuration file by rendering the
    template with the given parameters.

    :param pxe_options: A dict of values to set on the configuration file.
    :param template: The PXE configuration template.
    :returns: A formatted string with the file content.

    """
    tmpl_path, tmpl_file = os.path.split(template)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path))
    template = env.get_template(tmpl_file)
    return template.render({'pxe_options': pxe_options,
                            'ROOT': '{{ ROOT }}'})


def _link_mac_pxe_configs(task):
    """Link each MAC address with the PXE configuration file.

    :param task: A TaskManager instance.

    """
    pxe_config_file_path = get_pxe_config_file_path(task.node.uuid)
    for mac in driver_utils.get_node_mac_addresses(task):
        mac_path = _get_pxe_mac_path(mac)
        utils.unlink_without_raise(mac_path)
        utils.create_link_without_raise(pxe_config_file_path, mac_path)


def _get_pxe_mac_path(mac):
    """Convert a MAC address into a PXE config file name.

    :param mac: A MAC address string in the format xx:xx:xx:xx:xx:xx.
    :returns: the path to the config file.

    """
    return os.path.join(
        CONF.pxe.tftp_root,
        PXE_CFG_DIR_NAME,
        "01-" + mac.replace(":", "-").lower()
    )


def get_deploy_kr_info(node_uuid, driver_info):
    """Get uuid and tftp path for deploy kernel and ramdisk.

    Note: driver_info should be validated outside of this method.
    """
    image_info = {}
    for label in ('deploy_kernel', 'deploy_ramdisk'):
        # the values for these keys will look like "glance://image-uuid"
        image_info[label] = (
            str(driver_info[label]).split('/')[-1],
            os.path.join(CONF.pxe.tftp_root, node_uuid, label)
        )
    return image_info


def get_pxe_config_file_path(node_uuid):
    """Generate the path for the node's PXE configuration file.

    :param node_uuid: the UUID of the node.
    :returns: The path to the node's PXE configuration file.

    """
    return os.path.join(CONF.pxe.tftp_root, node_uuid, 'config')


def create_pxe_config(task, pxe_options, template=None):
    """Generate PXE configuration file and MAC address links for it.

    This method will generate the PXE configuration file for the task's
    node under a directory named with the UUID of that node. For each
    MAC address (port) of that node, a symlink for the configuration file
    will be created under the PXE configuration directory, so regardless
    of which port boots first they'll get the same PXE configuration.

    :param task: A TaskManager instance.
    :param pxe_options: A dictionary with the PXE configuration
        parameters.
    :param template: The PXE configuration template. If no template is
        given the CONF.pxe.pxe_config_template will be used.

    """
    LOG.debug("Building PXE config for node %s", task.node.uuid)

    if template is None:
        template = CONF.pxe.pxe_config_template

    _ensure_config_dirs_exist(task.node.uuid)

    pxe_config_file_path = get_pxe_config_file_path(task.node.uuid)
    pxe_config = _build_pxe_config(pxe_options, template)
    utils.write_to_file(pxe_config_file_path, pxe_config)
    _link_mac_pxe_configs(task)


def clean_up_pxe_config(task):
    """Clean up the TFTP environment for the task's node.

    :param task: A TaskManager instance.

    """
    LOG.debug("Cleaning up PXE config for node %s", task.node.uuid)

    for mac in driver_utils.get_node_mac_addresses(task):
        utils.unlink_without_raise(_get_pxe_mac_path(mac))

    utils.rmtree_without_raise(os.path.join(CONF.pxe.tftp_root,
                                            task.node.uuid))


def dhcp_options_for_instance():
    """Retrieves the DHCP PXE boot options."""
    return [{'opt_name': 'bootfile-name',
             'opt_value': CONF.pxe.pxe_bootfile_name},
            {'opt_name': 'server-ip-address',
             'opt_value': CONF.pxe.tftp_server},
            {'opt_name': 'tftp-server',
             'opt_value': CONF.pxe.tftp_server}
            ]
