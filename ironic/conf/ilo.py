# Copyright 2016 Intel Corporation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
    cfg.IntOpt('client_timeout',
               default=60,
               help=_('Timeout (in seconds) for iLO operations')),
    cfg.PortOpt('client_port',
                default=443,
                help=_('Port to be used for iLO operations')),
    cfg.StrOpt('swift_ilo_container',
               default='ironic_ilo_container',
               help=_('The Swift iLO container to store data.')),
    cfg.IntOpt('swift_object_expiry_timeout',
               default=900,
               help=_('Amount of time in seconds for Swift objects to '
                      'auto-expire.')),
    cfg.BoolOpt('use_web_server_for_images',
                default=False,
                help=_('Set this to True to use http web server to host '
                       'floppy images and generated boot ISO. This '
                       'requires http_root and http_url to be configured '
                       'in the [deploy] section of the config file. If this '
                       'is set to False, then Ironic will use Swift '
                       'to host the floppy images and generated '
                       'boot_iso.')),
    cfg.IntOpt('clean_priority_reset_ilo',
               default=0,
               help=_('Priority for reset_ilo clean step.')),
    cfg.IntOpt('clean_priority_reset_bios_to_default',
               default=10,
               help=_('Priority for reset_bios_to_default clean step.')),
    cfg.IntOpt('clean_priority_reset_secure_boot_keys_to_default',
               default=20,
               help=_('Priority for reset_secure_boot_keys clean step. This '
                      'step will reset the secure boot keys to manufacturing '
                      'defaults.')),
    cfg.IntOpt('clean_priority_clear_secure_boot_keys',
               default=0,
               help=_('Priority for clear_secure_boot_keys clean step. This '
                      'step is not enabled by default. It can be enabled to '
                      'clear all secure boot keys enrolled with iLO.')),
    cfg.IntOpt('clean_priority_reset_ilo_credential',
               default=30,
               help=_('Priority for reset_ilo_credential clean step. This '
                      'step requires "ilo_change_password" parameter to be '
                      'updated in nodes\'s driver_info with the new '
                      'password.')),
    cfg.IntOpt('power_wait',
               default=2,
               help=_('Amount of time in seconds to wait in between power '
                      'operations')),
    cfg.IntOpt('oob_erase_devices_job_status_interval',
               min=10,
               default=300,
               help=_('Interval (in seconds) between periodic erase-devices '
                      'status checks to determine whether the asynchronous '
                      'out-of-band erase-devices was successfully finished or '
                      'not. On an average, a 300GB HDD with default pattern '
                      '"overwrite" would take approximately 9 hours and '
                      '300GB SSD with default pattern "block" would take '
                      'approx. 30 seconds to complete sanitize disk erase.')),
    cfg.StrOpt('ca_file',
               deprecated_for_removal=True,
               deprecated_reason=_('Its being replaced by new configuration '
                                   'parameter "verify_ca".'),
               help=_('CA certificate file to validate iLO.')),
    cfg.StrOpt('verify_ca',
               default='True',
               help=_('CA certificate to validate iLO. This can be either '
                      'a Boolean value, a path to a CA_BUNDLE file or '
                      'directory with certificates of trusted CAs. If set '
                      'to True the driver will verify the host certificates; '
                      'if False the driver will ignore verifying the SSL '
                      'certificate. If it\'s a path the driver will use the '
                      'specified certificate or one of the certificates in '
                      'the directory. Defaults to True.')),
    cfg.StrOpt('default_boot_mode',
               default='auto',
               choices=[('auto', _('based on boot mode settings on the '
                                   'system')),
                        ('bios', _('BIOS boot mode')),
                        ('uefi', _('UEFI boot mode'))],
               help=_('Default boot mode to be used in provisioning when '
                      '"boot_mode" capability is not provided in the '
                      '"properties/capabilities" of the node. The default is '
                      '"auto" for backward compatibility. When "auto" is '
                      'specified, default boot mode will be selected based '
                      'on boot mode settings on the system.')),
    cfg.IntOpt('file_permission',
               default=0o644,
               help=_('File permission for swift-less image hosting with the '
                      'octal permission representation of file access '
                      'permissions. This setting defaults to ``644``, '
                      'or as the octal number ``0o644`` in Python. '
                      'This setting must be set to the octal number '
                      'representation, meaning starting with ``0o``.')),
    cfg.StrOpt('kernel_append_params',
               default='nofb vga=normal',
               mutable=True,
               help=_('Additional kernel parameters to pass down to the '
                      'instance kernel. These parameters can be consumed by '
                      'the kernel or by the applications by reading '
                      '/proc/cmdline. Mind severe cmdline size limit! Can be '
                      'overridden by `instance_info/kernel_append_params` '
                      'property.')),
    cfg.StrOpt('cert_path',
               default='/var/lib/ironic/ilo/',
               help=_('On the ironic-conductor node, directory where ilo '
                      'driver stores the CSR and the cert.')),

]


def register_opts(conf):
    conf.register_opts(opts, group='ilo')
