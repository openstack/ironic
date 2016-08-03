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
    conf.register_opts(opts, group='metrics_statsd')
