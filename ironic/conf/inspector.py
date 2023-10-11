# Copyright 2016 Intel Corporation

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

import os

from oslo_config import cfg

from ironic.common.i18n import _
from ironic.conf import auth


VALID_ADD_PORTS_VALUES = {
    'all': _('all MAC addresses'),
    'active': _('MAC addresses of NICs with IP addresses'),
    'pxe': _('only the MAC address of the PXE NIC'),
    'disabled': _('do not create any ports'),
}
VALID_KEEP_PORTS_VALUES = {
    'all': _('keep all ports, even ones with MAC addresses that are not '
             'present in the inventory'),
    'present': _('keep only ports with MAC addresses present in '
                 'the inventory'),
    'added': _('keep only ports determined by the add_ports option'),
}
DEFAULT_CPU_FLAGS_MAPPING = {
    'vmx': 'cpu_vt',
    'svm': 'cpu_vt',
    'aes': 'cpu_aes',
    'pse': 'cpu_hugepages',
    'pdpe1gb': 'cpu_hugepages_1g',
    'smx': 'cpu_txt',
}

opts = [
    cfg.IntOpt('status_check_period', default=60,
               help=_('period (in seconds) to check status of nodes '
                      'on inspection')),
    cfg.StrOpt('extra_kernel_params', default='',
               help=_('extra kernel parameters to pass to the inspection '
                      'ramdisk when boot is managed by ironic (not '
                      'ironic-inspector). Pairs key=value separated by '
                      'spaces.')),
    cfg.BoolOpt('power_off', default=True,
                help=_('whether to power off a node after inspection '
                       'finishes. Ignored for nodes that have fast '
                       'track mode enabled.')),
    cfg.StrOpt('callback_endpoint_override',
               help=_('endpoint to use as a callback for posting back '
                      'introspection data when boot is managed by ironic. '
                      'Standard keystoneauth options are used by default.')),
    cfg.BoolOpt('require_managed_boot', default=None,
                help=_('require that the in-band inspection boot is fully '
                       'managed by the node\'s boot interface. Set this to '
                       'True if your installation does not have a separate '
                       '(i)PXE boot environment for node discovery. Set '
                       'to False if you need to inspect nodes that are not '
                       'supported by boot interfaces (e.g. because they '
                       'don\'t have ports).')),
    cfg.StrOpt('add_ports',
               default='pxe',
               help=_('Which MAC addresses to add as ports during '
                      'inspection.'),
               choices=list(VALID_ADD_PORTS_VALUES.items())),
    cfg.StrOpt('keep_ports',
               default='all',
               help=_('Which ports (already present on a node) to keep after '
                      'inspection.'),
               choices=list(VALID_KEEP_PORTS_VALUES.items())),
    cfg.BoolOpt('update_pxe_enabled',
                default=True,
                help=_('Whether to update the ports\' pxe_enabled field '
                       'according to the inspection data.')),
    cfg.StrOpt('default_hooks',
               default='ramdisk-error,validate-interfaces,ports,architecture',
               help=_('A comma-separated lists of inspection hooks that are '
                      'run by default. In most cases, the operators will not '
                      'modify this. The default (somewhat conservative) hooks '
                      'will raise an exception in case the ramdisk reports an '
                      'error, validate interfaces in the inventory, create '
                      'ports and set the node\'s cpu architecture property.')),
    cfg.StrOpt('hooks',
               default='$default_hooks',
               help=_('Comma-separated list of enabled hooks for processing '
                      'pipeline. The default for this is $default_hooks. '
                      'Hooks can be added before or after the defaults '
                      'like this: "prehook,$default_hooks,posthook".')),
    cfg.StrOpt('known_accelerators',
               default=os.path.join(
                   '$pybasedir',
                   'drivers/modules/inspector/hooks/known_accelerators.yaml'),
               help=_('Path to the file which contains the known accelerator '
                      'devices, to be used by the "accelerators" inspection '
                      'hook.')),
    cfg.DictOpt('cpu_capabilities',
                default=DEFAULT_CPU_FLAGS_MAPPING,
                help='Mapping between a CPU flag and a node capability to set '
                     'if this CPU flag is present. This configuration option '
                     'is used by the "cpu-capabilities" inspection hook.'),
    cfg.BoolOpt('extra_hardware_strict',
                default=False,
                help=_('If True, refuse to parse extra data (in plugin_data) '
                       'if at least one record is too short. Additionally, '
                       'remove the incoming "data" even if parsing failed. '
                       'This configuration option is used by the '
                       '"extra-hardware" inspection hook.')),
    cfg.MultiStrOpt('pci_device_alias',
                    default=[],
                    help=_('An alias for a PCI device identified by '
                           '\'vendor_id\' and \'product_id\' fields. Format: '
                           '{"vendor_id": "1234", "product_id": "5678", '
                           '"name": "pci_dev1"}. Use double quotes for the '
                           'keys and values.')),
    cfg.ListOpt('physical_network_cidr_map',
                default=[],
                sample_default=('10.10.10.0/24:physnet_a,'
                                '2001:db8::/64:physnet_b'),
                help=_('Mapping of IP subnet CIDR to physical network. When '
                       'the phyical-network inspection hook is enabled, the '
                       '"physical_network" property of corresponding '
                       'baremetal ports is populated based on this mapping.')),
    cfg.BoolOpt('disk_partitioning_spacing',
                default=True,
                help=_('Whether to leave 1 GiB of disk size untouched for '
                       'partitioning. Only has effect when used with the IPA '
                       'as a ramdisk, for older ramdisk local_gb is '
                       'calculated on the ramdisk side. This configuration '
                       'option is used by the "root-device" inspection hook.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='inspector')
    auth.register_auth_opts(conf, 'inspector',
                            service_type='baremetal-introspection')


def list_opts():
    return auth.add_auth_opts(opts, service_type='baremetal-introspection')
