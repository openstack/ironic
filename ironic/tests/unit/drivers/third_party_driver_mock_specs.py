# Copyright 2015 Intel Corporation
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

"""This module provides mock 'specs' for third party modules that can be used
when needing to mock those third party modules"""

# python-dracclient
DRACCLIENT_SPEC = (
    'client',
    'constants',
    'exceptions',
)

DRACCLIENT_CLIENT_MOD_SPEC = (
    'DRACClient',
)

DRACCLIENT_CONSTANTS_MOD_SPEC = (
    'POWER_OFF',
    'POWER_ON',
    'REBOOT',
    'RebootRequired',
    'RaidStatus'
)

DRACCLIENT_CONSTANTS_REBOOT_REQUIRED_MOD_SPEC = (
    'true',
    'optional',
    'false'
)

DRACCLIENT_CONSTANTS_RAID_STATUS_MOD_SPEC = (
    'jbod',
    'raid'
)

# proliantutils
PROLIANTUTILS_SPEC = (
    'exception',
    'ilo',
    'utils',
)

# pywsnmp
PYWSNMP_SPEC = (
    'hlapi',
    'error',
)

# scciclient
SCCICLIENT_SPEC = (
    'irmc',
)
SCCICLIENT_IRMC_SCCI_SPEC = (
    'POWER_OFF',
    'POWER_ON',
    'POWER_RESET',
    'POWER_SOFT_CYCLE',
    'POWER_SOFT_OFF',
    'MOUNT_CD',
    'POWER_RAISE_NMI',
    'UNMOUNT_CD',
    'MOUNT_FD',
    'UNMOUNT_FD',
    'SCCIError',
    'SCCIClientError',
    'SCCIError',
    'SCCIInvalidInputError',
    'get_share_type',
    'get_client',
    'get_report',
    'get_sensor_data',
    'get_virtual_cd_set_params_cmd',
    'get_virtual_fd_set_params_cmd',
    'get_essential_properties',
    'get_capabilities_properties',
)
SCCICLIENT_IRMC_ELCM_SPEC = (
    'backup_bios_config',
    'restore_bios_config',
    'set_secure_boot_mode',
)

SCCICLIENT_VIOM_SPEC = (
    'validate_physical_port_id',
    'VIOMConfiguration',
)

SCCICLIENT_VIOM_CONF_SPEC = (
    'set_lan_port',
    'set_iscsi_volume',
    'set_fc_volume',
    'apply',
    'dump_json',
    'terminate',
)

REDFISH_SPEC = (
    'redfish',
)

SUSHY_SPEC = (
    'auth',
    'exceptions',
    'Sushy',
    'BOOT_SOURCE_TARGET_PXE',
    'BOOT_SOURCE_TARGET_HDD',
    'BOOT_SOURCE_TARGET_CD',
    'BOOT_SOURCE_TARGET_BIOS_SETUP',
    'CHASSIS_INDICATOR_LED_LIT',
    'CHASSIS_INDICATOR_LED_BLINKING',
    'CHASSIS_INDICATOR_LED_OFF',
    'CHASSIS_INDICATOR_LED_UNKNOWN',
    'DRIVE_INDICATOR_LED_LIT',
    'DRIVE_INDICATOR_LED_BLINKING',
    'DRIVE_INDICATOR_LED_OFF',
    'DRIVE_INDICATOR_LED_UNKNOWN',
    'INDICATOR_LED_LIT',
    'INDICATOR_LED_BLINKING',
    'INDICATOR_LED_OFF',
    'INDICATOR_LED_UNKNOWN',
    'SYSTEM_POWER_STATE_ON',
    'SYSTEM_POWER_STATE_POWERING_ON',
    'SYSTEM_POWER_STATE_OFF',
    'SYSTEM_POWER_STATE_POWERING_OFF',
    'RESET_ON',
    'RESET_FORCE_OFF',
    'RESET_GRACEFUL_SHUTDOWN',
    'RESET_GRACEFUL_RESTART',
    'RESET_FORCE_RESTART',
    'RESET_NMI',
    'BOOT_SOURCE_ENABLED_CONTINUOUS',
    'BOOT_SOURCE_ENABLED_ONCE',
    'BOOT_SOURCE_MODE_BIOS',
    'BOOT_SOURCE_MODE_UEFI',
    'PROCESSOR_ARCH_x86',
    'PROCESSOR_ARCH_IA_64',
    'PROCESSOR_ARCH_ARM',
    'PROCESSOR_ARCH_MIPS',
    'PROCESSOR_ARCH_OEM',
    'PROTOCOL_TYPE_iSCSI',
    'PROTOCOL_TYPE_SAS',
    'PROTOCOL_TYPE_SATA',
    'STATE_ENABLED',
    'STATE_DISABLED',
    'STATE_ABSENT',
    'VIRTUAL_MEDIA_CD',
    'VIRTUAL_MEDIA_FLOPPY',
    'VIRTUAL_MEDIA_USBSTICK',
    'APPLY_TIME_IMMEDIATE',
    'APPLY_TIME_ON_RESET',
    'TASK_STATE_COMPLETED',
    'HEALTH_OK',
    'HEALTH_WARNING',
    'HEALTH_CRITICAL',
    'SECURE_BOOT_RESET_KEYS_TO_DEFAULT',
    'SECURE_BOOT_RESET_KEYS_DELETE_ALL',
    'VOLUME_TYPE_RAW_DEVICE',
    'SEVERITY_OK',
    'SEVERITY_WARNING',
    'SEVERITY_CRITICAL',
    'MANAGER_TYPE_BMC',
)

SUSHY_AUTH_SPEC = (
    'BasicAuth',
    'SessionAuth',
    'SessionOrBasicAuth',
)

XCLARITY_SPEC = (
    'client',
    'states',
    'exceptions',
    'models',
    'utils',
)

XCLARITY_CLIENT_CLS_SPEC = (
)

XCLARITY_STATES_SPEC = (
    'STATE_POWERING_OFF',
    'STATE_POWERING_ON',
    'STATE_POWER_OFF',
    'STATE_POWER_ON',
)

# python-ibmcclient
IBMCCLIENT_SPEC = (
    'connect',
    'exceptions',
    'constants',
)
