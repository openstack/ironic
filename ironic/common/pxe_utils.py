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

import copy
import os
import shutil
import tempfile

from ironic_lib import utils as ironic_utils
import jinja2
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common.i18n import _
from ironic.common import image_service as service
from ironic.common import images
from ironic.common import kickstart_utils as ks_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers import utils as driver_utils
from ironic import objects

LOG = logging.getLogger(__name__)

PXE_CFG_DIR_NAME = CONF.pxe.pxe_config_subdir

DHCP_CLIENT_ID = '61'  # rfc2132
DHCP_TFTP_SERVER_NAME = '66'  # rfc2132
DHCP_BOOTFILE_NAME = '67'  # rfc2132
DHCPV6_BOOTFILE_NAME = '59'  # rfc5970
# NOTE(TheJulia): adding note for the bootfile parameter
# field as defined by RFC 5870. No practical examples seem
# available. Neither grub2 or ipxe seem to leverage this.
# DHCPV6_BOOTFILE_PARAMS = '60'  # rfc5970
DHCP_TFTP_SERVER_ADDRESS = '150'  # rfc5859
DHCP_IPXE_ENCAP_OPTS = '175'  # Tentatively Assigned
DHCP_TFTP_PATH_PREFIX = '210'  # rfc5071

DEPLOY_KERNEL_RAMDISK_LABELS = ['deploy_kernel', 'deploy_ramdisk']
RESCUE_KERNEL_RAMDISK_LABELS = ['rescue_kernel', 'rescue_ramdisk']
KERNEL_RAMDISK_LABELS = {'deploy': DEPLOY_KERNEL_RAMDISK_LABELS,
                         'rescue': RESCUE_KERNEL_RAMDISK_LABELS}


def _get_root_dir(ipxe_enabled):
    if ipxe_enabled:
        return CONF.deploy.http_root
    else:
        return CONF.pxe.tftp_root


def ensure_tree(path):
    mode = CONF.pxe.dir_permission or 0o755
    os.makedirs(path, mode=mode, exist_ok=True)


def _ensure_config_dirs_exist(task, ipxe_enabled=False):
    """Ensure that the node's and PXE configuration directories exist.

    :param task: A TaskManager instance
    :param ipxe_enabled: Default false boolean to indicate if ipxe
                         is in use by the caller.
    """
    root_dir = _get_root_dir(ipxe_enabled)
    node_dir = os.path.join(root_dir, task.node.uuid)
    pxe_dir = os.path.join(root_dir, PXE_CFG_DIR_NAME)
    # NOTE: We should only change the permissions if the folder
    # does not exist. i.e. if defined, an operator could have
    # already created it and placed specific ACLs upon the folder
    # which may not recurse downward.
    for directory in (node_dir, pxe_dir):
        if not os.path.isdir(directory):
            ensure_tree(directory)


def _link_mac_pxe_configs(task, ipxe_enabled=False):
    """Link each MAC address with the PXE configuration file.

    :param task: A TaskManager instance.
    :param ipxe_enabled: Default false boolean to indicate if ipxe
                         is in use by the caller.
    """

    def create_link(mac_path):
        ironic_utils.unlink_without_raise(mac_path)
        relative_source_path = os.path.relpath(
            pxe_config_file_path, os.path.dirname(mac_path))
        utils.create_link_without_raise(relative_source_path, mac_path)

    pxe_config_file_path = get_pxe_config_file_path(
        task.node.uuid, ipxe_enabled=ipxe_enabled)
    for port in task.ports:
        client_id = port.extra.get('client-id')
        # Syslinux, ipxe, depending on settings.
        create_link(_get_pxe_mac_path(port.address, client_id=client_id,
                                      ipxe_enabled=ipxe_enabled))
        # Grub2 MAC address only
        for path in _get_pxe_grub_mac_path(port.address,
                                           ipxe_enabled=ipxe_enabled):
            create_link(path)


def _link_ip_address_pxe_configs(task, ipxe_enabled=False):
    """Link each IP address with the PXE configuration file.

    :param task: A TaskManager instance.
    :param ipxe_enabled: Default false boolean to indicate if ipxe
                         is in use by the caller.
    :raises: FailedToGetIPAddressOnPort
    :raises: InvalidIPv4Address

    """
    pxe_config_file_path = get_pxe_config_file_path(
        task.node.uuid,
        ipxe_enabled=ipxe_enabled)

    api = dhcp_factory.DHCPFactory().provider
    ip_addrs = api.get_ip_addresses(task)
    if not ip_addrs:

        if ip_addrs == []:
            LOG.warning("No IP addresses assigned for node %(node)s.",
                        {'node': task.node.uuid})
        else:
            LOG.warning(
                "DHCP address management is not available for node "
                "%(node)s. Operators without Neutron can ignore this "
                "warning.",
                {'node': task.node.uuid})
        # Just in case, reset to empty list if we got nothing.
        ip_addrs = []
    for port_ip_address in ip_addrs:
        ip_address_path = _get_pxe_ip_address_path(port_ip_address)
        ironic_utils.unlink_without_raise(ip_address_path)
        relative_source_path = os.path.relpath(
            pxe_config_file_path, os.path.dirname(ip_address_path))
        utils.create_link_without_raise(relative_source_path,
                                        ip_address_path)


def _get_pxe_grub_mac_path(mac, ipxe_enabled=False):
    root_dir = _get_root_dir(ipxe_enabled)
    yield os.path.join(root_dir, "%s-%s-%s" %
                       ("grub.cfg", "01", mac.replace(':', "-").lower()))
    yield os.path.join(root_dir, mac + '.conf')


def _get_pxe_mac_path(mac, delimiter='-', client_id=None,
                      ipxe_enabled=False):
    """Convert a MAC address into a PXE config file name.

    :param mac: A MAC address string in the format xx:xx:xx:xx:xx:xx.
    :param delimiter: The MAC address delimiter. Defaults to dash ('-').
    :param client_id: client_id indicate InfiniBand port.
                      Defaults is None (Ethernet)
    :param ipxe_enabled: A default False boolean value to tell the method
                         if the caller is using iPXE.
    :returns: the path to the config file.

    """
    mac_file_name = mac.replace(':', delimiter).lower()
    if not ipxe_enabled:
        hw_type = '01-'
        if client_id:
            hw_type = '20-'
        mac_file_name = hw_type + mac_file_name
        return os.path.join(CONF.pxe.tftp_root, PXE_CFG_DIR_NAME,
                            mac_file_name)
    return os.path.join(CONF.deploy.http_root, PXE_CFG_DIR_NAME,
                        mac_file_name)


def _get_pxe_ip_address_path(ip_address):
    """Convert an ipv4 address into a PXE config file name.

    :param ip_address: A valid IPv4 address string in the format 'n.n.n.n'.
    :returns: the path to the config file.

    """
    # grub2 bootloader needs ip based config file name.
    return os.path.join(
        CONF.pxe.tftp_root, ip_address + ".conf"
    )


def get_kernel_ramdisk_info(node_uuid, driver_info, mode='deploy',
                            ipxe_enabled=False):
    """Get href and tftp path for deploy or rescue kernel and ramdisk.

    :param node_uuid: UUID of the node
    :param driver_info: Node's driver_info dict
    :param mode: A label to indicate whether paths for deploy or rescue
                 ramdisk are being requested. Supported values are 'deploy'
                 'rescue'. Defaults to 'deploy', indicating deploy paths will
                 be returned.
    :param ipxe_enabled: A default False boolean value to tell the method
                         if the caller is using iPXE.
    :returns: a dictionary whose keys are deploy_kernel and deploy_ramdisk or
              rescue_kernel and rescue_ramdisk and whose values are the
              absolute paths to them.

    Note: driver_info should be validated outside of this method.
    """
    root_dir = _get_root_dir(ipxe_enabled)
    image_info = {}
    labels = KERNEL_RAMDISK_LABELS[mode]
    for label in labels:
        image_info[label] = (
            str(driver_info[label]),
            os.path.join(root_dir, node_uuid, label)
        )
    return image_info


def get_pxe_config_file_path(node_uuid, ipxe_enabled=False):
    """Generate the path for the node's PXE configuration file.

    :param node_uuid: the UUID of the node.
    :param ipxe_enabled: A default False boolean value to tell the method
                         if the caller is using iPXE.
    :returns: The path to the node's PXE configuration file.

    """
    return os.path.join(_get_root_dir(ipxe_enabled), node_uuid, 'config')


def get_file_path_from_label(node_uuid, root_dir, label):
    """Generate absolute paths to various images from their name(label)

    This method generates absolute file system path on the conductor where
    various images need to be placed. For example the kickstart template, file
    and stage2 squashfs.img needs to be placed in the ipxe_root_dir since they
    will be transferred by anaconda ramdisk over http(s). The generated paths
    will be added to the image_info dictionary as values.

    :param node_uuid: the UUID of the node
    :param root_dir: Directory in which the image must be placed
    :param label: Name of the image
    """
    if label == 'ks_template':
        return os.path.join(CONF.deploy.http_root, node_uuid,
                            'ks.cfg.template')
    elif label == 'ks_cfg':
        return os.path.join(CONF.deploy.http_root, node_uuid, 'ks.cfg')
    elif label == 'stage2':
        return os.path.join(CONF.deploy.http_root, node_uuid, 'LiveOS',
                            'squashfs.img')
    else:
        return os.path.join(root_dir, node_uuid, label)


def get_http_url_path_from_label(http_url, node_uuid, label):
    """Generate http url path to various image artifacts

    This method generates http(s) urls for various image artifacts int the
    webserver root. The generated urls will be added to the pxe_options dict
    and used to render pxe/ipxe configuration templates.

    :param http_url: URL to access the root of the webserver
    :param node_uuid: the UUID of the node
    :param label: Name of the image
    """
    if label == 'ks_template':
        return '/'.join([http_url, node_uuid, 'ks.cfg.template'])
    elif label == 'ks_cfg':
        return '/'.join([http_url, node_uuid, 'ks.cfg'])
    elif label == 'stage2':
        # we store stage2 in http_root/node_uuid/LiveOS/squashfs.img
        # Specifying http://host/node_uuid as stage2 url will make anaconda
        # automatically load the squashfs.img from LiveOS directory.
        return '/'.join([http_url, node_uuid])
    else:
        return '/'.join([http_url, node_uuid, label])


def create_pxe_config(task, pxe_options, template=None, ipxe_enabled=False):
    """Generate PXE configuration file and MAC address links for it.

    This method will generate the PXE configuration file for the task's
    node under a directory named with the UUID of that node. For each
    MAC address or DHCP IP address (port) of that node, a symlink for
    the configuration file will be created under the PXE configuration
    directory, so regardless of which port boots first they'll get the
    same PXE configuration.
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
        if ipxe_enabled:
            template = deploy_utils.get_ipxe_config_template(task.node)
        else:
            template = deploy_utils.get_pxe_config_template(task.node)

    _ensure_config_dirs_exist(task, ipxe_enabled)

    pxe_config_file_path = get_pxe_config_file_path(
        task.node.uuid,
        ipxe_enabled=ipxe_enabled)
    is_uefi_boot_mode = (boot_mode_utils.get_boot_mode(task.node)
                         == 'uefi')
    uefi_with_grub = is_uefi_boot_mode and not ipxe_enabled

    # grub bootloader panics with '{}' around any of its tags in its
    # config file. To overcome that 'ROOT' and 'DISK_IDENTIFIER' are enclosed
    # with '(' and ')' in uefi boot mode.
    if uefi_with_grub:
        pxe_config_root_tag = '(( ROOT ))'
        pxe_config_disk_ident = '(( DISK_IDENTIFIER ))'
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

    # Always write the mac addresses
    _link_mac_pxe_configs(task, ipxe_enabled=ipxe_enabled)
    if uefi_with_grub:
        try:
            _link_ip_address_pxe_configs(task, ipxe_enabled)
        # NOTE(TheJulia): The IP address support will fail if the
        # dhcp_provider interface is set to none. This will result
        # in the MAC addresses and DHCP files being written, and
        # we can remove IP address creation for the grub use.
        except exception.FailedToGetIPAddressOnPort as e:
            if CONF.dhcp.dhcp_provider != 'none':
                with excutils.save_and_reraise_exception():
                    LOG.error('Unable to create boot config, IP address '
                              'was unable to be retrieved. %(error)s',
                              {'error': e})


def create_ipxe_boot_script():
    """Render the iPXE boot script into the HTTP root directory"""
    boot_script = utils.render_template(
        CONF.pxe.ipxe_boot_script,
        {'ipxe_for_mac_uri': PXE_CFG_DIR_NAME + '/',
         'ipxe_fallback_script': CONF.pxe.ipxe_fallback_script})
    bootfile_path = os.path.join(
        CONF.deploy.http_root,
        os.path.basename(CONF.pxe.ipxe_boot_script))
    # NOTE(pas-ha) to prevent unneeded writes,
    # only write to file if its content is different from required,
    # which should be rather rare
    if (not os.path.isfile(bootfile_path)
            or not utils.file_has_content(bootfile_path, boot_script)):
        utils.write_to_file(bootfile_path, boot_script)


def clean_up_pxe_config(task, ipxe_enabled=False):
    """Clean up the TFTP environment for the task's node.

    :param task: A TaskManager instance.

    """
    LOG.debug("Cleaning up PXE config for node %s", task.node.uuid)

    is_uefi_boot_mode = (boot_mode_utils.get_boot_mode(task.node) == 'uefi')

    if is_uefi_boot_mode and not ipxe_enabled:
        api = dhcp_factory.DHCPFactory().provider
        ip_addresses = api.get_ip_addresses(task)

        for port_ip_address in ip_addresses:
            try:
                # Get xx.xx.xx.xx based grub config file
                ip_address_path = _get_pxe_ip_address_path(port_ip_address)
            except exception.InvalidIPv4Address:
                continue
            except exception.FailedToGetIPAddressOnPort:
                continue
            # Cleaning up config files created for grub2.
            ironic_utils.unlink_without_raise(ip_address_path)

    for port in task.ports:
        client_id = port.extra.get('client-id')
        # syslinux, ipxe, etc.
        ironic_utils.unlink_without_raise(
            _get_pxe_mac_path(port.address, client_id=client_id,
                              ipxe_enabled=ipxe_enabled))
        # Grub2 MAC address based confiuration
        for path in _get_pxe_grub_mac_path(port.address,
                                           ipxe_enabled=ipxe_enabled):
            ironic_utils.unlink_without_raise(path)
    utils.rmtree_without_raise(os.path.join(_get_root_dir(ipxe_enabled),
                                            task.node.uuid))


def _dhcp_option_file_or_url(task, urlboot=False, ip_version=None):
    """Returns the appropriate file or URL.

    :param task: A TaskManager object.
    :param url_boot: Boolean value default False to indicate if a
                     URL should be returned to the file as opposed
                     to a file.
    :param ip_version: Integer representing the version of IP of
                       to return options for DHCP. Possible options
                       are 4, and 6.
    """
    try:
        if task.driver.boot.ipxe_enabled:
            boot_file = deploy_utils.get_ipxe_boot_file(task.node)
        else:
            boot_file = deploy_utils.get_pxe_boot_file(task.node)
    except AttributeError:
        # Support boot interfaces that lack an explicit ipxe_enabled
        # attribute flag.
        boot_file = deploy_utils.get_pxe_boot_file(task.node)

    # NOTE(TheJulia): There are additional cases as we add new
    # features, so the logic below is in the form of if/elif/elif
    if not urlboot:
        return boot_file
    elif urlboot:
        if CONF.my_ipv6 and ip_version == 6:
            host = utils.wrap_ipv6(CONF.my_ipv6)
        else:
            host = utils.wrap_ipv6(CONF.pxe.tftp_server)
        return "tftp://{host}/{boot_file}".format(host=host,
                                                  boot_file=boot_file)


def dhcp_options_for_instance(task, ipxe_enabled=False, url_boot=False,
                              ip_version=None):
    """Retrieves the DHCP PXE boot options.

    :param task: A TaskManager instance.
    :param ipxe_enabled: Default false boolean that signals if iPXE
                         formatting should be returned by the method
                         for DHCP server configuration.
    :param url_boot: Default false boolean to inform the method if
                     a URL should be returned to boot the node.
                     If [pxe]ip_version is set to `6`, then this option
                     has no effect as url_boot form is required by DHCPv6
                     standards.
    :param ip_version: The IP version of options to return as values
                       differ by IP version. Default to [pxe]ip_version.
                       Possible options are integers 4 or 6.
    :returns: Dictionary to be sent to the networking service describing
              the DHCP options to be set.
    """
    if ip_version:
        use_ip_version = ip_version
    else:
        use_ip_version = int(CONF.pxe.ip_version)
    dhcp_opts = []
    dhcp_provider_name = CONF.dhcp.dhcp_provider
    if use_ip_version == 4:
        boot_file_param = DHCP_BOOTFILE_NAME
    else:
        # NOTE(TheJulia): Booting with v6 means it is always
        # a URL reply.
        boot_file_param = DHCPV6_BOOTFILE_NAME
        url_boot = True
    # NOTE(TheJulia): The ip_version value config from the PXE config is
    # guarded in the configuration, so there is no real sense in having
    # anything else here in the event the value is something aside from
    # 4 or 6, as there are no other possible values.
    boot_file = _dhcp_option_file_or_url(task, url_boot, use_ip_version)

    if ipxe_enabled:
        # TODO(TheJulia): DHCPv6 through dnsmasq + ipxe matching simply
        # does not work as the dhcp client is tracked via a different
        # identity mechanism in the exchange. This means if we really
        # want ipv6 + ipxe, we should be prepared to build a custom
        # iso with ipxe inside. Likely this is more secure and better
        # aligns with some of the mega-scale ironic operators.
        script_name = os.path.basename(CONF.pxe.ipxe_boot_script)
        # TODO(TheJulia): We should make this smarter to handle unwrapped v6
        # addresses, since the format is http://[ff80::1]:80/boot.ipxe.
        # As opposed to requiring configuration, we can eventually make this
        # dynamic, and would need to do similar then.
        ipxe_script_url = '/'.join([CONF.deploy.http_url, script_name])
        # if the request comes from dumb firmware send them the iPXE
        # boot image.
        if dhcp_provider_name == 'neutron':
            # Neutron use dnsmasq as default DHCP agent. Neutron carries the
            # configuration to relate to the tags below. The ipxe6 tag was
            # added in the Stein cycle which identifies the iPXE User-Class
            # directly and is only sent in DHCPv6.

            if use_ip_version != 6:
                dhcp_opts.append(
                    {'opt_name': "tag:!ipxe,%s" % boot_file_param,
                     'opt_value': boot_file}
                )
                dhcp_opts.append(
                    {'opt_name': "tag:ipxe,%s" % boot_file_param,
                     'opt_value': ipxe_script_url}
                )
            else:
                dhcp_opts.append(
                    {'opt_name': "tag:!ipxe6,%s" % boot_file_param,
                     'opt_value': boot_file})
                dhcp_opts.append(
                    {'opt_name': "tag:ipxe6,%s" % boot_file_param,
                     'opt_value': ipxe_script_url})
        else:
            # !175 == non-iPXE.
            # http://ipxe.org/howto/dhcpd#ipxe-specific_options
            if use_ip_version == 6:
                LOG.warning('IPv6 is enabled and the DHCP driver appears set '
                            'to a plugin aside from "neutron". Node %(name)s '
                            'may not receive proper DHCPv6 provided '
                            'boot parameters.', {'name': task.node.uuid})
            # NOTE(TheJulia): This was added for ISC DHCPd support, however it
            # appears that isc support was never added to neutron and is likely
            # a down stream driver.
            dhcp_opts.append({'opt_name': "!%s,%s" % (DHCP_IPXE_ENCAP_OPTS,
                              boot_file_param),
                              'opt_value': boot_file})
            dhcp_opts.append({'opt_name': boot_file_param,
                              'opt_value': ipxe_script_url})
    else:
        dhcp_opts.append({'opt_name': boot_file_param,
                          'opt_value': boot_file})
        # 210 == tftp server path-prefix or tftp root, will be used to find
        # pxelinux.cfg directory. The pxelinux.0 loader infers this information
        # from it's own path, but Petitboot needs it to be specified by this
        # option since it doesn't use pxelinux.0 loader.
        if not url_boot:
            # Enforce trailing slash
            prefix = os.path.join(CONF.pxe.tftp_root, '')
            dhcp_opts.append(
                {'opt_name': DHCP_TFTP_PATH_PREFIX,
                 'opt_value': prefix})

    if not url_boot:
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
    if not url_boot:
        dhcp_opts.append({'opt_name': 'server-ip-address',
                          'opt_value': CONF.pxe.tftp_server})

    # Append the IP version for all the configuration options
    for opt in dhcp_opts:
        opt.update({'ip_version': use_ip_version})

    return dhcp_opts


def is_ipxe_enabled(task):
    """Return true if ipxe is set.

    :param task: A TaskManager object
    :returns: boolean true if ``[pxe]ipxe_enabled`` is configured
              or if the task driver instance is the iPXE driver.
    """
    return 'ipxe_boot' in task.driver.boot.capabilities


def parse_driver_info(node, mode='deploy'):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver to
    deploy images to, or rescue, the node.

    :param node: a single Node.
    :param mode: Label indicating a deploy or rescue operation being
                 carried out on the node. Supported values are
                 'deploy' and 'rescue'. Defaults to 'deploy', indicating
                 deploy operation is being carried out.
    :returns: A dict with the driver_info values.
    :raises: MissingParameterValue
    """
    info = node.driver_info

    params_to_check = KERNEL_RAMDISK_LABELS[mode]

    d_info = {k: info.get(k) for k in params_to_check}
    if not any(d_info.values()):
        # NOTE(dtantsur): avoid situation when e.g. deploy_kernel comes from
        # driver_info but deploy_ramdisk comes from configuration, since it's
        # a sign of a potential operator's mistake.
        d_info = {k: getattr(CONF.conductor, k) for k in params_to_check}
    error_msg = _("Cannot validate PXE bootloader. Some parameters were"
                  " missing in node's driver_info and configuration")
    deploy_utils.check_for_missing_params(d_info, error_msg)
    return d_info


def get_instance_image_info(task, ipxe_enabled=False):
    """Generate the paths for TFTP files for instance related images.

    This method generates the paths for instance kernel and
    instance ramdisk. This method also updates the node, so caller should
    already have a non-shared lock on the node.

    :param task: A TaskManager instance containing node and context.
    :param ipxe_enabled: Default false boolean to indicate if ipxe
                         is in use by the caller.
    :returns: a dictionary whose keys are the names of the images (kernel,
        ramdisk) and values are the absolute paths of them. If it's a whole
        disk image or node is configured for localboot,
        it returns an empty dictionary.
    """
    ctx = task.context
    node = task.node
    image_info = {}
    # NOTE(pas-ha) do not report image kernel and ramdisk for
    # local boot or whole disk images so that they are not cached
    if (node.driver_internal_info.get('is_whole_disk_image')
            or deploy_utils.get_boot_option(node) == 'local'):
        return image_info
    root_dir = _get_root_dir(ipxe_enabled)
    i_info = node.instance_info
    if i_info.get('boot_iso'):
        image_info['boot_iso'] = (
            i_info['boot_iso'],
            os.path.join(root_dir, node.uuid, 'boot_iso'))

        return image_info

    labels = ('kernel', 'ramdisk')
    image_properties = None
    d_info = deploy_utils.get_image_instance_info(node)
    if not (i_info.get('kernel') and i_info.get('ramdisk')):
        # NOTE(rloo): If both are not specified in instance_info
        # we won't use any of them. We'll use the values specified
        # with the image, which we assume have been set.
        glance_service = service.GlanceImageService(context=ctx)
        image_properties = glance_service.show(
            d_info['image_source'])['properties']
        for label in labels:
            i_info[label] = str(image_properties[label + '_id'])
        node.instance_info = i_info
        node.save()

    anaconda_labels = ()
    if deploy_utils.get_boot_option(node) == 'kickstart':
        # stage2: installer stage2 squashfs image
        # ks_template: anaconda kickstart template
        # ks_cfg - rendered ks_template
        anaconda_labels = ('stage2', 'ks_template', 'ks_cfg')
        if not i_info.get('stage2') or not i_info.get('ks_template'):
            if not image_properties:
                glance_service = service.GlanceImageService(context=ctx)
                image_properties = glance_service.show(
                    d_info['image_source'])['properties']
            if not i_info.get('ks_template'):
                # ks_template is an optional property on the image
                if 'ks_template' not in image_properties:
                    i_info['ks_template'] = CONF.anaconda.default_ks_template
                else:
                    i_info['ks_template'] = str(
                        image_properties['ks_template'])
            if not i_info.get('stage2'):
                if 'stage2_id' not in image_properties:
                    msg = ("'stage2_id' property is missing from the OS image "
                           "%s. The anaconda deploy interface requires this "
                           "to be set with the OS image or in instance_info. "
                           % d_info['image_source'])
                    raise exception.ImageUnacceptable(msg)
                else:
                    i_info['stage2'] = str(image_properties['stage2_id'])
        # NOTE(rloo): This is internally generated; cannot be specified.
        i_info['ks_cfg'] = ''

        node.instance_info = i_info
        node.save()

    for label in labels + anaconda_labels:
        image_info[label] = (
            i_info[label],
            get_file_path_from_label(node.uuid, root_dir, label)
        )

    return image_info


def get_image_info(node, mode='deploy', ipxe_enabled=False):
    """Generate the paths for TFTP files for deploy or rescue images.

    This method generates the paths for the deploy (or rescue) kernel and
    deploy (or rescue) ramdisk.

    :param node: a node object
    :param mode: Label indicating a deploy or rescue operation being
        carried out on the node. Supported values are 'deploy' and 'rescue'.
        Defaults to 'deploy', indicating deploy operation is being carried out.
    :param ipxe_enabled: A default False boolean value to tell the method
                         if the caller is using iPXE.
    :returns: a dictionary whose keys are the names of the images
        (deploy_kernel, deploy_ramdisk, or rescue_kernel, rescue_ramdisk) and
        values are the absolute paths of them.
    :raises: MissingParameterValue, if deploy_kernel/deploy_ramdisk or
        rescue_kernel/rescue_ramdisk is missing in node's driver_info.
    """
    d_info = parse_driver_info(node, mode=mode)

    return get_kernel_ramdisk_info(
        node.uuid, d_info, mode=mode, ipxe_enabled=ipxe_enabled)


def build_deploy_pxe_options(task, pxe_info, mode='deploy',
                             ipxe_enabled=False):
    pxe_opts = {}
    node = task.node
    kernel_label = '%s_kernel' % mode
    ramdisk_label = '%s_ramdisk' % mode
    for label, option in ((kernel_label, 'deployment_aki_path'),
                          (ramdisk_label, 'deployment_ari_path')):
        if ipxe_enabled:
            image_href = pxe_info[label][0]
            if (CONF.pxe.ipxe_use_swift
                    and service_utils.is_glance_image(image_href)):
                pxe_opts[option] = images.get_temp_url_for_glance_image(
                    task.context, image_href)
            else:
                pxe_opts[option] = '/'.join([CONF.deploy.http_url, node.uuid,
                                            label])
        else:
            pxe_opts[option] = os.path.relpath(pxe_info[label][1],
                                               CONF.pxe.tftp_root)
    if ipxe_enabled:
        pxe_opts['initrd_filename'] = ramdisk_label
    return pxe_opts


def build_instance_pxe_options(task, pxe_info, ipxe_enabled=False):
    pxe_opts = {}
    node = task.node

    for label, option in (('kernel', 'aki_path'),
                          ('ramdisk', 'ari_path'),
                          ('stage2', 'stage2_url'),
                          ('ks_template', 'ks_template_path'),
                          ('ks_cfg', 'ks_cfg_url')):
        if label in pxe_info:
            if ipxe_enabled or label in ('stage2', 'ks_template', 'ks_cfg'):
                # NOTE(pas-ha) do not use Swift TempURLs for kernel and
                # ramdisk of user image when boot_option is not local,
                # as this breaks instance reboot later when temp urls
                # have timed out.
                pxe_opts[option] = get_http_url_path_from_label(
                    CONF.deploy.http_url, node.uuid, label)
            else:
                # It is possible that we don't have kernel/ramdisk or even
                # image_source to determine if it's a whole disk image or not.
                # For example, when transitioning to 'available' state
                # for first time from 'manage' state.
                pxe_opts[option] = os.path.relpath(pxe_info[label][1],
                                                   CONF.pxe.tftp_root)

    pxe_opts.setdefault('aki_path', 'no_kernel')
    pxe_opts.setdefault('ari_path', 'no_ramdisk')

    i_info = task.node.instance_info
    try:
        pxe_opts['ramdisk_opts'] = i_info['ramdisk_kernel_arguments']
    except KeyError:
        pass
    try:
        # TODO(TheJulia): Boot iso should change at a later point
        # if we serve more than just as a pass-through.
        if i_info.get('boot_iso'):
            pxe_opts['boot_iso_url'] = '/'.join(
                [CONF.deploy.http_url, node.uuid, 'boot_iso'])
    except KeyError:
        pass

    return pxe_opts


def build_extra_pxe_options(task, ramdisk_params=None):
    pxe_append_params = driver_utils.get_kernel_append_params(
        task.node, default=CONF.pxe.kernel_append_params)
    # Enable debug in IPA according to CONF.debug if it was not
    # specified yet
    if CONF.debug and 'ipa-debug' not in pxe_append_params:
        pxe_append_params += ' ipa-debug=1'
    if ramdisk_params:
        pxe_append_params += ' ' + ' '.join(
            ('%s=%s' % tpl) if tpl[1] is not None else tpl[0]
            for tpl in ramdisk_params.items())
    if task and task.context.global_id:
        pxe_append_params += (
            ' ipa-global-request-id=%s' % task.context.global_id)

    return {'pxe_append_params': pxe_append_params,
            'tftp_server': CONF.pxe.tftp_server,
            'ipxe_timeout': CONF.pxe.ipxe_timeout * 1000}


def build_pxe_config_options(task, pxe_info, service=False,
                             ipxe_enabled=False, ramdisk_params=None):
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
    :param ipxe_enabled: Default false boolean to indicate if ipxe
                         is in use by the caller.
    :param ramdisk_params: the parameters to be passed to the ramdisk.
                           as kernel command-line arguments.
    :returns: A dictionary of pxe options to be used in the pxe bootfile
        template.
    """
    node = task.node
    mode = deploy_utils.rescue_or_deploy_mode(node)
    if service:
        pxe_options = {}
    elif (node.driver_internal_info.get('boot_from_volume')
            and ipxe_enabled):
        pxe_options = get_volume_pxe_options(task)
    else:
        pxe_options = build_deploy_pxe_options(task, pxe_info, mode=mode,
                                               ipxe_enabled=ipxe_enabled)

    # NOTE(pas-ha) we still must always add user image kernel and ramdisk
    # info as later during switching PXE config to service mode the
    # template will not be regenerated anew, but instead edited as-is.
    # This can be changed later if/when switching PXE config will also use
    # proper templating instead of editing existing files on disk.
    pxe_options.update(build_instance_pxe_options(task, pxe_info,
                                                  ipxe_enabled=ipxe_enabled))

    pxe_options.update(build_extra_pxe_options(task, ramdisk_params))

    return pxe_options


def build_service_pxe_config(task, instance_image_info,
                             root_uuid_or_disk_id,
                             ramdisk_boot=False,
                             ipxe_enabled=False,
                             is_whole_disk_image=None,
                             anaconda_boot=False):
    node = task.node
    pxe_config_path = get_pxe_config_file_path(node.uuid,
                                               ipxe_enabled=ipxe_enabled)
    # NOTE(pas-ha) if it is takeover of ACTIVE node or node performing
    # unrescue operation, first ensure that basic PXE configs and links
    # are in place before switching pxe config
    # NOTE(TheJulia): Also consider deploying a valid state to go ahead
    # and check things before continuing, as otherwise deployments can
    # fail if the agent was booted outside the direct actions of the
    # boot interface.
    if (node.provision_state in [states.ACTIVE, states.UNRESCUING,
                                 states.DEPLOYING]
            and not os.path.isfile(pxe_config_path)):
        pxe_options = build_pxe_config_options(task, instance_image_info,
                                               service=True,
                                               ipxe_enabled=ipxe_enabled)
        if ipxe_enabled:
            pxe_config_template = deploy_utils.get_ipxe_config_template(node)
        else:
            pxe_config_template = deploy_utils.get_pxe_config_template(node)
        create_pxe_config(task, pxe_options, pxe_config_template,
                          ipxe_enabled=ipxe_enabled)

    if is_whole_disk_image is None:
        is_whole_disk_image = node.driver_internal_info.get(
            'is_whole_disk_image')

    deploy_utils.switch_pxe_config(
        pxe_config_path, root_uuid_or_disk_id,
        boot_mode_utils.get_boot_mode(node),
        is_whole_disk_image,
        deploy_utils.is_trusted_boot_requested(node),
        deploy_utils.is_iscsi_boot(task), ramdisk_boot,
        ipxe_enabled=ipxe_enabled, anaconda_boot=anaconda_boot)


def build_kickstart_config_options(task):
    """Build the kickstart template options for a node

    This method builds the kickstart template options for a node,
    given all the required parameters.

    The options should then be passed to pxe_utils.create_kickstart_config to
    create the actual config files.

    :param task: A TaskManager object
    :returns: A dictionary of kickstart options to be used in the kickstart
              template.
    """
    params = {}
    node = task.node
    manager_utils.add_secret_token(node, pregenerated=True)
    node.save()
    params['liveimg_url'] = node.instance_info['image_url']
    params['agent_token'] = node.driver_internal_info['agent_secret_token']

    heartbeat_url = '%s/v1/heartbeat/%s' % (
        deploy_utils.get_ironic_api_url().rstrip('/'),
        node.uuid
    )
    params['heartbeat_url'] = heartbeat_url
    return {'ks_options': params}


def get_volume_pxe_options(task):
    """Identify volume information for iPXE template generation."""
    def __return_item_or_first_if_list(item):
        if isinstance(item, list):
            return item[0]
        else:
            return item

    def __get_property(properties, key):
        prop = __return_item_or_first_if_list(properties.get(key, ''))
        if prop != '':
            return prop
        return __return_item_or_first_if_list(properties.get(key + 's', ''))

    def __format_portal(portal, iqn, lun):
        if ':' in portal:
            host, port = portal.split(':')
        else:
            host = portal
            port = ''
        return ("iscsi:%(host)s::%(port)s:%(lun)s:%(iqn)s" %
                {'host': host, 'port': port, 'lun': lun, 'iqn': iqn})

    def __generate_iscsi_url(properties):
        """Returns iscsi url."""
        iqn = __get_property(properties, 'target_iqn')
        lun = __get_property(properties, 'target_lun')
        if 'target_portals' in properties:
            portals = properties.get('target_portals')
            formatted_portals = []
            for portal in portals:
                formatted_portals.append(__format_portal(portal, iqn, lun))
            return ' '.join(formatted_portals)
        else:
            portal = __get_property(properties, 'target_portal')
            return __format_portal(portal, iqn, lun)

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
        extra_targets = []

        for target in task.volume_targets:
            if target.boot_index != 0 and 'iscsi' in target.volume_type:
                iscsi_url = __generate_iscsi_url(target.properties)
                username = target.properties['auth_username']
                password = target.properties['auth_password']
                extra_targets.append({'url': iscsi_url,
                                      'username': username,
                                      'password': password})
        pxe_options.update({'iscsi_volumes': extra_targets,
                            'boot_from_volume': True})
    # TODO(TheJulia): FibreChannel boot, i.e. wwpn in volume_type
    # for FCoE, should go here.
    return pxe_options


def validate_boot_parameters_for_trusted_boot(node):
    """Check if boot parameters are valid for trusted boot."""
    boot_mode = boot_mode_utils.get_boot_mode(node)
    boot_option = deploy_utils.get_boot_option(node)
    is_whole_disk_image = node.driver_internal_info.get('is_whole_disk_image')
    # 'is_whole_disk_image' is not supported by trusted boot, because there is
    # no Kernel/Ramdisk to measure at all.
    if (boot_mode != 'bios'
        or is_whole_disk_image
        or boot_option != 'netboot'):
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


def validate_kickstart_template(ks_template):
    """Validate the kickstart template

    :param ks_template: Path to the kickstart template
    :raises: InvalidKickstartTemplate
    """
    ks_options = {'liveimg_url': 'fake_image_url',
                  'agent_token': 'fake_token',
                  'heartbeat_url': 'fake_heartbeat_url'}
    params = {'ks_options': ks_options}
    try:
        rendered_tmpl = utils.render_template(ks_template, params, strict=True)
    except jinja2.exceptions.UndefinedError as exc:
        msg = (_("The kickstart template includes a variable that is not "
                 "a valid kickstart option. Rendering the template returned "
                 " %(msg)s. The valid options are %(valid_options)s.") %
               {'msg': exc.message,
                'valid_options': ','.join(ks_options.keys())})
        raise exception.InvalidKickstartTemplate(msg)

    missing_required_options = []
    for var, value in ks_options.items():
        if rendered_tmpl.find(value) == -1:
            missing_required_options.append(var)
    if missing_required_options:
        msg = (_("Following required kickstart option variables are missing "
                 "from the kickstart template: %(missing_opts)s.") %
               {'missing_opts': ','.join(missing_required_options)})
        raise exception.InvalidKickstartTemplate(msg)
    return rendered_tmpl


def validate_kickstart_file(ks_cfg):
    """Check if the kickstart file is valid

    :param ks_cfg: Contents of kickstart file to validate
    :raises: InvalidKickstartFile
    """
    if not os.path.isfile('/usr/bin/ksvalidator'):
        LOG.warning(
            "Unable to validate the kickstart file as ksvalidator binary is "
            "missing. Please install pykickstart package to enable "
            "validation of kickstart file."
        )
        return

    with tempfile.NamedTemporaryFile(
            dir=CONF.tempdir, suffix='.cfg', mode='wt') as ks_file:
        ks_file.write(ks_cfg)
        ks_file.flush()
        try:
            utils.execute(
                'ksvalidator', ks_file.name, check_on_exit=[0], attempts=1
            )
        except processutils.ProcessExecutionError as e:
            msg = _(("The kickstart file generated does not pass validation. "
                     "The ksvalidator tool returned the following error: %s") %
                    (e))
            raise exception.InvalidKickstartFile(msg)


def prepare_instance_pxe_config(task, image_info,
                                iscsi_boot=False,
                                ramdisk_boot=False,
                                ipxe_enabled=False,
                                anaconda_boot=False):
    """Prepares the config file for PXE boot

    :param task: a task from TaskManager.
    :param image_info: a dict of values of instance image
                       metadata to set on the configuration file.
    :param iscsi_boot: if boot is from an iSCSI volume or not.
    :param ramdisk_boot: if the boot is to a ramdisk configuration.
    :param ipxe_enabled: Default false boolean to indicate if ipxe
                         is in use by the caller.
    :param anaconda_boot: if the boot is to a anaconda ramdisk configuration.
    :returns: None
    """
    node = task.node
    # Generate options for both IPv4 and IPv6, and they can be
    # filtered down later based upon the port options.
    # TODO(TheJulia): This should be re-tooled during the Victoria
    # development cycle so that we call a single method and return
    # combined options. The method we currently call is relied upon
    # by two eternal projects, to changing the behavior is not ideal.
    dhcp_opts = dhcp_options_for_instance(task, ipxe_enabled,
                                          ip_version=4)
    dhcp_opts += dhcp_options_for_instance(task, ipxe_enabled,
                                           ip_version=6)
    provider = dhcp_factory.DHCPFactory()
    provider.update_dhcp(task, dhcp_opts)
    pxe_config_path = get_pxe_config_file_path(
        node.uuid, ipxe_enabled=ipxe_enabled)
    if not os.path.isfile(pxe_config_path):
        pxe_options = build_pxe_config_options(
            task, image_info, service=ramdisk_boot or anaconda_boot,
            ipxe_enabled=ipxe_enabled)
        if ipxe_enabled:
            pxe_config_template = (
                deploy_utils.get_ipxe_config_template(node))
        else:
            pxe_config_template = (
                deploy_utils.get_pxe_config_template(node))
        create_pxe_config(
            task, pxe_options, pxe_config_template,
            ipxe_enabled=ipxe_enabled)
    deploy_utils.switch_pxe_config(
        pxe_config_path, None,
        boot_mode_utils.get_boot_mode(node), False,
        iscsi_boot=iscsi_boot, ramdisk_boot=ramdisk_boot,
        ipxe_enabled=ipxe_enabled, anaconda_boot=anaconda_boot)


def prepare_instance_kickstart_config(task, image_info, anaconda_boot=False):
    """Prepare to boot anaconda ramdisk by generating kickstart file

    :param task: a task from TaskManager.
    :param image_info: a dict of values of instance image
                       metadata to set on the configuration file.
    :param anaconda_boot: if the boot is to a anaconda ramdisk configuration.
    """
    if not anaconda_boot:
        return
    ks_options = build_kickstart_config_options(task)
    kickstart_template = image_info['ks_template'][1]
    ks_cfg = utils.render_template(kickstart_template, ks_options)
    ks_config_drive = ks_utils.prepare_config_drive(task)
    if ks_config_drive:
        ks_cfg = ks_cfg + ks_config_drive
    utils.write_to_file(image_info['ks_cfg'][1], ks_cfg)


@image_cache.cleanup(priority=25)
class TFTPImageCache(image_cache.ImageCache):
    def __init__(self):
        master_path = CONF.pxe.tftp_master_path or None
        super(TFTPImageCache, self).__init__(
            master_path,
            # MiB -> B
            cache_size=CONF.pxe.image_cache_size * 1024 * 1024,
            # min -> sec
            cache_ttl=CONF.pxe.image_cache_ttl * 60)


def cache_ramdisk_kernel(task, pxe_info, ipxe_enabled=False):
    """Fetch the necessary kernels and ramdisks for the instance."""
    ctx = task.context
    node = task.node
    t_pxe_info = copy.copy(pxe_info)
    if ipxe_enabled:
        path = os.path.join(CONF.deploy.http_root, node.uuid)
    else:
        path = os.path.join(CONF.pxe.tftp_root, node.uuid)
    ensure_tree(path)
    # anaconda deploy will have 'stage2' as one of the labels in pxe_info dict
    if 'stage2' in pxe_info.keys():
        # stage2 will be stored in ipxe http directory so make sure the
        # directory exists.
        file_path = get_file_path_from_label(node.uuid,
                                             CONF.deploy.http_root,
                                             'stage2')
        ensure_tree(os.path.dirname(file_path))
        # ks_cfg is rendered later by the driver using ks_template. It cannot
        # be fetched and cached.
        t_pxe_info.pop('ks_cfg')

    LOG.debug("Fetching necessary kernel and ramdisk for node %s",
              node.uuid)
    deploy_utils.fetch_images(ctx, TFTPImageCache(), list(t_pxe_info.values()),
                              CONF.force_raw_images)


def clean_up_pxe_env(task, images_info, ipxe_enabled=False):
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

    clean_up_pxe_config(task, ipxe_enabled=ipxe_enabled)
    TFTPImageCache().clean_up()


def place_loaders_for_boot(base_path):
    """Place configured bootloaders from the host OS.

    Example: grubaa64.efi:/path/to/grub-aarch64.efi,...

    :param base_path: Destination path where files should be copied to.
    """
    loaders = CONF.pxe.loader_file_paths
    if not loaders or not base_path:
        # Do nothing, return.
        return

    for dest, src in loaders.items():
        (head, _tail) = os.path.split(dest)
        if head:
            if head.startswith('/'):
                # NOTE(TheJulia): The intent here is to error if the operator
                # has put absolute paths in place, as we can and likely should
                # copy to multiple folders based upon the protocol operation
                # being used. Absolute paths are problematic there, where
                # as a relative path is more a "well, that is silly, but okay
                # misconfiguration.
                msg = ('File paths configured for [pxe]loader_file_paths '
                       'must be relative paths. Entry: %s') % dest
                raise exception.IncorrectConfiguration(msg)
            else:
                try:
                    ensure_tree(os.path.join(base_path, head))
                except OSError as e:
                    msg = ('Failed to create supplied directories in '
                           'asset copy paths. Error: %s') % e
                    raise exception.IncorrectConfiguration(msg)

        full_dest = os.path.join(base_path, dest)
        LOG.debug('Copying bootloader %(dest)s from %(src)s.',
                  {'src': src, 'dest': full_dest})
        try:
            shutil.copy2(src, full_dest)
            if CONF.pxe.file_permission:
                os.chmod(full_dest, CONF.pxe.file_permission)
        except OSError as e:
            msg = ('Error encountered while attempting to '
                   'copy a configured bootloader into '
                   'the requested destination. %s' % e)
            LOG.error(msg)
            raise exception.IncorrectConfiguration(error=msg)
