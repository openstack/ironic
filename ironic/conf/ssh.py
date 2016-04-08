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
    cfg.StrOpt('libvirt_uri',
               default='qemu:///system',
               help=_('libvirt URI.')),
    cfg.IntOpt('get_vm_name_attempts',
               default=3,
               help=_("Number of attempts to try to get VM name used by the "
                      "host that corresponds to a node's MAC address.")),
    cfg.IntOpt('get_vm_name_retry_interval',
               default=3,
               help=_("Number of seconds to wait between attempts to get "
                      "VM name used by the host that corresponds to a "
                      "node's MAC address.")),
]


def register_opts(conf):
    conf.register_opts(opts, group='ssh')
