# Copyright 2016 Intel Corporation
# Copyright (c) 2012 NTT DOCOMO, INC.
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
    cfg.StrOpt('http_url',
               help=_("ironic-conductor node's HTTP server URL. "
                      "Example: http://192.1.2.3:8080")),
    cfg.StrOpt('http_root',
               default='/httpboot',
               help=_("ironic-conductor node's HTTP root path.")),
    cfg.IntOpt('erase_devices_priority',
               help=_('Priority to run in-band erase devices via the Ironic '
                      'Python Agent ramdisk. If unset, will use the priority '
                      'set in the ramdisk (defaults to 10 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('erase_devices_metadata_priority',
               help=_('Priority to run in-band clean step that erases '
                      'metadata from devices, via the Ironic Python Agent '
                      'ramdisk. If unset, will use the priority set in the '
                      'ramdisk (defaults to 99 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('shred_random_overwrite_iterations',
               default=1,
               min=0,
               help=_('During shred, overwrite all block devices N times with '
                      'random data. This is only used if a device could not '
                      'be ATA Secure Erased. Defaults to 1.')),
    cfg.BoolOpt('shred_final_overwrite_with_zeros',
                default=True,
                help=_("Whether to write zeros to a node's block devices "
                       "after writing random data. This will write zeros to "
                       "the device even when "
                       "deploy.shred_random_overwrite_iterations is 0. This "
                       "option is only used if a device could not be ATA "
                       "Secure Erased. Defaults to True.")),
    cfg.BoolOpt('continue_if_disk_secure_erase_fails',
                default=False,
                help=_('Defines what to do if an ATA secure erase operation '
                       'fails during cleaning in the Ironic Python Agent. '
                       'If False, the cleaning operation will fail and the '
                       'node will be put in ``clean failed`` state. '
                       'If True, shred will be invoked and cleaning will '
                       'continue.')),
    cfg.BoolOpt('power_off_after_deploy_failure',
                default=True,
                help=_('Whether to power off a node after deploy failure. '
                       'Defaults to True.')),
    cfg.StrOpt('default_boot_option',
               choices=['netboot', 'local'],
               help=_('Default boot option to use when no boot option is '
                      'requested in node\'s driver_info. Currently the '
                      'default is "netboot", but it will be changed to '
                      '"local" in the future. It is recommended to set '
                      'an explicit value for this option.')),
    cfg.BoolOpt('configdrive_use_object_store',
                default=False,
                deprecated_group='conductor',
                deprecated_name='configdrive_use_swift',
                help=_('Whether to upload the config drive to object store. '
                       'Set this option to True to store config drive '
                       'in swift or radosgw.')),
    cfg.StrOpt('object_store_endpoint_type',
               default='swift',
               deprecated_group='glance',
               deprecated_name='temp_url_endpoint_type',
               choices=['swift', 'radosgw'],
               help=_('Type of object store endpoint type to be '
                      'used as a backend')),
]


def register_opts(conf):
    conf.register_opts(opts, group='deploy')
