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
               help=_('The storage backend for storing introspection data.'),
               choices=[('none', _('introspection data will not be stored')),
                        ('database', _('introspection data stored in an SQL '
                                       'database')),
                        ('swift', _('introspection data stored in Swift'))],
               default='database'),
    cfg.StrOpt('swift_data_container',
               default='introspection_data_container',
               help=_('The Swift introspection data container to store '
                      'the inventory data.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='inventory')
