# Copyright 2016 Intel Corporation
# Copyright 2014 OpenStack Foundation
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

from oslo_config import cfg

from ironic.common.i18n import _
from ironic.conf import auth

opts = [
    cfg.IntOpt('port_setup_delay',
               default=0,
               min=0,
               help=_('Delay value to wait for Neutron agents to setup '
                      'sufficient DHCP configuration for port.')),
    cfg.IntOpt('retries',
               default=3,
               help=_('Client retries in the case of a failed request.')),
    cfg.StrOpt('cleaning_network',
               help=_('Neutron network UUID or name for the ramdisk to be '
                      'booted into for cleaning nodes. Required for "neutron" '
                      'network interface. It is also required if cleaning '
                      'nodes when using "flat" network interface or "neutron" '
                      'DHCP provider. If a name is provided, it must be '
                      'unique among all networks or cleaning will fail.'),
               deprecated_name='cleaning_network_uuid'),
    cfg.StrOpt('provisioning_network',
               help=_('Neutron network UUID or name for the ramdisk to be '
                      'booted into for provisioning nodes. Required for '
                      '"neutron" network interface. If a name is provided, '
                      'it must be unique among all networks or deploy will '
                      'fail.'),
               deprecated_name='provisioning_network_uuid'),
    cfg.ListOpt('provisioning_network_security_groups',
                default=[],
                help=_('List of Neutron Security Group UUIDs to be '
                       'applied during provisioning of the nodes. '
                       'Optional for the "neutron" network interface and not '
                       'used for the "flat" or "noop" network interfaces. '
                       'If not specified, default security group '
                       'is used.')),
    cfg.ListOpt('cleaning_network_security_groups',
                default=[],
                help=_('List of Neutron Security Group UUIDs to be '
                       'applied during cleaning of the nodes. '
                       'Optional for the "neutron" network interface and not '
                       'used for the "flat" or "noop" network interfaces. '
                       'If not specified, default security group '
                       'is used.')),
    cfg.StrOpt('rescuing_network',
               help=_('Neutron network UUID or name for booting the ramdisk '
                      'for rescue mode. This is not the network that the '
                      'rescue ramdisk will use post-boot -- the tenant '
                      'network is used for that. Required for "neutron" '
                      'network interface, if rescue mode will be used. It '
                      'is not used for the "flat" or "noop" network '
                      'interfaces. If a name is provided, it must be unique '
                      'among all networks or rescue will fail.')),
    cfg.ListOpt('rescuing_network_security_groups',
                default=[],
                help=_('List of Neutron Security Group UUIDs to be applied '
                       'during the node rescue process. Optional for the '
                       '"neutron" network interface and not used for the '
                       '"flat" or "noop" network interfaces. If not '
                       'specified, the default security group is used.')),
    cfg.IntOpt('request_timeout',
               default=45,
               help=_('Timeout for request processing when interacting '
                      'with Neutron. This value should be increased if '
                      'neutron port action timeouts are observed as neutron '
                      'performs pre-commit validation prior returning to '
                      'the API client which can take longer than normal '
                      'client/server interactions.')),
    cfg.BoolOpt('add_all_ports',
                default=False,
                help=_('Option to enable transmission of all ports '
                       'to neutron when creating ports for provisioning, '
                       'cleaning, or rescue. This is done without IP '
                       'addresses assigned to the port, and may be useful '
                       'in some bonded network configurations.')),
    cfg.IntOpt('dhcpv6_stateful_address_count',
               default=1,
               help=_('Number of IPv6 addresses to allocate for ports created '
                      'for provisioning, cleaning, rescue or inspection on '
                      'DHCPv6-stateful networks. Different stages of the '
                      'chain-loading process will request addresses with '
                      'different CLID/IAID. Due to non-identical identifiers '
                      'multiple addresses must be reserved for the host to '
                      'ensure each step of the boot process can successfully '
                      'lease addresses.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='neutron')
    auth.register_auth_opts(conf, 'neutron', service_type='network')


def list_opts():
    return auth.add_auth_opts(opts, service_type='network')
