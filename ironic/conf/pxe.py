# Copyright 2016 Intel Corporation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import os

from oslo_config import cfg
from oslo_config import types as cfg_types

from ironic.common.i18n import _

opts = [
    cfg.StrOpt('kernel_append_params',
               deprecated_name='pxe_append_params',
               default='nofb nomodeset vga=normal',
               mutable=True,
               help=_('Additional append parameters for baremetal PXE boot.')),
    cfg.StrOpt('default_ephemeral_format',
               default='ext4',
               mutable=True,
               help=_('Default file system format for ephemeral partition, '
                      'if one is created.')),
    cfg.StrOpt('images_path',
               default='/var/lib/ironic/images/',
               help=_('On the ironic-conductor node, directory where images '
                      'are stored on disk.')),
    cfg.StrOpt('instance_master_path',
               default='/var/lib/ironic/master_images',
               help=_('On the ironic-conductor node, directory where master '
                      'instance images are stored on disk. '
                      'Setting to the empty string disables image caching.')),
    cfg.IntOpt('image_cache_size',
               default=20480,
               help=_('Maximum size (in MiB) of cache for master images, '
                      'including those in use.')),
    # 10080 here is 1 week - 60*24*7. It is entirely arbitrary in the absence
    # of a facility to disable the ttl entirely.
    cfg.IntOpt('image_cache_ttl',
               default=10080,
               help=_('Maximum TTL (in minutes) for old master images in '
                      'cache.')),
    cfg.StrOpt('pxe_config_template',
               default=os.path.join(
                   '$pybasedir', 'drivers/modules/pxe_config.template'),
               mutable=True,
               help=_('On ironic-conductor node, template file for PXE '
                      'loader configuration.')),
    cfg.StrOpt('ipxe_config_template',
               default=os.path.join(
                   '$pybasedir', 'drivers/modules/ipxe_config.template'),
               mutable=True,
               help=_('On ironic-conductor node, template file for iPXE '
                      'operations.')),
    cfg.StrOpt('uefi_pxe_config_template',
               default=os.path.join(
                   '$pybasedir',
                   'drivers/modules/pxe_grub_config.template'),
               mutable=True,
               help=_('On ironic-conductor node, template file for PXE '
                      'configuration for UEFI boot loader. Generally this '
                      'is used for GRUB specific templates.')),
    cfg.DictOpt('pxe_config_template_by_arch',
                default={},
                mutable=True,
                help=_('On ironic-conductor node, template file for PXE '
                       'configuration per node architecture. '
                       'For example: '
                       'aarch64:/opt/share/grubaa64_pxe_config.template')),
    cfg.StrOpt('tftp_server',
               default='$my_ip',
               help=_("IP address of ironic-conductor node's TFTP server.")),
    cfg.StrOpt('tftp_root',
               default='/tftpboot',
               help=_("ironic-conductor node's TFTP root path. The "
                      "ironic-conductor must have read/write access to this "
                      "path.")),
    cfg.StrOpt('tftp_master_path',
               default='/tftpboot/master_images',
               help=_('On ironic-conductor node, directory where master TFTP '
                      'images are stored on disk. '
                      'Setting to the empty string disables image caching.')),
    cfg.IntOpt('dir_permission',
               help=_("The permission that will be applied to the TFTP "
                      "folders upon creation. This should be set to the "
                      "permission such that the tftpserver has access to "
                      "read the contents of the configured TFTP folder. This "
                      "setting is only required when the operating system's "
                      "umask is restrictive such that ironic-conductor is "
                      "creating files that cannot be read by the TFTP server. "
                      "Setting to <None> will result in the operating "
                      "system's umask to be utilized for the creation of new "
                      "tftp folders. The system default umask is masked out "
                      "on the specified value. It is required that an octal "
                      "representation is specified. For example: 0o755")),
    cfg.IntOpt('file_permission',
               default=0o644,
               help=_('The permission which is used on files created as part '
                      'of configuration and setup of file assets for PXE '
                      'based operations. Defaults to a value of '
                      '0o644. This value must be specified as an octal '
                      'representation. For example: 0o644')),
    cfg.StrOpt('pxe_bootfile_name',
               default='pxelinux.0',
               help=_('Bootfile DHCP parameter.')),
    cfg.StrOpt('pxe_config_subdir',
               default='pxelinux.cfg',
               help=_('Directory in which to create symbolic links which '
                      'represent the MAC or IP address of the ports on '
                      'a node and allow boot loaders to load the PXE '
                      'file for the node. This directory name is relative '
                      'to the PXE or iPXE folders.')),
    cfg.StrOpt('uefi_pxe_bootfile_name',
               default='bootx64.efi',
               help=_('Bootfile DHCP parameter for UEFI boot mode.')),
    cfg.StrOpt('ipxe_bootfile_name',
               default='undionly.kpxe',
               help=_('Bootfile DHCP parameter.')),
    cfg.StrOpt('uefi_ipxe_bootfile_name',
               default='snponly.efi',
               help=_('Bootfile DHCP parameter for UEFI boot mode. If you '
                      'experience problems with booting using it, try '
                      'ipxe.efi.')),
    cfg.DictOpt('pxe_bootfile_name_by_arch',
                default={},
                help=_('Bootfile DHCP parameter per node architecture. '
                       'For example: aarch64:grubaa64.efi')),
    cfg.DictOpt('ipxe_bootfile_name_by_arch',
                default={},
                help=_('Bootfile DHCP parameter per node architecture. '
                       'For example: aarch64:ipxe_aa64.efi')),
    cfg.StrOpt('ipxe_boot_script',
               default=os.path.join(
                   '$pybasedir', 'drivers/modules/boot.ipxe'),
               help=_('On ironic-conductor node, the path to the main iPXE '
                      'script file.')),
    cfg.StrOpt('ipxe_fallback_script',
               help=_('File name (e.g. inspector.ipxe) of an iPXE script to '
                      'fall back to when booting to a MAC-specific script '
                      'fails. When not set, booting will fail in this case.')),
    cfg.IntOpt('ipxe_timeout',
               default=0,
               help=_('Timeout value (in seconds) for downloading an image '
                      'via iPXE. Defaults to 0 (no timeout)')),
    cfg.IntOpt('boot_retry_timeout',
               min=60,
               help=_('Timeout (in seconds) after which PXE boot should be '
                      'retried. Must be less than [conductor]'
                      'deploy_callback_timeout. Disabled by default.')),
    cfg.IntOpt('boot_retry_check_interval',
               default=90, min=1,
               help=_('Interval (in seconds) between periodic checks on PXE '
                      'boot retry. Has no effect if boot_retry_timeout '
                      'is not set.')),
    cfg.StrOpt('ip_version',
               default='4',
               choices=[('4', _('IPv4')),
                        ('6', _('IPv6'))],
               mutable=True,
               deprecated_for_removal=True,
               help=_('The IP version that will be used for PXE booting. '
                      'Defaults to 4. This option has been a no-op for in-tree'
                      'drivers since the Ussuri development cycle.')),
    cfg.BoolOpt('ipxe_use_swift',
                default=False,
                mutable=True,
                help=_("Download deploy and rescue images directly from swift "
                       "using temporary URLs. "
                       "If set to false (default), images are downloaded "
                       "to the ironic-conductor node and served over its "
                       "local HTTP server. "
                       "Applicable only when 'ipxe' compatible boot interface "
                       "is used.")),
    cfg.BoolOpt('enable_netboot_fallback',
                default=False,
                mutable=True,
                help=_('If True, generate a PXE environment even for nodes '
                       'that use local boot. This is useful when the driver '
                       'cannot switch nodes to local boot, e.g. with SNMP '
                       'or with Redfish on machines that cannot do persistent '
                       'boot. Mostly useful for standalone ironic since '
                       'Neutron will prevent incorrect PXE boot.')),
    cfg.Opt('loader_file_paths',
            type=cfg_types.Dict(cfg_types.String(quotes=True)),
            default={},
            help=_('Dictionary describing the bootloaders to load into '
                   'conductor PXE/iPXE boot folders values from the host '
                   'operating system. Formatted as key of destination '
                   'file name, and value of a full path to a file to be '
                   'copied. File assets will have [pxe]file_permission '
                   'applied, if set. If used, the file names should '
                   'match established bootloader configuration settings '
                   'for bootloaders. Use example: '
                   'ipxe.efi:/usr/share/ipxe/ipxe-snponly-x86_64.efi,'
                   'undionly.kpxe:/usr/share/ipxe/undionly.kpxe')),
]


def register_opts(conf):
    conf.register_opts(opts, group='pxe')
