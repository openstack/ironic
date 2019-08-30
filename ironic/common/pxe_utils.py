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

from ironic_lib import utils as ironic_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

PXE_CFG_DIR_NAME = CONF.pxe.pxe_config_subdir

DHCP_CLIENT_ID = '61'  # rfc2132
DHCP_TFTP_SERVER_NAME = '66'  # rfc2132
DHCP_BOOTFILE_NAME = '67'  # rfc2132
DHCP_TFTP_SERVER_ADDRESS = '150'  # rfc5859
DHCP_IPXE_ENCAP_OPTS = '175'  # Tentatively Assigned
DHCP_TFTP_PATH_PREFIX = '210'  # rfc5071
DEPLOY_KERNEL_RAMDISK_LABELS = ['deploy_kernel', 'deploy_ramdisk']
RESCUE_KERNEL_RAMDISK_LABELS = ['rescue_kernel', 'rescue_ramdisk']
KERNEL_RAMDISK_LABELS = {'deploy': DEPLOY_KERNEL_RAMDISK_LABELS,
                         'rescue': RESCUE_KERNEL_RAMDISK_LABELS}


def get_root_dir():
    """Returns the directory where the config files and images will live."""
    if CONF.pxe.ipxe_enabled:
        return CONF.deploy.http_root
    else:
        return CONF.pxe.tftp_root


def _ensure_config_dirs_exist(node_uuid):
    """Ensure that the node's and PXE configuration directories exist.

    :param node_uuid: the UUID of the node.

    """
    root_dir = get_root_dir()
    node_dir = os.path.join(root_dir, node_uuid)
    pxe_dir = os.path.join(root_dir, PXE_CFG_DIR_NAME)
    # NOTE: We should only change the permissions if the folder
    # does not exist. i.e. if defined, an operator could have
    # already created it and placed specific ACLs upon the folder
    # which may not recurse downward.
    for directory in (node_dir, pxe_dir):
        if not os.path.isdir(directory):
            fileutils.ensure_tree(directory)
            if CONF.pxe.dir_permission:
                os.chmod(directory, CONF.pxe.dir_permission)


def _link_mac_pxe_configs(task):
    """Link each MAC address with the PXE configuration file.

    :param task: A TaskManager instance.

    """

    def create_link(mac_path):
        ironic_utils.unlink_without_raise(mac_path)
        relative_source_path = os.path.relpath(
            pxe_config_file_path, os.path.dirname(mac_path))
        utils.create_link_without_raise(relative_source_path, mac_path)

    pxe_config_file_path = get_pxe_config_file_path(task.node.uuid)
    for port in task.ports:
        client_id = port.extra.get('client-id')
        # Syslinux, ipxe, depending on settings.
        create_link(_get_pxe_mac_path(port.address, client_id=client_id))
        # Grub2 MAC address only
        create_link(_get_pxe_grub_mac_path(port.address))


def _link_ip_address_pxe_configs(task, hex_form):
    """Link each IP address with the PXE configuration file.

    :param task: A TaskManager instance.
    :param hex_form: Boolean value indicating if the conf file name should be
                     hexadecimal equivalent of supplied ipv4 address.
    :raises: FailedToGetIPAddressOnPort
    :raises: InvalidIPv4Address

    """
    pxe_config_file_path = get_pxe_config_file_path(task.node.uuid)

    api = dhcp_factory.DHCPFactory().provider
    ip_addrs = api.get_ip_addresses(task)
    if not ip_addrs:
        raise exception.FailedToGetIPAddressOnPort(_(
            "Failed to get IP address for any port on node %s.") %
            task.node.uuid)
    for port_ip_address in ip_addrs:
        ip_address_path = _get_pxe_ip_address_path(port_ip_address,
                                                   hex_form)
        ironic_utils.unlink_without_raise(ip_address_path)
        relative_source_path = os.path.relpath(
            pxe_config_file_path, os.path.dirname(ip_address_path))
        utils.create_link_without_raise(relative_source_path,
                                        ip_address_path)


def _get_pxe_grub_mac_path(mac):
    return os.path.join(get_root_dir(), mac + '.conf')


def _get_pxe_mac_path(mac, delimiter='-', client_id=None):
    """Convert a MAC address into a PXE config file name.

    :param mac: A MAC address string in the format xx:xx:xx:xx:xx:xx.
    :param delimiter: The MAC address delimiter. Defaults to dash ('-').
    :param client_id: client_id indicate InfiniBand port.
                      Defaults is None (Ethernet)
    :returns: the path to the config file.

    """
    mac_file_name = mac.replace(':', delimiter).lower()
    if not CONF.pxe.ipxe_enabled:
        hw_type = '01-'
        if client_id:
            hw_type = '20-'
        mac_file_name = hw_type + mac_file_name
    return os.path.join(get_root_dir(), PXE_CFG_DIR_NAME, mac_file_name)


def _get_pxe_ip_address_path(ip_address, hex_form):
    """Convert an ipv4 address into a PXE config file name.

    :param ip_address: A valid IPv4 address string in the format 'n.n.n.n'.
    :param hex_form: Boolean value indicating if the conf file name should be
                     hexadecimal equivalent of supplied ipv4 address.
    :returns: the path to the config file.

    """
    # NOTE(TheJulia): Remove elilo support after the deprecation
    # period, in the Queens release.
    # elilo bootloader needs hex based config file name.
    if hex_form:
        ip = ip_address.split('.')
        ip_address = '{0:02X}{1:02X}{2:02X}{3:02X}'.format(*map(int, ip))

    # grub2 bootloader needs ip based config file name.
    return os.path.join(
        CONF.pxe.tftp_root, ip_address + ".conf"
    )


def get_kernel_ramdisk_info(node_uuid, driver_info, mode='deploy'):
    """Get href and tftp path for deploy or rescue kernel and ramdisk.

    :param node_uuid: UUID of the node
    :param driver_info: Node's driver_info dict
    :param mode: A label to indicate whether paths for deploy or rescue
                 ramdisk are being requested. Supported values are 'deploy'
                 'rescue'. Defaults to 'deploy', indicating deploy paths will
                 be returned.
    :returns: a dictionary whose keys are deploy_kernel and deploy_ramdisk or
              rescue_kernel and rescue_ramdisk and whose values are the
              absolute paths to them.

    Note: driver_info should be validated outside of this method.
    """
    root_dir = get_root_dir()
    image_info = {}
    labels = KERNEL_RAMDISK_LABELS[mode]
    for label in labels:
        image_info[label] = (
            str(driver_info[label]),
            os.path.join(root_dir, node_uuid, label)
        )
    return image_info


def get_pxe_config_file_path(node_uuid):
    """Generate the path for the node's PXE configuration file.

    :param node_uuid: the UUID of the node.
    :returns: The path to the node's PXE configuration file.

    """
    return os.path.join(get_root_dir(), node_uuid, 'config')


def create_pxe_config(task, pxe_options, template=None):
    """Generate PXE configuration file and MAC address links for it.

    This method will generate the PXE configuration file for the task's
    node under a directory named with the UUID of that node. For each
    MAC address or DHCP IP address (port) of that node, a symlink for
    the configuration file will be created under the PXE configuration
    directory, so regardless of which port boots first they'll get the
    same PXE configuration.
    If elilo is the bootloader in use, then its configuration file will
    be created based on hex form of DHCP IP address.
    If grub2 bootloader is in use, then its configuration will be created
    based on DHCP IP address in the form nn.nn.nn.nn.

    :param task: A TaskManager instance.
    :param pxe_options: A dictionary with the PXE configuration
        parameters.
    :param template: The PXE configuration template. If no template is
        given the node specific template will be used.

    """
    LOG.debug("Building PXE config for node %s", task.node.uuid)

    if template is None:
        template = deploy_utils.get_pxe_config_template(task.node)

    _ensure_config_dirs_exist(task.node.uuid)

    pxe_config_file_path = get_pxe_config_file_path(task.node.uuid)
    is_uefi_boot_mode = (boot_mode_utils.get_boot_mode_for_deploy(task.node)
                         == 'uefi')

    # grub bootloader panics with '{}' around any of its tags in its
    # config file. To overcome that 'ROOT' and 'DISK_IDENTIFIER' are enclosed
    # with '(' and ')' in uefi boot mode.
    # These changes do not have any impact on elilo bootloader.
    hex_form = True
    if is_uefi_boot_mode and utils.is_regex_string_in_file(template,
                                                           '^menuentry'):
        hex_form = False
        pxe_config_root_tag = '(( ROOT ))'
        pxe_config_disk_ident = '(( DISK_IDENTIFIER ))'
        LOG.warning("The requested config appears to support elilo. "
                    "Support for elilo has been deprecated and will be "
                    "removed in the Queens release of OpenStack.")
    else:
        # TODO(stendulker): We should use '(' ')' as the delimiters for all our
        # config files so that we do not need special handling for each of the
        # bootloaders. Should be removed once the Mitaka release starts.
        pxe_config_root_tag = '{{ ROOT }}'
        pxe_config_disk_ident = '{{ DISK_IDENTIFIER }}'

    params = {'pxe_options': pxe_options,
              'ROOT': pxe_config_root_tag,
              'DISK_IDENTIFIER': pxe_config_disk_ident}

    pxe_config = utils.render_template(template, params)
    utils.write_to_file(pxe_config_file_path, pxe_config)

    if is_uefi_boot_mode and not CONF.pxe.ipxe_enabled:
        # Always write the mac addresses
        _link_mac_pxe_configs(task)
        try:
            _link_ip_address_pxe_configs(task, hex_form)
        # NOTE(TheJulia): The IP address support will fail if the
        # dhcp_provider interface is set to none. This will result
        # in the MAC addresses and DHCP files being written, and
        # we can remove IP address creation for the grub use
        # case, considering that will ease removal of elilo support.
        except exception.FailedToGetIPAddressOnPort as e:
            if CONF.dhcp.dhcp_provider != 'none':
                with excutils.save_and_reraise_exception():
                    LOG.error('Unable to create boot config, IP address '
                              'was unable to be retrieved. %(error)s',
                              {'error': e})
    else:
        _link_mac_pxe_configs(task)


def create_ipxe_boot_script():
    """Render the iPXE boot script into the HTTP root directory"""
    boot_script = utils.render_template(
        CONF.pxe.ipxe_boot_script,
        {'ipxe_for_mac_uri': PXE_CFG_DIR_NAME + '/'})
    bootfile_path = os.path.join(
        CONF.deploy.http_root,
        os.path.basename(CONF.pxe.ipxe_boot_script))
    # NOTE(pas-ha) to prevent unneeded writes,
    # only write to file if its content is different from required,
    # which should be rather rare
    if (not os.path.isfile(bootfile_path)
            or not utils.file_has_content(bootfile_path, boot_script)):
        utils.write_to_file(bootfile_path, boot_script)


def clean_up_pxe_config(task):
    """Clean up the TFTP environment for the task's node.

    :param task: A TaskManager instance.

    """
    LOG.debug("Cleaning up PXE config for node %s", task.node.uuid)

    is_uefi_boot_mode = (boot_mode_utils.get_boot_mode_for_deploy(task.node)
                         == 'uefi')
    if is_uefi_boot_mode and not CONF.pxe.ipxe_enabled:
        api = dhcp_factory.DHCPFactory().provider
        ip_addresses = api.get_ip_addresses(task)
        if not ip_addresses:
            return

        for port_ip_address in ip_addresses:
            try:
                # Get xx.xx.xx.xx based grub config file
                ip_address_path = _get_pxe_ip_address_path(port_ip_address,
                                                           False)
                # NOTE(TheJulia): Remove elilo support after the deprecation
                # period, in the Queens release.
                # Get 0AOAOAOA based elilo config file
                hex_ip_path = _get_pxe_ip_address_path(port_ip_address,
                                                       True)
            except exception.InvalidIPv4Address:
                continue
            except exception.FailedToGetIPAddressOnPort:
                continue
            # Cleaning up config files created for grub2.
            ironic_utils.unlink_without_raise(ip_address_path)
            # Cleaning up config files created for elilo.
            ironic_utils.unlink_without_raise(hex_ip_path)

    for port in task.ports:
        client_id = port.extra.get('client-id')
        # syslinux, ipxe, etc.
        ironic_utils.unlink_without_raise(
            _get_pxe_mac_path(port.address, client_id=client_id))
        # Grub2 MAC address based confiuration
        ironic_utils.unlink_without_raise(
            _get_pxe_grub_mac_path(port.address))
    utils.rmtree_without_raise(os.path.join(get_root_dir(),
                                            task.node.uuid))


def dhcp_options_for_instance(task):
    """Retrieves the DHCP PXE boot options.

    :param task: A TaskManager instance.
    """
    dhcp_opts = []

    boot_file = deploy_utils.get_pxe_boot_file(task.node)

    if CONF.pxe.ipxe_enabled:
        script_name = os.path.basename(CONF.pxe.ipxe_boot_script)
        ipxe_script_url = '/'.join([CONF.deploy.http_url, script_name])
        dhcp_provider_name = CONF.dhcp.dhcp_provider
        # if the request comes from dumb firmware send them the iPXE
        # boot image.
        if dhcp_provider_name == 'neutron':
            # Neutron use dnsmasq as default DHCP agent, add extra config
            # to neutron "dhcp-match=set:ipxe,175" and use below option
            dhcp_opts.append({'opt_name': "tag:!ipxe,%s" % DHCP_BOOTFILE_NAME,
                              'opt_value': boot_file})
            dhcp_opts.append({'opt_name': "tag:ipxe,%s" % DHCP_BOOTFILE_NAME,
                              'opt_value': ipxe_script_url})
        else:
            # !175 == non-iPXE.
            # http://ipxe.org/howto/dhcpd#ipxe-specific_options
            dhcp_opts.append({'opt_name': "!%s,%s" % (DHCP_IPXE_ENCAP_OPTS,
                              DHCP_BOOTFILE_NAME),
                              'opt_value': boot_file})
            dhcp_opts.append({'opt_name': DHCP_BOOTFILE_NAME,
                              'opt_value': ipxe_script_url})
    else:
        dhcp_opts.append({'opt_name': DHCP_BOOTFILE_NAME,
                          'opt_value': boot_file})
        # 210 == tftp server path-prefix or tftp root, will be used to find
        # pxelinux.cfg directory. The pxelinux.0 loader infers this information
        # from it's own path, but Petitboot needs it to be specified by this
        # option since it doesn't use pxelinux.0 loader.
        dhcp_opts.append({'opt_name': DHCP_TFTP_PATH_PREFIX,
                          'opt_value': get_tftp_path_prefix()})

    dhcp_opts.append({'opt_name': DHCP_TFTP_SERVER_NAME,
                      'opt_value': CONF.pxe.tftp_server})
    dhcp_opts.append({'opt_name': DHCP_TFTP_SERVER_ADDRESS,
                      'opt_value': CONF.pxe.tftp_server})

    # NOTE(vsaienko) set this option specially for dnsmasq case as it always
    # sets `siaddr` field which is treated by pxe clients as TFTP server
    # see page 9 https://tools.ietf.org/html/rfc2131.
    # If `server-ip-address` is not provided dnsmasq sets `siaddr` to dnsmasq's
    # IP which breaks PXE booting as TFTP server is configured on ironic
    # conductor host.
    # http://thekelleys.org.uk/gitweb/?p=dnsmasq.git;a=blob;f=src/dhcp-common.c;h=eae9ae3567fe16eb979a484976c270396322efea;hb=a3303e196e5d304ec955c4d63afb923ade66c6e8#l572 # noqa
    # There is an informational RFC which describes how options related to
    # tftp 150,66 and siaddr should be used https://tools.ietf.org/html/rfc5859
    # All dhcp servers we've tried: contrail/dnsmasq/isc just silently ignore
    # unknown options but potentially it may blow up with others.
    # Related bug was opened on Neutron side:
    # https://bugs.launchpad.net/neutron/+bug/1723354
    dhcp_opts.append({'opt_name': 'server-ip-address',
                      'opt_value': CONF.pxe.tftp_server})

    # Append the IP version for all the configuration options
    for opt in dhcp_opts:
        opt.update({'ip_version': int(CONF.pxe.ip_version)})

    return dhcp_opts


def get_tftp_path_prefix():
    """Adds trailing slash (if needed) necessary for path-prefix

    :return: CONF.pxe.tftp_root ensured to have a trailing slash
    """
    return os.path.join(CONF.pxe.tftp_root, '')


def get_path_relative_to_tftp_root(file_path):
    """Return file relative path to CONF.pxe.tftp_root

    :param file_path: full file path to be made relative path.
    :returns: The path relative to CONF.pxe.tftp_root
    """
    return os.path.relpath(file_path, get_tftp_path_prefix())
