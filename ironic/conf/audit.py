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
    cfg.BoolOpt('enabled',
                default=False,
                help=_('Enable auditing of API requests'
                       ' (for ironic-api service).')),

    cfg.StrOpt('audit_map_file',
               default='/etc/ironic/api_audit_map.conf',
               help=_('Path to audit map file for ironic-api service. '
                      'Used only when API audit is enabled.')),

    cfg.StrOpt('ignore_req_list',
               default='',
               help=_('Comma separated list of Ironic REST API HTTP methods '
                      'to be ignored during audit logging. For example: '
                      'auditing will not be done on any GET or POST '
                      'requests if this is set to "GET,POST". It is used '
                      'only when API audit is enabled.')),

    cfg.BoolOpt('record_payloads', default=False,
                help=_('The payload of the API response to a CRUD request can be '
                       'attached to the event optionally. This will increase the '
                       'size of the events, but brings a lot of value when it '
                       'comes to diagnostics')),

    cfg.BoolOpt('metrics_enabled', default=False,
                help=_('The middleware can emit statistics on emitted events '
                       'using tagged statsd metrics.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='audit')
