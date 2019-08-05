# Copyright 2016 Intel Corporation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

from oslo_config import cfg

from ironic.common.i18n import _

opts = [
    cfg.HostAddressOpt('host_ip',
                       default='0.0.0.0',
                       help=_('The IP address or hostname on which ironic-api '
                              'listens.')),
    cfg.PortOpt('port',
                default=6385,
                help=_('The TCP port on which ironic-api listens.')),
    cfg.IntOpt('max_limit',
               default=1000,
               help=_('The maximum number of items returned in a single '
                      'response from a collection resource.')),
    cfg.StrOpt('public_endpoint',
               help=_("Public URL to use when building the links to the API "
                      "resources (for example, \"https://ironic.rocks:6384\")."
                      " If None the links will be built using the request's "
                      "host URL. If the API is operating behind a proxy, you "
                      "will want to change this to represent the proxy's URL. "
                      "Defaults to None. "
                      "Ignored when proxy headers parsing is enabled via "
                      "[oslo_middleware]enable_proxy_headers_parsing option.")
               ),
    cfg.IntOpt('api_workers',
               help=_('Number of workers for OpenStack Ironic API service. '
                      'The default is equal to the number of CPUs available '
                      'if that can be determined, else a default worker '
                      'count of 1 is returned.')),
    cfg.BoolOpt('enable_ssl_api',
                default=False,
                help=_("Enable the integrated stand-alone API to service "
                       "requests via HTTPS instead of HTTP. If there is a "
                       "front-end service performing HTTPS offloading from "
                       "the service, this option should be False; note, you "
                       "will want to enable proxy headers parsing with "
                       "[oslo_middleware]enable_proxy_headers_parsing "
                       "option or configure [api]public_endpoint option "
                       "to set URLs in responses to the SSL terminated one.")),
    cfg.BoolOpt('restrict_lookup',
                default=True,
                help=_('Whether to restrict the lookup API to only nodes '
                       'in certain states.')),
    cfg.IntOpt('ramdisk_heartbeat_timeout',
               default=300,
               deprecated_group='agent', deprecated_name='heartbeat_timeout',
               help=_('Maximum interval (in seconds) for agent heartbeats.')),
]

opt_group = cfg.OptGroup(name='api',
                         title='Options for the ironic-api service')


def register_opts(conf):
    conf.register_group(opt_group)
    conf.register_opts(opts, group=opt_group)
