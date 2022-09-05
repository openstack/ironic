# Copyright 2021 Verizon Media
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
import os

from oslo_config import cfg

from ironic.common.i18n import _


ks_group = cfg.OptGroup(name='anaconda',
                        title='Anaconda/kickstart interface options')
opts = [
    cfg.StrOpt('default_ks_template',
               default=os.path.join(
                   '$pybasedir', 'drivers/modules/ks.cfg.template'),
               mutable=True,
               help=_('kickstart template to use when no kickstart template '
                      'is specified in the instance_info or the glance OS '
                      'image.')),
    cfg.BoolOpt('insecure_heartbeat',
                default=False,
                mutable=True,
                help=_('Option to allow the kickstart configuration to be '
                       'informed if SSL/TLS certificate verificaiton should '
                       'be enforced, or not. This option exists largely to '
                       'facilitate easy testing and use of the ``anaconda`` '
                       'deployment interface. When this option is set, '
                       'heartbeat operations, depending on the contents of '
                       'the utilized kickstart template, may not enfore TLS '
                       'certificate verification.')),
]


def register_opts(conf):
    conf.register_group(ks_group)
    conf.register_opts(opts, group='anaconda')
