#
# Copyright 2022 Red Hat, Inc.
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
    cfg.StrOpt('dhcp_optsdir',
               default='/etc/dnsmasq.d/optsdir.d',
               help=_('Directory where the "dnsmasq" provider will write '
                      'option configuration files for an external '
                      'Dnsmasq to read. Use the same path for the '
                      'dhcp-optsdir dnsmasq configuration directive.')),
    cfg.StrOpt('dhcp_hostsdir',
               default='/etc/dnsmasq.d/hostsdir.d',
               help=_('Directory where the "dnsmasq" provider will write '
                      'host configuration files for an external '
                      'Dnsmasq to read. Use the same path for the '
                      'dhcp-hostsdir dnsmasq configuration directive.')),
    cfg.StrOpt('dhcp_leasefile',
               default='/var/lib/dnsmasq/dnsmasq.leases',
               help=_('Dnsmasq leases file for the "dnsmasq" driver to '
                      'discover IP addresses of managed nodes. Use the'
                      'same path for the dhcp-leasefile dnsmasq '
                      'configuration directive.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='dnsmasq')
