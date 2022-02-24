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

from ironic.common import boot_modes
from ironic.common.i18n import _


opts = [
    cfg.StrOpt('http_url',
               help=_("ironic-conductor node's HTTP server URL. "
                      "Example: http://192.1.2.3:8080")),
    cfg.StrOpt('http_root',
               default='/httpboot',
               help=_("ironic-conductor node's HTTP root path.")),
    cfg.StrOpt('external_http_url',
               help=_("URL of the ironic-conductor node's HTTP server for "
                      "boot methods such as virtual media, "
                      "where images could be served outside of the "
                      "provisioning network. Does not apply when Swift is "
                      "used. Defaults to http_url.")),
    cfg.StrOpt('external_callback_url',
               help=_("Agent callback URL of the bare metal API for boot "
                      "methods such as virtual media, where images could be "
                      "served outside of the provisioning network. Defaults "
                      "to the configuration from [service_catalog].")),
    cfg.BoolOpt('enable_ata_secure_erase',
                default=True,
                mutable=True,
                help=_('Whether to support the use of ATA Secure Erase '
                       'during the cleaning process. Defaults to True.')),
    cfg.BoolOpt('enable_nvme_secure_erase',
                default=True,
                mutable=True,
                help=_('Whether to support the use of NVMe Secure Erase '
                       'during the cleaning process. Currently nvme-cli '
                       'format command is supported with user-data and '
                       'crypto modes, depending on device capabilities.'
                       'Defaults to True.')),
    cfg.IntOpt('erase_devices_priority',
               mutable=True,
               help=_('Priority to run in-band erase devices via the Ironic '
                      'Python Agent ramdisk. If unset, will use the priority '
                      'set in the ramdisk (defaults to 10 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('erase_devices_metadata_priority',
               mutable=True,
               help=_('Priority to run in-band clean step that erases '
                      'metadata from devices, via the Ironic Python Agent '
                      'ramdisk. If unset, will use the priority set in the '
                      'ramdisk (defaults to 99 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('delete_configuration_priority',
               mutable=True,
               help=_('Priority to run in-band clean step that erases '
                      'RAID configuration from devices, via the Ironic '
                      'Python Agent ramdisk. If unset, will use the '
                      'priority set in the ramdisk (defaults to 0 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('create_configuration_priority',
               mutable=True,
               help=_('Priority to run in-band clean step that creates '
                      'RAID configuration from devices, via the Ironic '
                      'Python Agent ramdisk. If unset, will use the '
                      'priority set in the ramdisk (defaults to 0 for the '
                      'GenericHardwareManager). If set to 0, will not run '
                      'during cleaning.')),
    cfg.IntOpt('shred_random_overwrite_iterations',
               default=1,
               min=0,
               mutable=True,
               help=_('During shred, overwrite all block devices N times with '
                      'random data. This is only used if a device could not '
                      'be ATA Secure Erased. Defaults to 1.')),
    cfg.BoolOpt('shred_final_overwrite_with_zeros',
                default=True,
                mutable=True,
                help=_("Whether to write zeros to a node's block devices "
                       "after writing random data. This will write zeros to "
                       "the device even when "
                       "deploy.shred_random_overwrite_iterations is 0. This "
                       "option is only used if a device could not be ATA "
                       "Secure Erased. Defaults to True.")),
    cfg.BoolOpt('continue_if_disk_secure_erase_fails',
                default=False,
                mutable=True,
                help=_('Defines what to do if a secure erase operation '
                       '(NVMe or ATA) fails during cleaning in the Ironic '
                       'Python Agent. If False, the cleaning operation will '
                       'fail and the node will be put in ``clean failed`` '
                       'state. If True, shred will be invoked and cleaning '
                       'will continue.')),
    cfg.IntOpt('disk_erasure_concurrency',
               default=1,
               min=1,
               mutable=True,
               help=_('Defines the target pool size used by Ironic Python '
                      'Agent ramdisk to erase disk devices. The number of '
                      'threads created to erase disks will not exceed this '
                      'value or the number of disks to be erased.')),
    cfg.BoolOpt('power_off_after_deploy_failure',
                default=True,
                mutable=True,
                help=_('Whether to power off a node after deploy failure. '
                       'Defaults to True.')),
    cfg.StrOpt('default_boot_option',
               choices=[('netboot', _('boot from a network')),
                        ('local', _('local boot'))],
               default='local',
               mutable=True,
               help=_('Default boot option to use when no boot option is '
                      'requested in node\'s driver_info. Defaults to '
                      '"local". Prior to the Ussuri release, the default '
                      'was "netboot".'),
               deprecated_for_removal=True,
               deprecated_reason=_('Support for network boot will be removed '
                                   'after the Yoga release.')),
    cfg.StrOpt('default_boot_mode',
               choices=[(boot_modes.UEFI, _('UEFI boot mode')),
                        (boot_modes.LEGACY_BIOS, _('Legacy BIOS boot mode'))],
               default=boot_modes.UEFI,
               mutable=True,
               help=_('Default boot mode to use when no boot mode is '
                      'requested in node\'s driver_info, capabilities or '
                      'in the `instance_info` configuration. Currently the '
                      'default boot mode is "%(uefi)s", but it was '
                      '"%(bios)s" previously in Ironic. It is recommended '
                      'to set an explicit value for this option, and if the '
                      'setting or default differs from nodes, to ensure that '
                      'nodes are configured specifically for their desired '
                      'boot mode. This option '
                      'only has effect when management interface supports '
                      'boot mode management') % {
                          'bios': boot_modes.LEGACY_BIOS,
                          'uefi': boot_modes.UEFI}),
    cfg.BoolOpt('configdrive_use_object_store',
                default=False,
                deprecated_group='conductor',
                deprecated_name='configdrive_use_swift',
                mutable=True,
                help=_('Whether to upload the config drive to object store. '
                       'Set this option to True to store config drive '
                       'in a swift endpoint.')),
    cfg.StrOpt('http_image_subdir',
               default='agent_images',
               help=_('The name of subdirectory under ironic-conductor '
                      'node\'s HTTP root path which is used to place instance '
                      'images for the direct deploy interface, when local '
                      'HTTP service is incorporated to provide instance image '
                      'instead of swift tempurls.')),
    cfg.BoolOpt('fast_track',
                default=False,
                mutable=True,
                help=_('Whether to allow deployment agents to perform lookup, '
                       'heartbeat operations during initial states of a '
                       'machine lifecycle and by-pass the normal setup '
                       'procedures for a ramdisk. This feature also enables '
                       'power operations which are part of deployment '
                       'processes to be bypassed if the ramdisk has performed '
                       'a heartbeat operation using the fast_track_timeout '
                       'setting.')),
    cfg.IntOpt('fast_track_timeout',
               default=300,
               min=0,
               max=300,
               mutable=True,
               help=_('Seconds for which the last heartbeat event is to be '
                      'considered valid for the purpose of a fast '
                      'track sequence. This setting should generally be '
                      'less than the number of seconds for "Power-On Self '
                      'Test" and typical ramdisk start-up. This value should '
                      'not exceed the [api]ramdisk_heartbeat_timeout '
                      'setting.')),
    cfg.BoolOpt('erase_skip_read_only',
                default=False,
                mutable=True,
                help=_('If the ironic-python-agent should skip read-only '
                       'devices when running the "erase_devices" clean step '
                       'where block devices are zeroed out. This requires '
                       'ironic-python-agent 6.0.0 or greater. By default '
                       'a read-only device will cause non-metadata based '
                       'cleaning operations to fail due to the possible '
                       'operational security risk of data being retained '
                       'between deployments of the bare metal node.')),
    cfg.StrOpt('ramdisk_image_download_source',
               choices=[('http', _('In case the ramdisk is already a bootable '
                                   'iso, using this option it will be '
                                   'directly provided by an external HTTP '
                                   'service using its full url.')),
                        ('local', _('This is the default behavior. '
                                    'The image is downloaded, prepared and '
                                    'cached locally, to be served from '
                                    'the conductor.')),
                        ('swift', _('Same as "http", but if the image '
                                    'is a Glance UUID, it is exposed via a '
                                    'Swift temporary URL.'))],
               default='local',
               mutable=True,
               help=_('Specifies whether a boot iso image should be served '
                      'from its own original location using the image source '
                      'url directly, or if ironic should cache the image on '
                      'the conductor and serve it from ironic\'s own http '
                      'server.')),
    cfg.StrOpt('iso_master_path',
               default='/var/lib/ironic/master_iso_images',
               help=_('On the ironic-conductor node, directory where master '
                      'ISO images are stored on disk. '
                      'Setting to the empty string disables image caching.')),
    cfg.IntOpt('iso_cache_size',
               default=20480,
               help=_('Maximum size (in MiB) of cache for master ISO images, '
                      'including those in use.')),
    # 10080 here is 1 week - 60*24*7. It is entirely arbitrary in the absence
    # of a facility to disable the ttl entirely.
    cfg.IntOpt('iso_cache_ttl',
               default=10080,
               help=_('Maximum TTL (in minutes) for old master ISO images in '
                      'cache.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='deploy')
