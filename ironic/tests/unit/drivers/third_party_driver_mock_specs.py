# Copyright 2015 Intel Corporation
# All Rights Reserved.
# Copyright (c) 2021 Dell Inc. or its subsidiaries.
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

# sushy_oem_idrac
SUSHY_OEM_IDRAC_MOD_SPEC = (
    'PHYSICAL_DISK_STATE_MODE_RAID',
    'PHYSICAL_DISK_STATE_MODE_NONRAID',
    'JOB_TYPE_RT_NO_REBOOT_CONF',
    'JOB_TYPE_RAID_CONF',
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
    'get_irmc_version_str',
)
SCCICLIENT_IRMC_ELCM_SPEC = (
    'backup_bios_config',
    'elcm_request',
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
