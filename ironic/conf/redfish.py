# Copyright 2017 Red Hat, Inc.
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
    cfg.IntOpt('connection_attempts',
               min=1,
               default=5,
               help=_('Maximum number of attempts to try to connect '
                      'to Redfish')),
    cfg.IntOpt('connection_retry_interval',
               min=1,
               default=4,
               help=_('Number of seconds to wait between attempts to '
                      'connect to Redfish')),
    cfg.IntOpt('connection_cache_size',
               min=0,
               default=1000,
               help=_('Maximum Redfish client connection cache size. '
                      'Redfish driver would strive to reuse authenticated '
                      'BMC connections (obtained through Redfish Session '
                      'Service). This option caps the maximum number of '
                      'connections to maintain. The value of `0` disables '
                      'client connection caching completely.')),
    cfg.StrOpt('auth_type',
               choices=[('basic', _('Use HTTP basic authentication')),
                        ('session', _('Use HTTP session authentication')),
                        ('auto', _('Try HTTP session authentication first, '
                                   'fall back to basic HTTP authentication'))],
               default='auto',
               help=_('Redfish HTTP client authentication method.')),
    cfg.BoolOpt('use_swift',
                default=True,
                mutable=True,
                help=_('Upload generated ISO images for virtual media boot to '
                       'Swift, then pass temporary URL to BMC for booting the '
                       'node. If set to false, images are placed on the '
                       'ironic-conductor node and served over its '
                       'local HTTP server.')),
    cfg.StrOpt('swift_container',
               default='ironic_redfish_container',
               mutable=True,
               help=_('The Swift container to store Redfish driver data. '
                      'Applies only when `use_swift` is enabled.')),
    cfg.IntOpt('swift_object_expiry_timeout',
               default=900,
               mutable=True,
               help=_('Amount of time in seconds for Swift objects to '
                      'auto-expire. Applies only when `use_swift` is '
                      'enabled.')),
    cfg.StrOpt('kernel_append_params',
               default='nofb nomodeset vga=normal',
               mutable=True,
               help=_('Additional kernel parameters to pass down to the '
                      'instance kernel. These parameters can be consumed by '
                      'the kernel or by the applications by reading '
                      '/proc/cmdline. Mind severe cmdline size limit! Can be '
                      'overridden by `instance_info/kernel_append_params` '
                      'property.')),
    cfg.IntOpt('file_permission',
               default=0o644,
               help=_('File permission for swift-less image hosting with the '
                      'octal permission representation of file access '
                      'permissions. This setting defaults to ``644``, '
                      'or as the octal number ``0o644`` in Python. '
                      'This setting must be set to the octal number '
                      'representation, meaning starting with ``0o``.')),
    cfg.IntOpt('firmware_update_status_interval',
               min=0,
               default=60,
               help=_('Number of seconds to wait between checking for '
                      'completed firmware update tasks')),
    cfg.IntOpt('firmware_update_fail_interval',
               min=0,
               default=60,
               help=_('Number of seconds to wait between checking for '
                      'failed firmware update tasks')),
    cfg.IntOpt('raid_config_status_interval',
               min=0,
               default=60,
               help=_('Number of seconds to wait between checking for '
                      'completed raid config tasks')),
    cfg.IntOpt('raid_config_fail_interval',
               min=0,
               default=60,
               help=_('Number of seconds to wait between checking for '
                      'failed raid config tasks')),
]


def register_opts(conf):
    conf.register_opts(opts, group='redfish')
