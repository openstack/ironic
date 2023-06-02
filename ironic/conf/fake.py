#
# Copyright 2022 Red Hat, Inc.
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
    cfg.StrOpt('power_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'power driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('boot_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'boot driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('deploy_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'deploy driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('vendor_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'vendor driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('management_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'management driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('inspect_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'inspect driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('raid_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'raid driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('bios_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'bios driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('storage_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'storage driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('rescue_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'rescue driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
    cfg.StrOpt('firmware_delay',
               default='0',
               help=_('Delay in seconds for operations with the fake '
                      'firmware driver. Two comma-delimited values will '
                      'result in a delay with a triangular random '
                      'distribution, weighted on the first value.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='fake')
