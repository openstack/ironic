# Copyright 2017 LENOVO Development Company, LP
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from ironic.common.i18n import _

opts = [
    cfg.StrOpt('manager_ip',
               help=_('IP address of the XClarity Controller. '
                      'Configuration here is deprecated and will be removed '
                      'in the Stein release. Please update the driver_info '
                      'field to use "xclarity_manager_ip" instead')),
    cfg.StrOpt('username',
               help=_('Username for the XClarity Controller. '
                      'Configuration here is deprecated and will be removed '
                      'in the Stein release. Please update the driver_info '
                      'field to use "xclarity_username" instead')),
    cfg.StrOpt('password',
               secret=True,
               help=_('Password for XClarity Controller username. '
                      'Configuration here is deprecated and will be removed '
                      'in the Stein release. Please update the driver_info '
                      'field to use "xclarity_password" instead')),
    cfg.PortOpt('port',
                default=443,
                help=_('Port to be used for XClarity Controller '
                       'connection.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='xclarity')
