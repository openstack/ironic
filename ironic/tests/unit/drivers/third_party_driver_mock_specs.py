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
    'exceptions'
)

DRACCLIENT_CLIENT_MOD_SPEC = (
    'DRACClient',
)

DRACCLIENT_CONSTANTS_MOD_SPEC = (
    'POWER_OFF',
    'POWER_ON',
    'REBOOT'
)

# iboot
IBOOT_SPEC = (
    'iBootInterface',
)

# ironic_inspector
IRONIC_INSPECTOR_CLIENT_SPEC = (
    'ClientV1',
)


class InspectorClientV1Specs(object):
    def __init__(self, session, inspector_url, api_version):
        pass

    def introspect(self, uuid):
        pass

    def get_status(self, uuid):
        pass


# proliantutils
PROLIANTUTILS_SPEC = (
    'exception',
    'ilo',
    'utils',
)

# pyghmi
PYGHMI_SPEC = (
    'exceptions',
    'ipmi',
)
PYGHMI_EXC_SPEC = (
    'IpmiException',
)
PYGHMI_IPMI_SPEC = (
    'command',
)
PYGHMI_IPMICMD_SPEC = (
    'boot_devices',
    'Command',
)

# pyremotevbox
PYREMOTEVBOX_SPEC = (
    'exception',
    'vbox',
)
PYREMOTEVBOX_EXC_SPEC = (
    'PyRemoteVBoxException',
    'VmInWrongPowerState',
)
PYREMOTEVBOX_VBOX_SPEC = (
    'VirtualBoxHost',
)

# pywsman
PYWSMAN_SPEC = (
    'Client',
    'ClientOptions',
    'EndPointReference',
    'FLAG_ENUMERATION_OPTIMIZATION',
    'Filter',
    'XmlDoc',
    'wsman_transport_set_verify_host',
    'wsman_transport_set_verify_peer',
)

# pywsnmp
PYWSNMP_SPEC = (
    'entity',
    'error',
    'proto',
)

# scciclient
SCCICLIENT_SPEC = (
    'irmc',
)
SCCICLIENT_IRMC_SCCI_SPEC = (
    'POWER_OFF',
    'POWER_ON',
    'POWER_RESET',
    'MOUNT_CD',
    'UNMOUNT_CD',
    'MOUNT_FD',
    'UNMOUNT_FD',
    'SCCIClientError',
    'SCCIInvalidInputError',
    'get_share_type',
    'get_client',
    'get_report',
    'get_sensor_data',
    'get_virtual_cd_set_params_cmd',
    'get_virtual_fd_set_params_cmd',
    'get_essential_properties',
)

ONEVIEWCLIENT_SPEC = (
    'client',
    'states',
    'exceptions',
    'models',
    'utils',
)

ONEVIEWCLIENT_CLIENT_CLS_SPEC = (
)

ONEVIEWCLIENT_STATES_SPEC = (
    'ONEVIEW_POWER_OFF',
    'ONEVIEW_POWERING_OFF',
    'ONEVIEW_POWER_ON',
    'ONEVIEW_POWERING_ON',
    'ONEVIEW_RESETTING',
    'ONEVIEW_ERROR',
)

# seamicro
SEAMICRO_SPEC = (
    'client',
    'exceptions',
)
# seamicro.client module
SEAMICRO_CLIENT_MOD_SPEC = (
    'Client',
)
SEAMICRO_EXC_SPEC = (
    'ClientException',
    'UnsupportedVersion',
)
