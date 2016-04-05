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


def register_opts(conf):
    conf.register_opts(opts, group='metrics')
