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

from oslo_config import cfg

from ironic.common.i18n import _

opts = [
    # Overrides the global rpc_transport setting so that the conductor
    # and networking service can use different transports if necessary.
    cfg.StrOpt('rpc_transport',
               default=None,
               choices=['json-rpc', 'oslo_messaging'],
               help=_('The transport mechanism used for RPC communication. '
                      'This can be set to "json-rpc" for JSON-RPC, '
                      '"oslo_messaging" for Oslo Messaging, or "none" '
                      'for no transport.')),
    cfg.StrOpt('switch_config_file',
               default='',
               help=_('Path to the switch configuration file that defines '
                      'switches to be acted upon. The config file should be '
                      'in INI format.  For syntax refer to the user guide.')),
    cfg.StrOpt('driver_config_dir',
               default='/var/lib/ironic/networking',
               help=_('The path to the driver configuration directory. This '
                      'is used to dynamically write driver config files that '
                      'are derived from entries in the file specified by the '
                      'switch_config_file option. This directory should not '
                      'be populated with files manually.')),
    cfg.ListOpt('enabled_switch_drivers',
                default=[],
                help=_('A list of switch drivers to load and make available '
                       'for managing network switches. Switch drivers are '
                       'loaded from external projects via entry points in '
                       'the "ironic.networking.switch_drivers" namespace. '
                       'Only drivers listed here will be loaded and made '
                       'available for use. An empty list means no switch '
                       'drivers will be loaded.')),
    cfg.ListOpt('allowed_vlans',
                default=None,
                help=_('A list of VLAN IDs that are allowed to be used for '
                       'port configuration. If not specified (None), all '
                       'VLAN IDs are allowed. If set to an empty list ([]), '
                       'no VLANs are allowed. If set to a list of values, '
                       'only the specified VLAN IDs are allowed. The list '
                       'is a comma separated list of VLAN ID values or range '
                       'of values. For example, 100,101,102-104,106 would '
                       'allow VLANs 100, 101, 102, 103, 104, and 106, but '
                       'not 105. This setting can be overridden on a '
                       'per-switch basis in the switch configuration file.')),
    cfg.StrOpt('cleaning_network',
               default='',
               help=_('The network to use for cleaning nodes.  This should be '
                      'expressed as {access|trunk}/native_vlan=VLAN_ID. Can '
                      'be overridden on a per-node basis using the '
                      'driver_info attribute and specifying this as '
                      '`cleaning_network`')),
    cfg.StrOpt('rescuing_network',
               default='',
               help=_('The network to use for rescuing nodes.  This should be '
                      'expressed as {access|trunk}/native_vlan=VLAN_ID. Can '
                      'be overridden on a per-node basis using the '
                      'driver_info attribute and specifying this as '
                      '`rescuing_network`')),
    cfg.StrOpt('provisioning_network',
               default='',
               help=_('The network to use for provisioning nodes.  This '
                      'should be expressed as '
                      '{access|trunk}/native_vlan=VLAN_ID. Can be overridden '
                      'on a per-node basis using the driver_info attribute '
                      'and specifying this as '
                      '`provisioning_network`')),
    cfg.StrOpt('servicing_network',
               default='',
               help=_('The network to use for servicing nodes.  This '
                      'should be expressed as '
                      '{access|trunk}/native_vlan=VLAN_ID. Can be overridden '
                      'on a per-node basis using the driver_info attribute '
                      'and specifying this as '
                      '`servicing_network`')),
    cfg.StrOpt('inspection_network',
               default='',
               help=_('The network to use for inspecting nodes.  This '
                      'should be expressed as '
                      '{access|trunk}/native_vlan=VLAN_ID. Can be overridden '
                      'on a per-node basis using the driver_info attribute '
                      'and specifying this as '
                      '`inspection_network`')),
    cfg.StrOpt('idle_network',
               default='',
               help=_('The network to use for initial inspecting of nodes. '
                      'If provided switch ports will be configured back to '
                      'this network whenever any of the other networks are '
                      'removed/unconfigured. '
                      'This should be expressed as '
                      '{access|trunk}/native_vlan=VLAN_ID. Can be overridden '
                      'on a per-node basis using the driver_info attribute '
                      'and specifying this as '
                      '`idle_network`'))
]


def register_opts(conf):
    conf.register_opts(opts, group='ironic_networking')


def list_opts():
    return opts
