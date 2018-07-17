# Copyright 2016 Intel Corporation
# Copyright 2015 FUJITSU LIMITED
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
    cfg.StrOpt('remote_image_share_root',
               default='/remote_image_share_root',
               help=_('Ironic conductor node\'s "NFS" or "CIFS" root path')),
    cfg.StrOpt('remote_image_server',
               help=_('IP of remote image server')),
    cfg.StrOpt('remote_image_share_type',
               default='CIFS',
               choices=[('CIFS', _('CIFS (Common Internet File System) '
                                   'protocol')),
                        ('NFS', _('NFS (Network File System) protocol'))],
               ignore_case=True,
               help=_('Share type of virtual media')),
    cfg.StrOpt('remote_image_share_name',
               default='share',
               help=_('share name of remote_image_server')),
    cfg.StrOpt('remote_image_user_name',
               help=_('User name of remote_image_server')),
    cfg.StrOpt('remote_image_user_password', secret=True,
               help=_('Password of remote_image_user_name')),
    cfg.StrOpt('remote_image_user_domain',
               default='',
               help=_('Domain name of remote_image_user_name')),
    cfg.PortOpt('port',
                default=443,
                choices=[(443, _('port 443')),
                         (80, _('port 80'))],
                help=_('Port to be used for iRMC operations')),
    cfg.StrOpt('auth_method',
               default='basic',
               choices=[('basic', _('Basic authentication')),
                        ('digest', _('Digest authentication'))],
               help=_('Authentication method to be used for iRMC '
                      'operations')),
    cfg.IntOpt('client_timeout',
               default=60,
               help=_('Timeout (in seconds) for iRMC operations')),
    cfg.StrOpt('sensor_method',
               default='ipmitool',
               choices=[('ipmitool', _('IPMItool')),
                        ('scci', _('Fujitsu SCCI (ServerView Common Command '
                                   'Interface)'))],
               help=_('Sensor data retrieval method.')),
    cfg.StrOpt('snmp_version',
               default='v2c',
               choices=[('v1', _('SNMPv1')),
                        ('v2c', _('SNMPv2c')),
                        ('v3', _('SNMPv3'))],
               help=_('SNMP protocol version')),
    cfg.PortOpt('snmp_port',
                default=161,
                help=_('SNMP port')),
    cfg.StrOpt('snmp_community',
               default='public',
               help=_('SNMP community. Required for versions "v1" and "v2c"')),
    cfg.StrOpt('snmp_security',
               help=_('SNMP security name. Required for version "v3"')),
    cfg.IntOpt('snmp_polling_interval',
               default=10,
               help='SNMP polling interval in seconds'),
    cfg.IntOpt('clean_priority_restore_irmc_bios_config',
               default=0,
               help=_('Priority for restore_irmc_bios_config clean step.')),
    cfg.ListOpt('gpu_ids',
                default=[],
                help=_('List of vendor IDs and device IDs for GPU device to '
                       'inspect. List items are in format vendorID/deviceID '
                       'and separated by commas. GPU inspection will use this '
                       'value to count the number of GPU device in a node. If '
                       'this option is not defined, then leave out '
                       'pci_gpu_devices in capabilities property. '
                       'Sample gpu_ids value: 0x1000/0x0079,0x2100/0x0080')),
    cfg.ListOpt('fpga_ids',
                default=[],
                help=_('List of vendor IDs and device IDs for CPU FPGA to '
                       'inspect. List items are in format vendorID/deviceID '
                       'and separated by commas. CPU inspection will use this '
                       'value to find existence of CPU FPGA in a node. If '
                       'this option is not defined, then leave out '
                       'CUSTOM_CPU_FPGA in node traits. '
                       'Sample fpga_ids value: 0x1000/0x0079,0x2100/0x0080')),
    cfg.IntOpt('query_raid_config_fgi_status_interval',
               min=1,
               default=300,
               help=_('Interval (in seconds) between periodic RAID status '
                      'checks to determine whether the asynchronous RAID '
                      'configuration was successfully finished or not. '
                      'Foreground Initialization (FGI) will start 5 minutes '
                      'after creating virtual drives.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='irmc')
