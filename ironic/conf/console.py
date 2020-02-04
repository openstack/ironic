# Copyright 2016 Intel Corporation
# Copyright 2014 International Business Machines Corporation
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
    cfg.StrOpt('terminal',
               default='shellinaboxd',
               help=_('Path to serial console terminal program. Used only '
                      'by Shell In A Box console.')),
    cfg.StrOpt('terminal_cert_dir',
               help=_('Directory containing the terminal SSL cert (PEM) for '
                      'serial console access. Used only by Shell In A Box '
                      'console.')),
    cfg.StrOpt('terminal_pid_dir',
               help=_('Directory for holding terminal pid files. '
                      'If not specified, the temporary directory '
                      'will be used.')),
    cfg.IntOpt('terminal_timeout',
               default=600,
               min=0,
               help=_('Timeout (in seconds) for the terminal session to be '
                      'closed on inactivity. Set to 0 to disable timeout. '
                      'Used only by Socat console.')),
    cfg.IntOpt('subprocess_checking_interval',
               default=1,
               help=_('Time interval (in seconds) for checking the status of '
                      'console subprocess.')),
    cfg.IntOpt('subprocess_timeout',
               default=10,
               help=_('Time (in seconds) to wait for the console subprocess '
                      'to start.')),
    cfg.IntOpt('kill_timeout',
               default=1,
               help=_('Time (in seconds) to wait for the shellinabox console '
                      'subprocess to exit before sending SIGKILL signal.')),
    cfg.IPOpt('socat_address',
              default='$my_ip',
              help=_('IP address of Socat service running on the host of '
                     'ironic conductor. Used only by Socat console.')),
    cfg.StrOpt('port_range',
               regex=r'^\d+:\d+$',
               sample_default='10000:20000',
               help=_('A range of ports available to be used for the console '
                      'proxy service running on the host of ironic '
                      'conductor, in the form of <start>:<stop>. This option '
                      'is used by both Shellinabox and Socat console')),
]


def register_opts(conf):
    conf.register_opts(opts, group='console')
