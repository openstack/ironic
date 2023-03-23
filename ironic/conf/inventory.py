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
    cfg.StrOpt('data_backend',
               help=_('The storage backend for storing inspection data.'),
               choices=[
                   ('none', _('do not store inspection data')),
                   ('database', _('store in the service database')),
                   ('swift', _('store in the Object Storage (swift)')),
               ],
               default='database'),
    cfg.StrOpt('swift_data_container',
               default='introspection_data_container',
               help=_('The Swift container prefix to store the inspection '
                      'data (separately inventory and plugin data).')),
]


def register_opts(conf):
    conf.register_opts(opts, group='inventory')
