# Copyright 2016 Intel Corporation
# Copyright 2014 Rackspace, Inc.
# Copyright 2015 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg

from ironic.common.i18n import _


opts = [
    cfg.StrOpt('backend',
               default='noop',
               choices=[
                   ('noop', 'Do nothing in relation to metrics.'),
                   ('statsd', 'Transmits metrics data to a statsd backend.'),
                   ('collector', 'Collects metrics data and saves it in '
                                 'memory for use by the running application.'),
               ],
               help='Backend to use for the metrics system.'),
    cfg.BoolOpt('prepend_host',
                default=False,
                help='Prepend the hostname to all metric names. '
                     'The format of metric names is '
                     '[global_prefix.][host_name.]prefix.metric_name.'),
    cfg.BoolOpt('prepend_host_reverse',
                default=True,
                help='Split the prepended host value by "." and reverse it '
                     '(to better match the reverse hierarchical form of '
                     'domain names).'),
    cfg.StrOpt('global_prefix',
               help='Prefix all metric names with this value. '
                    'By default, there is no global prefix. '
                    'The format of metric names is '
                    '[global_prefix.][host_name.]prefix.metric_name.'),
    # IPA config options: used by IPA to configure how it reports metric data
    cfg.StrOpt('agent_backend',
               default='noop',
               help=_('Backend for the agent ramdisk to use for metrics. '
                      'Default possible backends are "noop" and "statsd".')),
    cfg.BoolOpt('agent_prepend_host',
                default=False,
                help=_('Prepend the hostname to all metric names sent by the '
                       'agent ramdisk. The format of metric names is '
                       '[global_prefix.][uuid.][host_name.]prefix.'
                       'metric_name.')),
    cfg.BoolOpt('agent_prepend_uuid',
                default=False,
                help=_('Prepend the node\'s Ironic uuid to all metric names '
                       'sent by the agent ramdisk. The format of metric names '
                       'is [global_prefix.][uuid.][host_name.]prefix.'
                       'metric_name.')),
    cfg.BoolOpt('agent_prepend_host_reverse',
                default=True,
                help=_('Split the prepended host value by "." and reverse it '
                       'for metrics sent by the agent ramdisk (to better '
                       'match the reverse hierarchical form of domain '
                       'names).')),
    cfg.StrOpt('agent_global_prefix',
               help=_('Prefix all metric names sent by the agent ramdisk '
                      'with this value. The format of metric names is '
                      '[global_prefix.][uuid.][host_name.]prefix.'
                      'metric_name.'))
]


statsd_opts = [
    cfg.StrOpt('statsd_host',
               default='localhost',
               help='Host for use with the statsd backend.'),
    cfg.PortOpt('statsd_port',
                default=8125,
                help='Port to use with the statsd backend.'),
    cfg.StrOpt('agent_statsd_host',
               default='localhost',
               help=_('Host for the agent ramdisk to use with the statsd '
                      'backend. This must be accessible from networks the '
                      'agent is booted on.')),
    cfg.PortOpt('agent_statsd_port',
                default=8125,
                help=_('Port for the agent ramdisk to use with the statsd '
                       'backend.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='metrics')
    conf.register_opts(statsd_opts, group='metrics_statsd')


def list_opts():
    return [opts, statsd_opts]
