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
    cfg.StrOpt('url',
               help=_("URL for connecting to neutron. "
                      "Default value translates to 'http://$my_ip:9696' "
                      "when auth_strategy is 'noauth', "
                      "and to discovery from Keystone catalog "
                      "when auth_strategy is 'keystone'.")),
    cfg.IntOpt('url_timeout',
               default=30,
               help=_('Timeout value for connecting to neutron in seconds.')),
    cfg.IntOpt('port_setup_delay',
               default=0,
               min=0,
               help=_('Delay value to wait for Neutron agents to setup '
                      'sufficient DHCP configuration for port.')),
    cfg.IntOpt('retries',
               default=3,
               help=_('Client retries in the case of a failed request.')),
    cfg.StrOpt('auth_strategy',
               default='keystone',
               choices=['keystone', 'noauth'],
               help=_('Authentication strategy to use when connecting to '
                      'neutron. Running neutron in noauth mode (related to '
                      'but not affected by this setting) is insecure and '
                      'should only be used for testing.')),
    cfg.StrOpt('cleaning_network_uuid',
               help=_('Neutron network UUID for the ramdisk to be booted '
                      'into for cleaning nodes. Required for "neutron" '
                      'network interface. It is also required if cleaning '
                      'nodes when using "flat" network interface or "neutron" '
                      'DHCP provider.')),
    cfg.StrOpt('provisioning_network_uuid',
               help=_('Neutron network UUID for the ramdisk to be booted '
                      'into for provisioning nodes. Required for "neutron" '
                      'network interface.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='neutron')
    auth.register_auth_opts(conf, 'neutron')


def list_opts():
    return auth.add_auth_opts(opts)
