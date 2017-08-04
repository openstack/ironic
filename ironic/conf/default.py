# Copyright 2016 Intel Corporation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 Red Hat, Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
import socket
import tempfile

from oslo_config import cfg
from oslo_utils import netutils

from ironic.common.i18n import _
from ironic.common import release_mappings as versions


_ENABLED_IFACE_HELP = _('Specify the list of {0} interfaces to load during '
                        'service initialization. Missing {0} interfaces, '
                        'or {0} interfaces which fail to initialize, will '
                        'prevent the ironic-conductor service from starting. '
                        'At least one {0} interface that is supported by each '
                        'enabled hardware type must be enabled here, or the '
                        'ironic-conductor service will not start. '
                        'Must not be an empty list. '
                        'The default value is a recommended set of '
                        'production-oriented {0} interfaces. A complete '
                        'list of {0} interfaces present on your system may '
                        'be found by enumerating the '
                        '"ironic.hardware.interfaces.{0}" entrypoint. '
                        'When setting this value, please make sure that '
                        'every enabled hardware type will have the same '
                        'set of enabled {0} interfaces on every '
                        'ironic-conductor service.')

_DEFAULT_IFACE_HELP = _('Default {0} interface to be used for nodes that '
                        'do not have {0}_interface field set. A complete '
                        'list of {0} interfaces present on your system may '
                        'be found by enumerating the '
                        '"ironic.hardware.interfaces.{0}" entrypoint.')

api_opts = [
    cfg.StrOpt(
        'auth_strategy',
        default='keystone',
        choices=['noauth', 'keystone'],
        help=_('Authentication strategy used by ironic-api. "noauth" should '
               'not be used in a production environment because all '
               'authentication will be disabled.')),
    cfg.BoolOpt('debug_tracebacks_in_api',
                default=False,
                help=_('Return server tracebacks in the API response for any '
                       'error responses. WARNING: this is insecure '
                       'and should not be used in a production environment.')),
    cfg.BoolOpt('pecan_debug',
                default=False,
                help=_('Enable pecan debug mode. WARNING: this is insecure '
                       'and should not be used in a production environment.')),
]

driver_opts = [
    cfg.ListOpt('enabled_drivers',
                default=['pxe_ipmitool'],
                help=_('Specify the list of drivers to load during service '
                       'initialization. Missing drivers, or drivers which '
                       'fail to initialize, will prevent the conductor '
                       'service from starting. The option default is a '
                       'recommended set of production-oriented drivers. A '
                       'complete list of drivers present on your system may '
                       'be found by enumerating the "ironic.drivers" '
                       'entrypoint. An example may be found in the '
                       'developer documentation online.')),
    cfg.ListOpt('enabled_hardware_types',
                default=['ipmi'],
                help=_('Specify the list of hardware types to load during '
                       'service initialization. Missing hardware types, or '
                       'hardware types which fail to initialize, will prevent '
                       'the conductor service from starting. This option '
                       'defaults to a recommended set of production-oriented '
                       'hardware types. '
                       'A complete list of hardware types present on your '
                       'system may be found by enumerating the '
                       '"ironic.hardware.types" entrypoint.')),
    cfg.ListOpt('enabled_boot_interfaces',
                default=['pxe'],
                help=_ENABLED_IFACE_HELP.format('boot')),
    cfg.StrOpt('default_boot_interface',
               help=_DEFAULT_IFACE_HELP.format('boot')),
    cfg.ListOpt('enabled_console_interfaces',
                default=['no-console'],
                help=_ENABLED_IFACE_HELP.format('console')),
    cfg.StrOpt('default_console_interface',
               help=_DEFAULT_IFACE_HELP.format('console')),
    cfg.ListOpt('enabled_deploy_interfaces',
                default=['iscsi', 'direct'],
                help=_ENABLED_IFACE_HELP.format('deploy')),
    cfg.StrOpt('default_deploy_interface',
               help=_DEFAULT_IFACE_HELP.format('deploy')),
    cfg.ListOpt('enabled_inspect_interfaces',
                default=['no-inspect'],
                help=_ENABLED_IFACE_HELP.format('inspect')),
    cfg.StrOpt('default_inspect_interface',
               help=_DEFAULT_IFACE_HELP.format('inspect')),
    cfg.ListOpt('enabled_management_interfaces',
                default=['ipmitool'],
                help=_ENABLED_IFACE_HELP.format('management')),
    cfg.StrOpt('default_management_interface',
               help=_DEFAULT_IFACE_HELP.format('management')),
    cfg.ListOpt('enabled_network_interfaces',
                default=['flat', 'noop'],
                help=_ENABLED_IFACE_HELP.format('network')),
    cfg.StrOpt('default_network_interface',
               help=_DEFAULT_IFACE_HELP.format('network')),
    cfg.ListOpt('enabled_power_interfaces',
                default=['ipmitool'],
                help=_ENABLED_IFACE_HELP.format('power')),
    cfg.StrOpt('default_power_interface',
               help=_DEFAULT_IFACE_HELP.format('power')),
    cfg.ListOpt('enabled_raid_interfaces',
                default=['agent', 'no-raid'],
                help=_ENABLED_IFACE_HELP.format('raid')),
    cfg.StrOpt('default_raid_interface',
               help=_DEFAULT_IFACE_HELP.format('raid')),
    cfg.ListOpt('enabled_storage_interfaces',
                default=['cinder', 'noop'],
                help=_ENABLED_IFACE_HELP.format('storage')),
    cfg.StrOpt('default_storage_interface',
               help=_DEFAULT_IFACE_HELP.format('storage')),
    cfg.ListOpt('enabled_vendor_interfaces',
                default=['ipmitool', 'no-vendor'],
                help=_ENABLED_IFACE_HELP.format('vendor')),
    cfg.StrOpt('default_vendor_interface',
               help=_DEFAULT_IFACE_HELP.format('vendor')),
]

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help=_('Used if there is a formatting error when generating '
                       'an exception message (a programming error). If True, '
                       'raise an exception; if False, use the unformatted '
                       'message.')),
]

hash_opts = [
    cfg.IntOpt('hash_partition_exponent',
               default=5,
               help=_('Exponent to determine number of hash partitions to use '
                      'when distributing load across conductors. Larger '
                      'values will result in more even distribution of load '
                      'and less load when rebalancing the ring, but more '
                      'memory usage. Number of partitions per conductor is '
                      '(2^hash_partition_exponent). This determines the '
                      'granularity of rebalancing: given 10 hosts, and an '
                      'exponent of the 2, there are 40 partitions in the ring.'
                      'A few thousand partitions should make rebalancing '
                      'smooth in most cases. The default is suitable for up '
                      'to a few hundred conductors. Configuring for too many '
                      'partitions has a negative impact on CPU usage.')),
    cfg.IntOpt('hash_distribution_replicas',
               default=1,
               help=_('[Experimental Feature] '
                      'Number of hosts to map onto each hash partition. '
                      'Setting this to more than one will cause additional '
                      'conductor services to prepare deployment environments '
                      'and potentially allow the Ironic cluster to recover '
                      'more quickly if a conductor instance is terminated.')),
    cfg.IntOpt('hash_ring_reset_interval',
               default=180,
               help=_('Interval (in seconds) between hash ring resets.')),
]

image_opts = [
    cfg.BoolOpt('force_raw_images',
                default=True,
                help=_('If True, convert backing images to "raw" disk image '
                       'format.')),
    cfg.StrOpt('isolinux_bin',
               default='/usr/lib/syslinux/isolinux.bin',
               help=_('Path to isolinux binary file.')),
    cfg.StrOpt('isolinux_config_template',
               default=os.path.join('$pybasedir',
                                    'common/isolinux_config.template'),
               help=_('Template file for isolinux configuration file.')),
    cfg.StrOpt('grub_config_template',
               default=os.path.join('$pybasedir',
                                    'common/grub_conf.template'),
               help=_('Template file for grub configuration file.')),
    cfg.StrOpt('ldlinux_c32',
               help=_('Path to ldlinux.c32 file. This file is required for '
                      'syslinux 5.0 or later. If not specified, the file is '
                      'looked for in '
                      '"/usr/lib/syslinux/modules/bios/ldlinux.c32" and '
                      '"/usr/share/syslinux/ldlinux.c32".')),
]

img_cache_opts = [
    cfg.BoolOpt('parallel_image_downloads',
                default=False,
                help=_('Run image downloads and raw format conversions in '
                       'parallel.')),
]

netconf_opts = [
    cfg.StrOpt('my_ip',
               default=netutils.get_my_ipv4(),
               sample_default='127.0.0.1',
               help=_('IP address of this host. If unset, will determine the '
                      'IP programmatically. If unable to do so, will use '
                      '"127.0.0.1".')),
]

# NOTE(mariojv) By default, accessing this option when it's unset will return
# None, indicating no notifications will be sent. oslo.config returns None by
# default for options without set defaults that aren't required.
notification_opts = [
    cfg.StrOpt('notification_level',
               choices=['debug', 'info', 'warning', 'error', 'critical'],
               help=_('Specifies the minimum level for which to send '
                      'notifications. If not set, no notifications will '
                      'be sent. The default is for this option to be unset.'))
]

path_opts = [
    cfg.StrOpt('pybasedir',
               default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                    '../')),
               sample_default='/usr/lib/python/site-packages/ironic/ironic',
               help=_('Directory where the ironic python module is '
                      'installed.')),
    cfg.StrOpt('bindir',
               default='$pybasedir/bin',
               help=_('Directory where ironic binaries are installed.')),
    cfg.StrOpt('state_path',
               default='$pybasedir',
               help=_("Top-level directory for maintaining ironic's state.")),
]

portgroup_opts = [
    cfg.StrOpt(
        'default_portgroup_mode', default='active-backup',
        help=_(
            'Default mode for portgroups. Allowed values can be found in the '
            'linux kernel documentation on bonding: '
            'https://www.kernel.org/doc/Documentation/networking/bonding.txt.')
    ),
]

service_opts = [
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               sample_default='localhost',
               help=_('Name of this node. This can be an opaque identifier. '
                      'It is not necessarily a hostname, FQDN, or IP address. '
                      'However, the node name must be valid within '
                      'an AMQP key, and if using ZeroMQ, a valid '
                      'hostname, FQDN, or IP address.')),
    cfg.StrOpt('pin_release_version',
               choices=versions.RELEASE_VERSIONS,
               # TODO(xek): mutable=True,
               help=_('Used for rolling upgrades. Setting this option '
                      'downgrades (or pins) the internal ironic RPC '
                      'communication and database objects to their respective '
                      'versions, so they are compatible with older services. '
                      'When doing a rolling upgrade from version N to version '
                      'N+1, set (to pin) this to N. To unpin (default), leave '
                      'it unset and the latest versions of RPC communication '
                      'and database objects will be used.')),
]

utils_opts = [
    cfg.StrOpt('rootwrap_config',
               default="/etc/ironic/rootwrap.conf",
               help=_('Path to the rootwrap configuration file to use for '
                      'running commands as root.')),
    cfg.StrOpt('tempdir',
               default=tempfile.gettempdir(),
               sample_default='/tmp',
               help=_('Temporary working directory, default is Python temp '
                      'dir.')),
]


def register_opts(conf):
    conf.register_opts(api_opts)
    conf.register_opts(driver_opts)
    conf.register_opts(exc_log_opts)
    conf.register_opts(hash_opts)
    conf.register_opts(image_opts)
    conf.register_opts(img_cache_opts)
    conf.register_opts(netconf_opts)
    conf.register_opts(notification_opts)
    conf.register_opts(path_opts)
    conf.register_opts(portgroup_opts)
    conf.register_opts(service_opts)
    conf.register_opts(utils_opts)
